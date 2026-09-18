# RAMMS toolset — exposes the project's own test surface as MCP tools.
#
# Epic's stock 5.8 toolsets cover agent skills and editor context; nothing there
# reaches PIE, the robots, or the physics backends. These tools wrap the same
# calls the PIE runners in Scripts/pie_tests/base_component/ make, so an
# assistant can drive and inspect a running sim without a round trip through
# editor_remote_exec.py.
#
# Conventions:
#   - Every tool returns a JSON string. Callers parse one shape, not six.
#   - `robot` is a partial, case-insensitive actor name; "" means the only one.
#   - Read-only tools work in the editor world too, so they answer before play.

import unreal

import toolset_registry

from . import _helpers as H


@unreal.uclass()
class RammsToolset(unreal.ToolsetDefinition):
    """Inspect and drive the RAMMS simulation: play-in-editor, the robots'
    control surfaces, and the Chaos / MuJoCo / Newton physics backends."""

    # ---------------------------------------------------------------- world

    @toolset_registry.tool_call
    @staticmethod
    def sim_status() -> str:
        """Summarize the editor and simulation state.

        Reports whether play-in-editor is running, which map is loaded, and
        which robots are present. Start here; most other tools need PIE.

        Returns:
            JSON with playing, map, world and robots.
        """
        world = H.active_world()
        robots = H.robot_actors(world)
        return H.dumps(
            {
                "playing": H.is_playing(),
                # During PIE the editor world is a separate object; report the
                # world actually being inspected so the answer is never blank.
                "map": world.get_path_name() if world else "",
                "world": world.get_name() if world else "",
                "robot_count": len(robots),
                "robots": [a.get_name() for a in robots],
            }
        )

    @toolset_registry.tool_call
    @staticmethod
    def begin_pie(map_path: str = "") -> str:
        """Start play-in-editor, optionally loading a map first.

        Args:
            map_path: Map to load before playing, e.g. /Game/Maps/Map_Demo.
                Empty keeps the map already open.

        Returns:
            JSON with the requested map and the resulting state.
        """
        les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        if map_path:
            current = H.editor_world().get_path_name()
            want = "%s.%s" % (map_path, map_path.rsplit("/", 1)[-1])
            if current != want:
                les.load_level(map_path)
        les.editor_request_begin_play()
        # Begin play is deferred by a frame or more; the caller polls sim_status
        # rather than this returning a world that does not exist yet.
        return H.dumps({"requested": True, "map": map_path or "current", "note": "poll sim_status until playing is true"})

    @toolset_registry.tool_call
    @staticmethod
    def end_pie() -> str:
        """Stop play-in-editor.

        Returns:
            JSON confirming the request.
        """
        unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).editor_request_end_play()
        return H.dumps({"requested": True})

    # ------------------------------------------------------ control surface

    @toolset_registry.tool_call
    @staticmethod
    def describe_controls(robot: str = "", group: str = "") -> str:
        """List a robot's control axes: ids, kinds, units, ranges.

        The control surface is the single sink the UI panels, the input map and
        remote clients all command through, so these ids are what every other
        control tool takes.

        Args:
            robot: Partial actor name; empty means the only robot present.
            group: Optional group filter, e.g. Drive, Lift, Arm, Gripper.

        Returns:
            JSON with the robot name, its groups, and one entry per axis.
        """
        actor = H.find_robot(robot)
        cs = H.surface_of(actor)
        axes = []
        for a in H.axis_records(cs):
            gid = str(a.get_editor_property("group"))
            if group and group.lower() != gid.lower():
                continue
            # Range is an FVector2D: X is the minimum, Y the maximum. An
            # unbounded axis (raw motors) leaves min >= max, matching
            # FRammsControlAxis::Clamp, which skips clamping in that case.
            rng = a.get_editor_property("range")
            bounded = rng.x < rng.y
            axes.append(
                {
                    "id": str(a.get_editor_property("id")),
                    "group": gid,
                    "display_name": str(a.get_editor_property("display_name")),
                    "kind": H.enum_name(a.get_editor_property("kind")),
                    "units": str(a.get_editor_property("units")),
                    "min": rng.x if bounded else None,
                    "max": rng.y if bounded else None,
                    "bounded": bounded,
                    "default": a.get_editor_property("default_value"),
                    "read_only": bool(a.get_editor_property("read_only")),
                    "readback": bool(a.get_editor_property("readback")),
                }
            )
        return H.dumps(
            {
                "robot": actor.get_name(),
                "groups": sorted({a["group"] for a in axes}),
                "count": len(axes),
                "axes": axes,
            }
        )

    @toolset_registry.tool_call
    @staticmethod
    def read_control(robot: str = "", control_id: str = "") -> str:
        """Read one axis, or every axis when control_id is empty.

        Returns the live value and the commanded target separately. They differ
        whenever something is still moving toward a setpoint, and a controller
        reports the target it actually holds even if that target was set on it
        directly rather than through the surface.

        Args:
            robot: Partial actor name; empty means the only robot present.
            control_id: Axis id, e.g. drive.forward. Empty reads all axes.

        Returns:
            JSON with value, target and owner per axis.
        """
        actor = H.find_robot(robot)
        cs = H.surface_of(actor)
        ids = [control_id] if control_id else [str(a.get_editor_property("id")) for a in H.axis_records(cs)]
        if control_id and H.axis_named(cs, control_id) is None:
            raise RuntimeError("no control '%s' on %s; try describe_controls" % (control_id, actor.get_name()))
        out = []
        for cid in ids:
            # The binding collapses GetAxisTarget's bool return and out-param:
            # it yields the float when a target is held, None when none is.
            target = cs.get_axis_target(cid)
            out.append(
                {
                    "id": cid,
                    "value": cs.get_axis_value(cid),
                    "target": target,
                    "has_target": target is not None,
                    "owner": H.enum_name(cs.get_axis_owner(cid)),
                }
            )
        return H.dumps({"robot": actor.get_name(), "controls": out})

    @toolset_registry.tool_call
    @staticmethod
    def set_control(robot: str, control_id: str, value: float) -> str:
        """Command one axis through the control surface, as Script source.

        Arbitration still applies: Autonomy and Remote outrank Script, so a
        refused write is a real answer, not a failure. Release it afterwards
        with release_control or the hold persists.

        Args:
            robot: Partial actor name; empty means the only robot present.
            control_id: Axis id, e.g. drive.forward.
            value: Target value, in the axis units from describe_controls.

        Returns:
            JSON with whether the write was accepted and the resulting state.
        """
        actor = H.find_robot(robot)
        cs = H.surface_of(actor)
        if H.axis_named(cs, control_id) is None:
            raise RuntimeError("no control '%s' on %s; try describe_controls" % (control_id, actor.get_name()))
        accepted = bool(cs.set_control(control_id, float(value), H.SCRIPT_SOURCE))
        return H.dumps(
            {
                "robot": actor.get_name(),
                "id": control_id,
                "requested": value,
                "accepted": accepted,
                "owner": H.enum_name(cs.get_axis_owner(control_id)),
                "target": cs.get_axis_target(control_id),
                "value": cs.get_axis_value(control_id),
            }
        )

    @toolset_registry.tool_call
    @staticmethod
    def release_control(robot: str = "", control_id: str = "") -> str:
        """Release a Script hold on one axis, or on every axis.

        Args:
            robot: Partial actor name; empty means the only robot present.
            control_id: Axis id to release. Empty releases all of them.

        Returns:
            JSON listing what was released.
        """
        actor = H.find_robot(robot)
        cs = H.surface_of(actor)
        ids = [control_id] if control_id else [str(a.get_editor_property("id")) for a in H.axis_records(cs)]
        released = [{"id": cid, "released": bool(cs.release_control(cid, H.SCRIPT_SOURCE))} for cid in ids]
        return H.dumps({"robot": actor.get_name(), "released": released})

    # ------------------------------------------------------------- physics

    @toolset_registry.tool_call
    @staticmethod
    def physics_status(robot: str) -> str:
        """Report which physics backend a robot drives, plus every motor's state.

        Covers the shared robot base (Chaos or MuJoCo) and, when the Newton
        component is present, the Newton bridge: whether its runtime library
        loaded and what its own summary says. The per-motor value and velocity
        are the readback the backends agree on, so they are the right thing to
        compare when checking one backend against another.

        Args:
            robot: Partial actor name. Pass "" for the only robot present.

        Returns:
            JSON with the robot base, its motors, and any Newton backend status.
        """
        actor = H.find_robot(robot)
        payload = {"robot": actor.get_name(), "robot_base": None, "newton": None}

        base = H.component_named(actor, "RammsRobotBaseComponent")
        if base is not None:
            motors = []
            for mid in base.get_motor_ids():
                name = str(mid)
                motors.append(
                    {
                        "id": name,
                        "type": H.enum_name(base.get_motor_type(name)),
                        "value": base.get_motor_value(name),
                        "velocity": base.get_motor_velocity(name),
                    }
                )
            payload["robot_base"] = {
                "component": base.get_name(),
                "has_backend": bool(base.has_backend()),
                "backend": H.enum_name(base.get_editor_property("backend")),
                "motor_count": base.get_motor_count(),
                "motors": motors,
            }

        newton = H.component_named(actor, "RammsNewtonPhysicsComponent")
        if newton is None:
            newton = H.component_named(actor, "RammsNewtonArticulatedRobotComponent")
        if newton is not None and hasattr(newton, "get_backend_status"):
            st = newton.get_backend_status()
            payload["newton"] = {
                "component": newton.get_name(),
                "mode": H.enum_name(st.get_editor_property("mode")),
                "runtime_ready": bool(st.get_editor_property("runtime_ready")),
                "runtime_library_loaded": bool(st.get_editor_property("runtime_library_loaded")),
                "source_checkout_detected": bool(st.get_editor_property("source_checkout_detected")),
                "headers_detected": bool(st.get_editor_property("headers_detected")),
                "runtime_library_path": str(st.get_editor_property("runtime_library_path")),
                "summary": str(st.get_editor_property("summary")),
            }
        return H.dumps(payload)

    @toolset_registry.tool_call
    @staticmethod
    def newton_probe(force_reprobe: bool) -> str:
        """Ask the Newton subsystem whether its out-of-process worker is usable.

        This runs the plugin's real capability probe — it launches the worker
        and reports what it found — rather than inspecting configuration, so a
        true answer here means Newton can actually load and step on this
        machine. Also reports the pinned virtual environment the plugin
        resolves its interpreter from when no override is set.

        Args:
            force_reprobe: Re-run the probe instead of reusing a cached result.

        Returns:
            JSON with the probe capabilities and the interpreter it would use.
        """
        import os

        sub = unreal.get_engine_subsystem(unreal.RammsNewtonPhysicsSubsystem)
        if sub is None:
            raise RuntimeError("RammsNewtonPhysicsSubsystem is not available")

        caps = sub.probe_availability(bool(force_reprobe))
        payload = {"probing": bool(sub.is_probing())}
        for name in ("probed", "available", "newton_version", "python_version",
                     "cuda_available", "error", "solvers"):
            try:
                value = caps.get_editor_property(name)
                payload[name] = [str(v) for v in value] if hasattr(value, "__iter__") and not isinstance(value, str) else value
            except Exception:
                pass

        # The plugin falls back to a pinned venv under the plugin's Scripts dir
        # when the setting is empty, which is the normal configuration. The
        # settings object itself is not exposed to Python, so report the
        # filesystem facts that decide whether that fallback resolves.
        project = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir())
        scripts = os.path.join(project, "Plugins", "RammsNewtonPhysics", "Scripts")
        pinned = os.path.join(scripts, ".venv", "Scripts" if os.name == "nt" else "bin",
                              "python.exe" if os.name == "nt" else "python")
        payload["scripts_dir"] = scripts
        payload["pinned_venv_interpreter"] = pinned
        payload["pinned_venv_exists"] = os.path.exists(pinned)
        return H.dumps(payload)

    @toolset_registry.tool_call
    @staticmethod
    def newton_status(robot: str) -> str:
        """Report the Newton solver component's state on a robot.

        The solver binds to URLab's physics engine and takes over stepping by
        installing a custom step handler, so "is it stepping" is the question
        that matters; the status text carries the reason when it is not.

        Args:
            robot: Partial actor name. Pass "" for the only robot present, or
                "*" to report every actor that carries a solver component.

        Returns:
            JSON with each solver's stepping state, status text and model info.
        """
        if robot == "*":
            world = H.active_world()
            actors = []
            if world is not None:
                for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor):
                    if H.component_named(a, "RammsNewtonSolverComponent") is not None:
                        actors.append(a)
        else:
            actors = [H.find_robot(robot)]

        out = []
        for actor in actors:
            solver = H.component_named(actor, "RammsNewtonSolverComponent")
            if solver is None:
                out.append({"actor": actor.get_name(), "solver": None})
                continue
            entry = {
                "actor": actor.get_name(),
                "component": solver.get_name(),
                "stepping": bool(solver.is_newton_stepping()),
                "status": str(solver.get_status_text()),
            }
            try:
                info = solver.get_model_info()
                entry["model"] = {
                    "solver": str(info.get_editor_property("solver")),
                    "timestep": info.get_editor_property("timestep"),
                    "nq": info.get_editor_property("nq"),
                    "nv": info.get_editor_property("nv"),
                }
            except Exception as exc:
                entry["model_error"] = str(exc)
            out.append(entry)
        return H.dumps({"solvers": out, "count": len(out)})
