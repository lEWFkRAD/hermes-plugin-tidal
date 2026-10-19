"""TIDAL tools for Hermes (registered by this plugin's ``register(ctx)``).

Five tools, each routing ``args["action"]`` through a dispatch table. All TIDAL
access goes through tidalapi; playback is local (mpv) because TIDAL has no
remote-device API.
"""

from __future__ import annotations

from typing import Any, Callable

from tools.registry import tool_error, tool_result

from . import tidal_player
from .tidal_auth import auth_status, load_session

_Handler = Callable[[Any, dict], str]


def _check_tidal_available() -> bool:
    try:
        return bool(auth_status().get("logged_in"))
    except Exception:
        return False


class TidalToolError(Exception):
    pass


def _session() -> Any:
    s = load_session()
    if s is None:
        raise TidalToolError("Not logged in to TIDAL. Run: hermes tidal login")
    return s


def _nonblank(raw: Any, message: str) -> str:
    value = str(raw or "").strip()
    if not value:
        raise TidalToolError(message)
    return value


def _int(raw: Any, default: int) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _track_line(t: Any) -> dict:
    try:
        return {
            "id": t.id,
            "title": t.name,
            "artist": getattr(t.artist, "name", None) or ", ".join(
                a.name for a in getattr(t, "artists", []) if getattr(a, "name", None)),
            "album": getattr(getattr(t, "album", None), "name", None),
            "duration_s": getattr(t, "duration", None),
        }
    except Exception:
        return {"id": getattr(t, "id", None), "title": getattr(t, "name", "?")}


def _stream_url(session: Any, track_id: int) -> tuple[str, str]:
    track = session.track(track_id)
    stream = track.get_stream()
    manifest = stream.get_stream_manifest()
    urls = manifest.get_urls()
    if not urls:
        raise TidalToolError(f"No playable stream URL for track {track_id}")
    return urls[0], track.name


# ---------------------------------------------------------------- playback --

def _h_state(session: Any, args: dict) -> str:
    return tool_result(tidal_player.get_state())


def _h_play(session: Any, args: dict) -> str:
    if args.get("track_id") is not None:
        url, title = _stream_url(session, _int(args["track_id"], 0))
    elif args.get("playlist_id"):
        pl = session.playlist(_nonblank(args["playlist_id"], "playlist_id required"))
        tracks = pl.tracks or []
        if not tracks:
            raise TidalToolError("Playlist is empty")
        idx = max(0, min(_int(args.get("index", 0), 0), len(tracks) - 1))
        url, title = _stream_url(session, tracks[idx].id)
    elif args.get("album_id"):
        al = session.album(_nonblank(args["album_id"], "album_id required"))
        tracks = al.items or []
        if not tracks:
            raise TidalToolError("Album has no tracks")
        idx = max(0, min(_int(args.get("index", 0), 0), len(tracks) - 1))
        url, title = _stream_url(session, tracks[idx].id)
    else:
        raise TidalToolError("play needs one of: track_id, playlist_id, album_id")
    state = tidal_player.play_url(url, title=title)
    return tool_result({"playing": True, "title": state["title"]})


def _h_pause(session: Any, args: dict) -> str:
    tidal_player.pause()
    return tool_result({"paused": True})


def _h_resume(session: Any, args: dict) -> str:
    tidal_player.resume()
    return tool_result({"playing": True})


def _h_stop(session: Any, args: dict) -> str:
    tidal_player.stop()
    return tool_result({"stopped": True})


def _h_volume(session: Any, args: dict) -> str:
    tidal_player.set_volume(_int(args.get("volume_percent", 70), 70))
    return tool_result(tidal_player.get_state())


def _h_seek(session: Any, args: dict) -> str:
    tidal_player.seek(float(args.get("position_s", 0) or 0))
    return tool_result(tidal_player.get_state())


PLAYBACK_ACTIONS = {
    "get_state": _h_state, "play": _h_play, "pause": _h_pause,
    "resume": _h_resume, "stop": _h_stop, "set_volume": _h_volume, "seek": _h_seek,
}


def _handle_tidal_playback(args: dict, **kw) -> str:
    action = str(args.get("action") or "")
    handler = PLAYBACK_ACTIONS.get(action)
    if handler is None:
        return tool_error(f"Unknown action {action!r}; choose from: {', '.join(PLAYBACK_ACTIONS)}")
    try:
        return handler(_session(), args)
    except tidal_player.PlayerError as e:
        return tool_error(str(e))
    except TidalToolError as e:
        return tool_error(str(e))
    except Exception as e:
        return tool_error(f"TIDAL playback tool failed: {type(e).__name__}: {e}")


