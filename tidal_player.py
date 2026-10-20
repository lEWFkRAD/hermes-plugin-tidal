"""Local playback of TIDAL streams through mpv, with a tiny JSON state file.

TIDAL has no remote-device API (unlike Spotify Connect), so the plugin plays
through this machine: mpv is spawned detached with a --input-ipc-unix socket;
transport commands go over that socket as JSON lines.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import time
from hermes_constants import get_hermes_home

def _state_dir():
    return get_hermes_home() / "plugin-data" / "tidal"


def _state_file():
    return _state_dir() / "player.json"


def _sock_path():
    return _state_dir() / "mpv.sock"


class PlayerError(Exception):
    pass


def _mpv_bin() -> str:
    path = shutil.which("mpv")
    if not path:
        raise PlayerError("mpv is not installed on this machine")
    return path


def _read_state() -> dict:
    try:
        return json.loads(_state_file().read_text())
    except Exception:
        return {}


def _write_state(state: dict) -> None:
    _state_dir().mkdir(parents=True, exist_ok=True)
    tmp = _state_file().with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.replace(_state_file())


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return pid != 0 and os.path.exists(f"/proc/{pid}")
    except Exception:
        return False


def _mpv_socket(command: str | dict, timeout: float = 2.0):
    """Send one mpv IPC command and return the reply's 'data' (or None)."""
    state = _read_state()
    sock_path = state.get("socket") or str(_sock_path())
    payload = command if isinstance(command, str) else json.dumps([command])
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(sock_path)
            s.sendall((payload.rstrip("\n") + "\n").encode())
            # mpv may send async replies first; read until we get an error field or EOF-ish
            buf = b""
            deadline = time.time() + timeout
            while time.time() < deadline:
                try:
                    chunk = s.recv(65536)
                except socket.timeout:
                    break
                if not chunk:
                    break
                buf += chunk
                for line in buf.split(b"\n"):
                    if not line.strip():
                        continue
                    try:
                        reply = json.loads(line)
                    except Exception:
                        continue
                    if "error" in reply:
                        return reply.get("data")
                if b'"error"' in buf:
                    break
    except (FileNotFoundError, ConnectionRefusedError, OSError):
        raise PlayerError("player is not running")
    # parse last JSON line with an error field
    for line in reversed(buf.split(b"\n")):
        try:
            reply = json.loads(line)
        except Exception:
            continue
        if "error" in reply:
            return reply.get("data")
    return None


def play_url(url: str, title: str = "", quality: str = "") -> dict:
    """Start (or replace) playback of a direct stream URL in mpv."""
    stop()
    _state_dir().mkdir(parents=True, exist_ok=True)
    try:
        _sock_path().unlink(missing_ok=True)
    except Exception:
        pass
    args = [
        _mpv_bin(),
        "--input-ipc-server=" + str(_sock_path()),
        "--no-video",
        "--really-quiet",
        "--volume=70",
    ]
    if quality == "hi_res":
        args += ["--audio-display=no"]
    args.extend(["--", url])
    proc = subprocess.Popen(
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    # wait for the socket to appear (mpv creates it on startup)
    for _ in range(30):
        if _sock_path().exists():
            break
        time.sleep(0.1)
    state = {"pid": proc.pid, "socket": str(_sock_path()), "title": title, "url": url, "started": time.time()}
    _write_state(state)
    return state


def pause() -> None:
    _mpv_socket({"command": ["set_property", "pause", True]})


def resume() -> None:
    _mpv_socket({"command": ["set_property", "pause", False]})


def stop() -> None:
    state = _read_state()
    pid = state.get("pid")
    if pid:
        try:
            _mpv_socket({"command": ["quit"]})
        except Exception:
            pass
        time.sleep(0.2)
        if _pid_alive(int(pid)):
            try:
                os.killpg(os.getpgid(int(pid)), signal.SIGTERM)
            except Exception:
                try:
                    os.kill(int(pid), signal.SIGTERM)
                except Exception:
                    pass
    _write_state({})


def get_state() -> dict:
    state = _read_state()
    if not state.get("pid"):
        return {"playing": False}
    if not _pid_alive(int(state["pid"])):
        _write_state({})
        return {"playing": False}
    try:
        paused = _mpv_socket({"command": ["get_property", "pause"]})
        pos = _mpv_socket({"command": ["get_property", "time-pos"]})
        dur = _mpv_socket({"command": ["get_property", "duration"]})
        vol = _mpv_socket({"command": ["get_property", "volume"]})
    except PlayerError:
        return {"playing": False}
    return {
        "playing": paused is not True,
        "paused": bool(paused),
        "position_s": pos,
        "duration_s": dur,
        "volume": vol,
        "title": state.get("title", ""),
    }


def set_volume(percent: int) -> None:
    _mpv_socket({"command": ["set_property", "volume", max(0, min(130, int(percent)))]})


def seek(seconds: float) -> None:
    _mpv_socket({"command": ["set_property", "time", float(seconds)]})
