# PIE tests

Python-driven play-in-editor tests. Each subfolder is one scenario: a level builder that runs
inside the editor, and (for the driven ones) a host script that talks to the running editor
through `Scripts/editor_remote_exec.py`.

## `common.py`: shared helpers

One stdlib-only module for the pattern those tests share: the host sets `unreal.<var>` to an
op string and execs an op file in the editor; the op file takes the string, does its work and
prints one `<TAG> <json>` line; the host parses the last such line.

- Host: `remote`, `make_op`, `remote_code` (a long job past the client's 120 s), `next_path`
  and `latest` (numbered, never-overwritten recordings).
- Editor: `take_op`, `out`, `xf_row` (the same transform row as `Scripts/record_transforms.py`),
  `mesh_info`, `scene_of`, `unhook`. `unreal` is imported inside these, so the host can import
  the module too.

`remote()` puts `Scripts/pie_tests` on the editor's `sys.path`, so an op file starts with
`import common`. The module docstring has the full example. New tests should use it rather
than carry their own copy.
