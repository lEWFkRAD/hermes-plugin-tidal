"""TIDAL plugin for Hermes Agent.

Five tools (playback/search/playlists/library/mixes) plus `hermes tidal login`.
Wiring goes only through the public plugin API (ctx.register_tool /
ctx.register_cli_command).
"""

from __future__ import annotations

from .tidal_cli import handle_cli, setup_cli
from .tidal_tools import TOOLS, _check_tidal_available

TOOLSET = "tidal"


def register(ctx) -> None:
    for name, schema, handler, emoji in TOOLS:
        ctx.register_tool(name=name, toolset=TOOLSET, schema=schema, handler=handler,
                          check_fn=_check_tidal_available, emoji=emoji)
    ctx.register_cli_command(
        name="tidal", help="Log in to TIDAL and check the plugin's auth status",
        description="TIDAL login for the tidal plugin (interactive PKCE paste-back flow; needs a TIDAL subscription).",
        setup_fn=setup_cli, handler_fn=handle_cli)


__all__ = ["register"]
