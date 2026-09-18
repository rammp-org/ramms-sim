"""Project Python bootstrap — runs automatically at editor startup.

Registers the RAMMS MCP toolset so the in-editor Model Context Protocol server
exposes this project's own tools (PIE control, control surfaces, physics
backends) alongside Epic's stock ones. See the README's MCP Server section.

Failures here are logged and swallowed: a toolset that cannot register must not
stop the editor from opening.
"""

import unreal

TAG = "[RAMMS toolset] "


def _register():
    try:
        import ramms_toolset
    except Exception as exc:  # ToolsetRegistry plugin absent, syntax error, ...
        unreal.log_warning(TAG + "not registered: %s" % exc)
        return

    try:
        if ramms_toolset.register():
            unreal.log(TAG + "registered RammsToolset with the toolset registry.")
        else:
            # Expected in -game / commandlet runs, where the registry is absent.
            unreal.log(TAG + "toolset registry unavailable; skipped registration.")
    except Exception as exc:
        unreal.log_warning(TAG + "registration failed: %s" % exc)


_register()
