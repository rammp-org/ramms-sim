"""Shared helpers for Python-driven PIE tests. Stdlib only; importable from the host and from inside the editor.

The op pattern. A PIE test is driven from a host Python process, one operation per call:

  1. The host runs Scripts/editor_remote_exec.py with --code that sets `unreal.<var> = "<op string>"` and then execs the
     op file inside the running editor.
  2. The op file takes the string with take_op(var) (which clears it, so an op never runs twice), does its work and prints
     one reply line with out(TAG, {...}), i.e. `<TAG> <json>`.
  3. The host parses the LAST line containing `<TAG> ` and returns its JSON. No line means the editor is closed or the op
     crashed, and remote() raises RuntimeError with the tail of the output.

Host side:

    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))        # Scripts/pie_tests
    import common
    op = common.make_op(Path(__file__).with_name("my_op.py"), "_my_op", "MYTAG")
    print(op("status"))

Editor side. remote() prefixes the --code with `sys.path.insert(0, <Scripts/pie_tests>)`, so an op file just does:

    import common
    args = common.take_op("_my_op")          # ["status"], ["goto", "3", ...]
    common.out("MYTAG", {"ok": True})

The editor-side functions import `unreal` inside themselves, so the host can import this module without it.

Also here: remote_code() for a long job (the stock client gives a command 120 s), and next_path() / latest() for numbered,
never-overwritten files such as recordings.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

PIE_TESTS = Path(__file__).resolve().parent
SCRIPTS = PIE_TESTS.parent


def exec_script():
    """Scripts/editor_remote_exec.py, found relative to this module."""
    return SCRIPTS / "editor_remote_exec.py"


def _prefix():
    return "import sys; sys.path.insert(0, r'%s'); " % PIE_TESTS


# ---------- host side ----------

def remote(op_file, var, op, tag, exec_path=None, timeout=None):
    """Run `op_file` in the editor with unreal.<var> = `op` (a string); return the parsed JSON the op printed after
    "<tag> " (the last such line). `timeout` is seconds for the subprocess (None = no limit, but the client itself gives
    up after 120 s; use remote_code for a long job). Raises RuntimeError when no reply line appears."""
    code = _prefix() + "import unreal; unreal.%s = %r; exec(open(r'%s', encoding='utf-8').read())" % (var, op, op_file)
    r = subprocess.run([sys.executable, "-I", str(exec_path or exec_script()), "--code", code],
                       capture_output=True, text=True, timeout=timeout)
    lines = [l.split(tag + " ", 1)[1] for l in (r.stdout + r.stderr).splitlines() if (tag + " ") in l]
    if not lines:
        raise RuntimeError("%s %s: no reply\n%s%s" % (tag, op, r.stdout[-2500:], r.stderr[-2500:]))
    return json.loads(lines[-1])


def make_op(op_file, var, tag, exec_path=None):
    """A one-argument function op(cmd) bound to one op file: `op = make_op(OP, "_my_op", "MYTAG")`, then op("status")."""
    return lambda cmd: remote(op_file, var, cmd, tag, exec_path)


def remote_code(code, tag, exec_path=None, timeout=1800):
    """Run arbitrary editor code and return the last output line containing `tag` (raw text, not parsed). The stock client
    gives a command 120 s; this runs the same client with that one constant (COMMAND_TIMEOUT_S) lifted to `timeout`
    seconds. Raises RuntimeError when no line contains `tag`."""
    exec_path = exec_path or exec_script()
    shim = ("import sys; sys.argv = ['editor_remote_exec.py', '--code', sys.argv[1]]; "
            "src = open(r'%s', encoding='utf-8').read().replace('COMMAND_TIMEOUT_S = 120.0', 'COMMAND_TIMEOUT_S = %d.0'); "
            "exec(compile(src, r'%s', 'exec'), {'__name__': '__main__'})" % (exec_path, timeout, exec_path))
    r = subprocess.run([sys.executable, "-I", "-c", shim, _prefix() + code], capture_output=True, text=True,
                       timeout=timeout + 60)
    text = r.stdout + r.stderr
    hit = [l for l in text.splitlines() if tag in l]
    if not hit:
        raise RuntimeError("%s: no reply\n%s" % (tag, text[-3000:]))
    return hit[-1]


def next_path(directory, name, ext="json"):
    """directory/"<name> vN.<ext>" with N one past the highest existing, so a recording is never overwritten.
    Creates `directory`."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    pat = re.compile(re.escape(name) + r" v(\d+)\." + re.escape(ext) + "$")
    n = max([int(m.group(1)) for p in directory.iterdir() if (m := pat.match(p.name))] + [0])
    return directory / ("%s v%d.%s" % (name, n + 1, ext))


