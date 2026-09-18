"""RAMMS MCP toolset — the project's test surface, exposed to AI assistants.

Registered at editor startup by Content/Python/init_unreal.py and reachable
through the in-editor MCP server (see the README's MCP Server section).

To iterate without restarting the editor:

    import toolset_registry, ramms_toolset
    toolset_registry.reload_module(ramms_toolset)

which unregisters the toolset, reloads every submodule, and registers it again.
"""

from .toolset import RammsToolset

__all__ = ["RammsToolset", "register", "unregister"]

_registration = None


def _make_registration():
    from toolset_registry.registration import Registration

    return Registration([RammsToolset])


def register() -> bool:
    """Register the toolset with the running editor. Idempotent."""
    global _registration
    if _registration is None:
        _registration = _make_registration()
    return _registration.register()


def unregister() -> None:
    """Remove the toolset from the registry."""
    global _registration
    if _registration is not None:
        _registration.unregister()
        _registration = None