# ------------------------------------------------------------------ search --

def _h_search(session: Any, args: dict) -> str:
    query = _nonblank(args.get("query"), "query required")
    kind = str(args.get("type") or "track").lower()
    limit = max(1, min(_int(args.get("limit", 10), 10), 50))
    models = {"track": "track", "album": "album", "artist": "artist", "playlist": "playlist"}
    if kind not in models:
        raise TidalToolError(f"type must be one of: {', '.join(models)}")
    results = session.search(query, models=[models[kind]], limit=limit)
    out: list[dict] = []
    if kind == "track":
        out = [_track_line(t) for t in (results.track or [])]
    elif kind == "album":
        for a in (results.album or []):
            out.append({"id": a.id, "name": a.name, "artist": getattr(a.artist, "name", None)})
    elif kind == "artist":
        for a in (results.artist or []):
            out.append({"id": a.id, "name": a.name})
    else:
        for p in (results.playlist or []):
            out.append({"id": p.id, "name": p.name,
                        "owner": getattr(getattr(p, "user", None), "name", None)})
    return tool_result({"query": query, "type": kind, "results": out})


def _handle_tidal_search(args: dict, **kw) -> str:
    try:
        return _h_search(_session(), args)
    except TidalToolError as e:
        return tool_error(str(e))
    except Exception as e:
        return tool_error(f"TIDAL search failed: {type(e).__name__}: {e}")


# --------------------------------------------------------------- playlists --

def _h_my_playlists(session: Any, args: dict) -> str:
    user = session.get_user()
    pls = user.playlists() if callable(getattr(user, "playlists", None)) else getattr(user, "playlists", [])
    return tool_result({"playlists": [
        {"id": p.id, "name": p.name, "tracks": getattr(p, "num_tracks", None)} for p in pls]})


def _h_playlist_tracks(session: Any, args: dict) -> str:
    pl = session.playlist(_nonblank(args.get("playlist_id"), "playlist_id required"))
    return tool_result({"name": pl.name, "tracks": [_track_line(t) for t in (pl.tracks or [])]})


def _h_playlist_add(session: Any, args: dict) -> str:
    pl = session.playlist(_nonblank(args.get("playlist_id"), "playlist_id required"))
    pl.add(_int(args.get("track_id", 0), 0))
    return tool_result({"added": args.get("track_id")})


def _h_playlist_create(session: Any, args: dict) -> str:
    user = session.get_user()
    title = _nonblank(args.get("title"), "title required")
    artist = getattr(getattr(user, "artist", None), "name", None) or ""
    pl = user.create_playlist(title, artist)
    return tool_result({"id": pl.id, "name": title})


PLAYLIST_ACTIONS = {
    "list": _h_my_playlists, "tracks": _h_playlist_tracks,
    "add_track": _h_playlist_add, "create": _h_playlist_create,
}


def _handle_tidal_playlists(args: dict, **kw) -> str:
    action = str(args.get("action") or "")
    handler = PLAYLIST_ACTIONS.get(action)
    if handler is None:
        return tool_error(f"Unknown action {action!r}; choose from: {', '.join(PLAYLIST_ACTIONS)}")
    try:
        return handler(_session(), args)
    except TidalToolError as e:
        return tool_error(str(e))
    except Exception as e:
        return tool_error(f"TIDAL playlists tool failed: {type(e).__name__}: {e}")


# ----------------------------------------------------------------- library --

def _h_favorites_tracks(session: Any, args: dict) -> str:
    limit = max(1, min(_int(args.get("limit", 25), 25), 100))
    favs = session.user.favorites.tracks(limit=limit)
    return tool_result({"tracks": [_track_line(t) for t in favs]})


def _h_favorites_add(session: Any, args: dict) -> str:
    session.user.favorites.add_track(_int(args.get("track_id", 0), 0))
    return tool_result({"favorited": args.get("track_id")})


def _h_favorites_remove(session: Any, args: dict) -> str:
    session.user.favorites.remove_track(_int(args.get("track_id", 0), 0))
    return tool_result({"unfavorited": args.get("track_id")})


LIBRARY_ACTIONS = {
    "favorite_tracks": _h_favorites_tracks, "add_favorite": _h_favorites_add,
    "remove_favorite": _h_favorites_remove,
}