def latest(directory, name, ext="json"):
    """The newest "<name> vN.<ext>" in `directory` (highest N), or None."""
    pat = re.compile(re.escape(name) + r" v(\d+)\." + re.escape(ext) + "$")
    found = [(int(m.group(1)), p) for p in Path(directory).glob("*." + ext) if (m := pat.match(p.name))]
    return max(found)[1] if found else None


# ---------- editor side ----------

def take_op(var, maxsplit=None):
    """The op string the host left in unreal.<var> (cleared on read), split into words; "status" if none. maxsplit=1
    keeps the rest of the line whole (a path after `begin`)."""
    import unreal
    op = getattr(unreal, var, "status")
    if hasattr(unreal, var):
        delattr(unreal, var)
    return op.split(None, maxsplit) if maxsplit else op.split()


def out(tag, d):
    """Print the reply line the host parses: `<TAG> <json>`."""
    print(tag + " " + json.dumps(d))


def xf_row(xf):
    """[tx ty tz qx qy qz qw sx sy sz] of a Transform (or of a scene component, via its world transform): centimetres,
    quaternion x y z w, Unreal world space, rounded for a compact recording. The row format is identical to
    Scripts/record_transforms.py's."""
    if hasattr(xf, "get_world_transform"):
        xf = xf.get_world_transform()
    t, q, s = xf.translation, xf.rotation, xf.scale3d
    return [round(t.x, 3), round(t.y, 3), round(t.z, 3),
            round(q.x, 6), round(q.y, 6), round(q.z, 6), round(q.w, 6),
            round(s.x, 4), round(s.y, 4), round(s.z, 4)]


def asset_path(obj):
    """Asset path string of an unreal object, or None."""
    return obj.get_path_name() if obj is not None else None


def mesh_info(comp):
    """{"name", "class", "mesh" (asset path or None), "materials" (asset paths)} of a mesh component."""
    import unreal
    mesh = comp.static_mesh if isinstance(comp, unreal.StaticMeshComponent) else None
    mats = [asset_path(comp.get_material(i)) for i in range(comp.get_num_materials())]
    return {"name": comp.get_name(), "class": comp.get_class().get_name(),
            "mesh": asset_path(mesh), "materials": mats}


def scene_of(world, skip_actor=None):
    """Every visible static mesh in the level except those of `skip_actor`, with its transform, so a recording can be
    played back against the same set the sim ran in."""
    import unreal
    scene = []
    for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor):
        if a == skip_actor:
            continue
        for c in a.get_components_by_class(unreal.StaticMeshComponent):
            if c.is_visible() and c.static_mesh is not None:
                info = mesh_info(c)
                info["actor"] = a.get_actor_label() if hasattr(a, "get_actor_label") else a.get_name()
                info["xf"] = xf_row(c.get_world_transform())
                scene.append(info)
    return scene


def unhook(handle_var):
    """Unregister the slate tick callback stored in unreal.<handle_var> and clear it."""
    import unreal
    old = getattr(unreal, handle_var, None)
    if old is not None:
        unreal.unregister_slate_post_tick_callback(old)
    setattr(unreal, handle_var, None)
