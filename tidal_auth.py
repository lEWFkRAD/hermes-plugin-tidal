"""TIDAL auth for the tidal plugin.

Session persistence: tidalapi's own session file at ~/.hermes/tidal/session.json.
Login: TIDAL's device flow (pkce_login_url + code shown to the user) run in a
background thread so the CLI never blocks on the browser step.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

SESSION_DIR = Path.home() / ".hermes" / "tidal"
SESSION_FILE = SESSION_DIR / "session.json"


def _new_session():
    import tidalapi

    return tidalapi.Session()


class _NeedInput(Exception):
    """Raised by an agent-driven printer to hand control back for user input."""


def _collect_redirect_url(printer, login_url: str) -> str:
    """Get the 'Oops' redirect URL: interactive stdin, or raise _NeedInput."""
    import sys

    if sys.stdin and sys.stdin.isatty():
        try:
            return input("Paste 'Oops' page URL here and press <ENTER>: ").strip()
        except (EOFError, KeyboardInterrupt):
            return ""
    # Non-interactive (agent-driven): the caller finishes the login via
    # finish_login() once the user pastes the URL.
    raise _NeedInput(login_url)


def finish_login(redirect_url: str) -> dict:
    """Complete a pending PKCE login with the user-pasted redirect URL.

    The pending login state (code_verifier etc.) lives in PENDING_FILE, saved
    by device_login(); tidalapi's Session must be rebuilt with the same config.
    """
    pending = SESSION_DIR / "pending.json"
    if not pending.is_file():
        return {"ok": False, "error": "No pending TIDAL login. Run: hermes tidal login"}
    try:
        data = json.loads(pending.read_text())
        s = _new_session()
        cfg = s.config
        cfg.code_verifier = data["code_verifier"]
        cfg.code_challenge = data["code_challenge"]
        cfg.client_unique_key = data["client_unique_key"]
        token = s.pkce_get_auth_token(redirect_url.strip())
        s.process_auth_token(token, is_pkce_token=True)
        SESSION_DIR.mkdir(parents=True, exist_ok=True)
        s.save_session_to_file(SESSION_FILE)
        pending.unlink(missing_ok=True)
        return {"ok": True, "user": getattr(getattr(s, "user", None), "first_name", None)}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def load_session():
    """Return a logged-in tidalapi.Session or None (never raises)."""
    if not SESSION_FILE.is_file():
        return None
    try:
        s = _new_session()
        if s.login_session_file(SESSION_FILE):
            return s
    except Exception:
        pass
    return None


def auth_status() -> dict:
    s = load_session()
    if s is None:
        return {"logged_in": False}
    try:
        user = s.user
        name = getattr(user, "first_name", None) or getattr(user, "name", None) or "?"
        return {"logged_in": True, "user": name, "session_file": str(SESSION_FILE)}
    except Exception:
        return {"logged_in": True, "user": "?", "session_file": str(SESSION_FILE)}


def device_login(printer=print) -> bool:
    """Run TIDAL's PKCE login: user opens the URL, logs in, and pastes back
    the 'Oops' redirect URL. The URL is handed to the user through `printer`,
    which may raise _NeedInput (agent-driven logins) to collect it.
    """
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    s = _new_session()
    try:
        url = s.pkce_login_url()
    except Exception as e:
        printer(f"TIDAL login could not start: {e}")
        return False

    printer("TIDAL login — open this URL and log in with your TIDAL account:")
    printer(f"  {url}")
    printer("After logging in you'll land on an 'Oops' page: copy that page's URL "
            "from the browser's address bar and paste it back here.")

    # Save the PKCE state so finish_login() can complete out-of-band.
    try:
        (SESSION_DIR / "pending.json").write_text(json.dumps({
            "code_verifier": s.config.code_verifier,
            "code_challenge": s.config.code_challenge,
            "client_unique_key": s.config.client_unique_key,
            "login_url": url,
        }))
    except Exception:
        pass

    try:
        redirect = _collect_redirect_url(printer, url)
    except _NeedInput:
        printer("Waiting for the redirect URL... paste the 'Oops' page URL and I will finish the login.")
        return False

    if not redirect:
        printer("No redirect URL provided; login aborted.")
        return False

    try:
        token = s.pkce_get_auth_token(redirect)
        s.process_auth_token(token, is_pkce_token=True)
        s.save_session_to_file(SESSION_FILE)
        printer(f"Logged in. Session saved to {SESSION_FILE}")
        return True
    except Exception as e:
        printer(f"TIDAL login failed: {e}")
        return False


def logout() -> None:
    try:
        SESSION_FILE.unlink(missing_ok=True)
    except Exception:
        pass
