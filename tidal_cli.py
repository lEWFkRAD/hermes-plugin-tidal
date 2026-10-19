"""`hermes tidal login|status|logout` CLI subcommand."""

from __future__ import annotations

from .tidal_auth import auth_status, device_login, logout


def setup_cli(parser) -> None:
    parser.add_argument("action", nargs="?", choices=["login", "status", "logout"], default="login")


def handle_cli(args) -> int:
    action = getattr(args, "action", None) or "login"
    if action == "login":
        return 0 if device_login() else 1
    if action == "status":
        import json

        print(json.dumps(auth_status(), indent=2))
        return 0
    if action == "logout":
        logout()
        print("TIDAL session forgotten.")
        return 0
    return 1


__all__ = ["setup_cli", "handle_cli"]
