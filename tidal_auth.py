"""Profile-local TIDAL authentication using interactive PKCE paste-back login."""
from __future__ import annotations
import os
import sys
from hermes_constants import get_hermes_home

def _session_dir():
    return get_hermes_home() / "plugin-data" / "tidal"


def _session_file():
    return _session_dir() / "session.json"


def _new_session():
    import tidalapi
    return tidalapi.Session()


def _save_session(session):
    _session_dir().mkdir(parents=True, exist_ok=True)
    # Protect the file before tidalapi writes tokens, including an existing file.
    fd = os.open(_session_file(), os.O_WRONLY | os.O_CREAT, 0o600)
    os.close(fd)
    os.chmod(_session_file(), 0o600)
    session.save_session_to_file(_session_file())
    os.chmod(_session_file(), 0o600)


def load_session():
    """Return a logged-in tidalapi.Session or None (never raises)."""
    if not _session_file().is_file():
        return None
    try:
        # login_session_file may refresh and persist tokens.
        os.chmod(_session_file(), 0o600)
        s = _new_session()
        if s.login_session_file(_session_file()):
            os.chmod(_session_file(), 0o600)
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
        return {"logged_in": True, "user": name, "session_file": str(_session_file())}
    except Exception:
        return {"logged_in": True, "user": "?", "session_file": str(_session_file())}


def device_login(printer=print) -> bool:
    """Open a PKCE URL and paste the redirect back into the interactive CLI."""
    if not sys.stdin or not sys.stdin.isatty():
        printer("Run 'hermes tidal login' in an interactive terminal to paste the redirect URL.")
        return False
    s = _new_session()
    try:
        url = s.pkce_login_url()
        printer("TIDAL login - open this URL and log in with your TIDAL account:")
        printer(f"  {url}")
        printer("On the 'Oops' page, copy the URL from the address bar and paste it here.")
        redirect = input("Paste 'Oops' page URL here and press <ENTER>: ").strip()
        if not redirect:
            printer("No redirect URL provided; login aborted.")
            return False
        token = s.pkce_get_auth_token(redirect)
        s.process_auth_token(token, is_pkce_token=True)
        _save_session(s)
        printer(f"Logged in. Session saved to {_session_file()}")
        return True
    except (EOFError, KeyboardInterrupt):
        printer("Login aborted.")
        return False
    except Exception as e:
        printer(f"TIDAL login failed: {type(e).__name__}")
        return False


def logout() -> None:
    _session_file().unlink(missing_ok=True)
    # Remove any pending state left by an older version in this profile.
    (_session_dir() / "pending.json").unlink(missing_ok=True)