def _handle_tidal_library(args: dict, **kw) -> str:
    action = str(args.get("action") or "")
    handler = LIBRARY_ACTIONS.get(action)
    if handler is None:
        return tool_error(f"Unknown action {action!r}; choose from: {', '.join(LIBRARY_ACTIONS)}")
    try:
        return handler(_session(), args)
    except TidalToolError as e:
        return tool_error(str(e))
    except Exception as e:
        return tool_error(f"TIDAL library tool failed: {type(e).__name__}: {e}")


# ------------------------------------------------------------------- mixes --

def _h_mixes_list(session: Any, args: dict) -> str:
    page = session.mixes()
    return tool_result({"mixes": [
        {"id": m.id, "title": m.title, "sub_title": getattr(m, "sub_title", None)}
        for m in (page.items() if callable(getattr(page, "items", None)) else page)]})


def _h_mixes_tracks(session: Any, args: dict) -> str:
    mix = session.mix(_nonblank(args.get("mix_id"), "mix_id required"))
    items = mix.items() if callable(getattr(mix, "items", None)) else mix.items
    return tool_result({"title": mix.title, "tracks": [_track_line(t) for t in items]})


MIX_ACTIONS = {"list": _h_mixes_list, "tracks": _h_mixes_tracks}


def _handle_tidal_mixes(args: dict, **kw) -> str:
    action = str(args.get("action") or "")
    handler = MIX_ACTIONS.get(action)
    if handler is None:
        return tool_error(f"Unknown action {action!r}; choose from: {', '.join(MIX_ACTIONS)}")
    try:
        return handler(_session(), args)
    except TidalToolError as e:
        return tool_error(str(e))
    except Exception as e:
        return tool_error(f"TIDAL mixes tool failed: {type(e).__name__}: {e}")


# ----------------------------------------------------------------- schemas --

def _schema(name: str, desc: str, props: dict) -> dict:
    return {"name": name, "description": desc,
            "input_schema": {"type": "object", "properties": props, "required": ["action"]}}


_STR = {"type": "string"}
_INT_P = {"type": "integer"}

TIDAL_PLAYBACK_SCHEMA = _schema(
    "tidal_playback",
    "Play TIDAL music through this machine's speakers (mpv) and control it. "
    "play needs track_id, playlist_id, or album_id. TIDAL has no remote devices — "
    "audio always comes out of the Hermes host machine.",
    {
        "action": {"type": "string", "enum": list(PLAYBACK_ACTIONS)},
        "track_id": _INT_P, "playlist_id": _STR, "album_id": _STR,
        "index": {"description": "Which track of the playlist/album to start at (0-based)", **_INT_P},
        "volume_percent": _INT_P, "position_s": {"description": "Seek position in seconds", "type": "number"},
    })

TIDAL_SEARCH_SCHEMA = _schema(
    "tidal_search", "Search the TIDAL catalog for tracks, albums, artists or playlists.",
    {"action": {"type": "string", "enum": ["search"]}, "query": _STR,
     "type": {"type": "string", "enum": ["track", "album", "artist", "playlist"], "default": "track"},
     "limit": _INT_P})

TIDAL_PLAYLISTS_SCHEMA = _schema(
    "tidal_playlists", "List your TIDAL playlists, show a playlist's tracks, add a track, or create one.",
    {"action": {"type": "string", "enum": list(PLAYLIST_ACTIONS)},
     "playlist_id": _STR, "track_id": _INT_P, "title": _STR})

TIDAL_LIBRARY_SCHEMA = _schema(
    "tidal_library", "Your TIDAL favorites: list favorited tracks, add or remove a favorite.",
    {"action": {"type": "string", "enum": list(LIBRARY_ACTIONS)}, "track_id": _INT_P, "limit": _INT_P})

TIDAL_MIXES_SCHEMA = _schema(
    "tidal_mixes", "TIDAL's personal mixes (Daily Discovery, Creator Mixes...): list them or show a mix's tracks.",
    {"action": {"type": "string", "enum": list(MIX_ACTIONS)}, "mix_id": _STR})


TOOLS = (
    ("tidal_playback", TIDAL_PLAYBACK_SCHEMA, _handle_tidal_playback, "🎵"),
    ("tidal_search", TIDAL_SEARCH_SCHEMA, _handle_tidal_search, "🔎"),
    ("tidal_playlists", TIDAL_PLAYLISTS_SCHEMA, _handle_tidal_playlists, "📚"),
    ("tidal_library", TIDAL_LIBRARY_SCHEMA, _handle_tidal_library, "❤️"),
    ("tidal_mixes", TIDAL_MIXES_SCHEMA, _handle_tidal_mixes, "🌀"),
)

__all__ = ["TOOLS", "_check_tidal_available"]
