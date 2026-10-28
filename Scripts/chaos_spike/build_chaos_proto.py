"""Editor: build a Chaos robot from mjcf_chaos_export.py's JSON in a new level: one static mesh (the body's
collision hull) per MuJoCo body, welded bodies attached, a PhysicsConstraintActor per joint and per connect
equality, position drives from the actuators. Reads and logs in Saved/ChaosSpike (build.log)."""
import json, math, os, unreal
CH = os.path.join(os.path.abspath(unreal.Paths.project_saved_dir()), "ChaosSpike").replace("\\", "/")   # data: JSON in, logs and runs out
SRC = os.path.join(os.path.abspath(unreal.Paths.project_dir()), "Scripts", "chaos_spike")
os.makedirs(CH, exist_ok=True)
PKG = "/Game/ChaosProto"
_CP_OPTS = {k: globals().pop(k) for k in list(globals()) if k.startswith("CP_")}   # consumed: the editor's globals outlive a run
def _build(opts):
    log = []
    def L(m): log.append(str(m)); open(CH + "/build.log", "w").write("\n".join(log) + "\n")
    try:
        J = json.load(open(CH + "/" + opts.get("CP_JSON", "gen3_2f85_chaos.json")))
        les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        eas = unreal.EditorAssetLibrary
        sme = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
        acs = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        lvl = PKG + "/Map_ChaosProto"
        if not eas.does_asset_exist(lvl):
            ok = les.new_level_from_template(lvl, "/Engine/Maps/Templates/Template_Default")
            L("new level %s" % ok)
        else:
            les.load_level(lvl)
            for a in acs.get_all_level_actors():
                if str(a.get_folder_path()) == "ChaosRobot": acs.destroy_actor(a)
        base_z = float(opts.get("CP_BASE_Z", 0.0))
        meshes = {}
        for b in J["bodies"]:
            if not b["hull"]: continue
            path = "%s/Meshes/SM_%s" % (PKG, b["name"])
            if not eas.does_asset_exist(path): eas.duplicate_asset("/Engine/BasicShapes/Cube", path)
            sm = unreal.load_asset(path)
            desc = unreal.StaticMesh.create_static_mesh_description(sm)
            pg = desc.create_polygon_group()
            V = b["hull"]["verts"]
            vids = []
            for v in V:
                vid = desc.create_vertex(); desc.set_vertex_position(vid, unreal.Vector(*v)); vids.append(vid)
            for f in b["hull"]["faces"]:
                vis = [desc.create_vertex_instance(vids[i]) for i in (f[::-1] if opts.get("CP_FLIP", True) else f)]
                desc.create_triangle(pg, vis)
            sm.build_from_static_mesh_descriptions([desc], False)
            sme.remove_collisions(sm)
            ok = sme.set_convex_decomposition_collisions(sm, 1, 32, 100000)
            meshes[b["name"]] = sm
            L("mesh %s verts=%d faces=%d convex=%s" % (b["name"], len(V), len(b["hull"]["faces"]), ok))
        # bodies: a joint (or free joint) makes a separate simulated body, otherwise weld to the parent
        jointed = {j["child"] for j in J["joints"]}
        actors = {}
        slide_mid = {j["child"]: (j["axis"], 50.0 * (j["range"][0] + j["range"][1])) for j in J["joints"] if j["type"] == "slide" and j["range"]}
        for b in J["bodies"]:
            if b["name"] not in meshes: continue
            w, x, y, z = b["quat"]
            loc = unreal.Vector(b["pos"][0], b["pos"][1], b["pos"][2] + base_z)
            rot = unreal.Quat(x, y, z, w).rotator()
            sl = slide_mid.get(b["name"])
            if sl:   # a slide's limit is symmetric about where the body starts, so start it mid-range; PIE moves it back
                loc = loc + unreal.Vector(*sl[0]) * sl[1]
            a = acs.spawn_actor_from_class(unreal.StaticMeshActor, loc, rot)
            a.set_actor_label("CR_" + b["name"]); a.set_folder_path("ChaosRobot"); a.tags = ["ChaosRobot", b["name"]]
            c = a.static_mesh_component
            c.set_mobility(unreal.ComponentMobility.MOVABLE)
            c.set_static_mesh(meshes[b["name"]])
            c.set_collision_profile_name("PhysicsActor")
            if not opts.get("CP_SELFCOLLIDE", False):   # the robot's parts ignore one another, as RobotSelf does
                c.set_collision_object_type(unreal.CollisionChannel.ECC_VEHICLE)
                c.set_collision_response_to_channel(unreal.CollisionChannel.ECC_VEHICLE, unreal.CollisionResponseType.ECR_IGNORE)
            c.set_mass_override_in_kg("None", max(b["mass"], 1e-4), True)
            actors[b["name"]] = a
        root_of = {}
        for b in J["bodies"]:
            n = b["name"]
            if n not in actors: continue
            if n in jointed or b["free"] or b["parent"] == "world":
                root_of[n] = n
            else:
                p = b["parent"]
                while p in root_of and root_of[p] != p: p = root_of[p]
                root_of[n] = root_of.get(p, p)
        for n, a in actors.items():
            b_ = next(b for b in J["bodies"] if b["name"] == n)
            sim = (n in jointed) or b_["free"]   # a body welded to the world stays put
            if root_of[n] != n:
                a.attach_to_actor(actors[root_of[n]], "None", unreal.AttachmentRule.KEEP_WORLD, unreal.AttachmentRule.KEEP_WORLD, unreal.AttachmentRule.KEEP_WORLD, True)
                a.static_mesh_component.set_simulate_physics(False)
            else:
                a.static_mesh_component.set_simulate_physics(sim)
        L("bodies %d, simulated roots %s" % (len(actors), sorted(n for n in actors if root_of[n] == n)))
        acts = {}
        for ac in J["actuators"]:
            for jn, coef in ac.get("joints", []): acts[jn] = (ac, coef)
        def frame_rot(axis):
            ax = unreal.Vector(*axis); ax = ax.normal()
            return unreal.MathLibrary.make_rot_from_x(ax)
        def constraint(name, parent, child, loc, rot):
            ca = acs.spawn_actor_from_class(unreal.PhysicsConstraintActor, loc, rot)
            ca.set_actor_label("CJ_" + name); ca.set_folder_path("ChaosRobot"); ca.tags = ["ChaosRobotJoint", name]
            cc = ca.constraint_comp
            cc.set_editor_property("constraint_actor1", actors[root_of[parent]]); cc.set_editor_property("constraint_actor2", actors[root_of[child]])
            return ca, cc
        for j in J["joints"]:
            if j["type"] == "slide":   # linear X along the axis, everything else locked; spring and damping as linear drives
                loc = unreal.Vector(j["anchor"][0], j["anchor"][1], j["anchor"][2] + base_z) + unreal.Vector(*j["axis"]) * slide_mid.get(j["child"], (None, 0.0))[1]
                ca, cc = constraint(j["name"], j["parent"], j["child"], loc, frame_rot(j["axis"]))
                half = 50.0 * (j["range"][1] - j["range"][0]) if j["range"] else 0.0
                # the three linear axes share one limit size, so lock Y and Z first and size the limit on X last
                cc.set_linear_y_limit(unreal.LinearConstraintMotion.LCM_LOCKED, 0.0); cc.set_linear_z_limit(unreal.LinearConstraintMotion.LCM_LOCKED, 0.0)
                cc.set_linear_x_limit(unreal.LinearConstraintMotion.LCM_LIMITED if j["range"] else unreal.LinearConstraintMotion.LCM_FREE, half)
                for f in (cc.set_angular_twist_limit, cc.set_angular_swing1_limit, cc.set_angular_swing2_limit):
                    f(unreal.AngularConstraintMotion.ACM_LOCKED, 0.0)
                kp, kv = j.get("stiffness", 0.0), j["damping"]   # N/m and N.s/m are kg/s^2 and kg/s in either unit system
                cc.set_linear_position_drive(kp > 0, False, False); cc.set_linear_velocity_drive(kv > 0, False, False)
                cc.set_linear_drive_params(kp, kv, 0.0)
                ci = cc.get_editor_property("constraint_instance"); prof = ci.get_editor_property("profile_instance")
                ld = prof.get_editor_property("linear_drive"); ld.set_editor_property("acceleration_mode", False)
                prof.set_editor_property("linear_drive", ld); ci.set_editor_property("profile_instance", prof); cc.set_editor_property("constraint_instance", ci)
                L("slide %s parent=%s child=%s range=%s k=%g c=%g" % (j["name"], root_of[j["parent"]], root_of[j["child"]], j["range"], kp, kv))
                continue
            if j["type"] != "hinge": L("skip %s %s" % (j["name"], j["type"])); continue
            loc = unreal.Vector(j["anchor"][0], j["anchor"][1], j["anchor"][2] + base_z)
            ca, cc = constraint(j["name"], j["parent"], j["child"], loc, frame_rot(j["axis"]))
            ci = cc.get_editor_property("constraint_instance")
            prof = ci.get_editor_property("profile_instance")
            mid = 0.0
            if j["range"]:
                lo, hi = j["range"]; mid = 0.5 * (lo + hi); half = math.degrees(0.5 * (hi - lo))
                cc.set_angular_twist_limit(unreal.AngularConstraintMotion.ACM_LIMITED, half)
            else:
                cc.set_angular_twist_limit(unreal.AngularConstraintMotion.ACM_FREE, 0.0)
            cc.set_angular_swing1_limit(unreal.AngularConstraintMotion.ACM_LOCKED, 0.0)
            cc.set_angular_swing2_limit(unreal.AngularConstraintMotion.ACM_LOCKED, 0.0)
            # drives: a joint position servo (kp, kv, force range) or, unactuated, the joint's damping
            kp = kv = fmax = 0.0
            if j["name"] in acts:
                ac, coef = acts[j["name"]]; csum = sum(c for _, c in ac["joints"])
                kp, kv = coef * csum * ac["kp"], coef * csum * ac["kv"]
                fmax = coef * ac["forcerange"][1] if ac["forcerange"] else 0.0
            if kp == 0 and j.get("stiffness", 0.0) > 0: kp = j["stiffness"]
            kv += j["damping"]
            cc.set_angular_drive_mode(unreal.AngularDriveMode.TWIST_AND_SWING)
            cc.set_orientation_drive_twist_and_swing(kp > 0, False)
            cc.set_angular_velocity_drive_twist_and_swing(kv > 0, False)
            cc.set_angular_drive_params(kp * 1e4, kv * 1e4, fmax * 1e4)
            ci = cc.get_editor_property("constraint_instance")
            prof = ci.get_editor_property("profile_instance")
            ad = prof.get_editor_property("angular_drive"); ad.set_editor_property("acceleration_mode", False)
            prof.set_editor_property("angular_drive", ad); ci.set_editor_property("profile_instance", prof)
            if mid: ci.set_editor_property("angular_rotation_offset", unreal.Rotator(roll=float(opts.get("CP_OFFSET_SIGN", 1.0)) * math.degrees(mid), pitch=0.0, yaw=0.0))
            cc.set_editor_property("constraint_instance", ci)
            if mid: cc.set_angular_orientation_target(unreal.Rotator(roll=-float(opts.get("CP_OFFSET_SIGN", 1.0)) * math.degrees(mid), pitch=0.0, yaw=0.0))   # rest at q = 0
            L("  drive kp=%g kv=%g fmax=%g mid=%.3f" % (kp, kv, fmax, mid))
            L("joint %s parent=%s child=%s range=%s" % (j["name"], root_of[j["parent"]], root_of[j["child"]], j["range"]))
        for e in J["equality"]:
            if e["type"] != "connect": continue
            loc = unreal.Vector(e["anchor"][0], e["anchor"][1], e["anchor"][2] + base_z)
            ca, cc = constraint("eq_" + e["body1"], e["body1"], e["body2"], loc, unreal.Rotator())
            for f in (cc.set_angular_twist_limit, cc.set_angular_swing1_limit, cc.set_angular_swing2_limit):
                f(unreal.AngularConstraintMotion.ACM_FREE, 0.0)
            L("connect %s-%s" % (e["body1"], e["body2"]))
        bx = opts.get("CP_BOX")
        if bx:
            a = acs.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(bx["pos_ue"][0], bx["pos_ue"][1], bx["pos_ue"][2] + base_z), unreal.Rotator())
            a.set_actor_label("CR_box"); a.set_folder_path("ChaosRobot"); a.tags = ["ChaosRobotBox", "box"]
            c = a.static_mesh_component; c.set_mobility(unreal.ComponentMobility.MOVABLE)
            c.set_static_mesh(unreal.load_asset("/Engine/BasicShapes/Cube"))
            a.set_actor_scale3d(unreal.Vector(*[h * 2 / 100.0 for h in bx["half_cm"]]))
            c.set_collision_profile_name("PhysicsActor"); c.set_simulate_physics(True)
            c.set_mass_override_in_kg("None", bx["mass"], True)
            L("box %s" % bx)
        w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        w.get_world_settings().set_editor_property("default_game_mode", unreal.GameModeBase)
        for a in acs.get_all_level_actors():
            if isinstance(a, unreal.PlayerStart): a.set_actor_location(unreal.Vector(-600, 0, 100), False, False)
        cam_at = unreal.Vector(0, 0, 60 + base_z); cam_loc = unreal.Vector(130, -170, 110 + base_z)
        cam = acs.spawn_actor_from_class(unreal.CameraActor, cam_loc, unreal.MathLibrary.find_look_at_rotation(cam_loc, cam_at))
        cam.set_actor_label("CR_Camera"); cam.set_folder_path("ChaosRobot"); cam.tags = ["ChaosRobotCam"]
        cam.set_editor_property("auto_activate_for_player", unreal.AutoReceiveInput.PLAYER0)
        cam.camera_component.set_editor_property("field_of_view", 60.0)
        les.save_current_level()
        L("saved %s" % lvl)
    except Exception:
        import traceback; L("ERROR " + traceback.format_exc())
_build(_CP_OPTS); del _build, _CP_OPTS
