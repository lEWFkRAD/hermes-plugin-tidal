<!-- project-home:start -->
![hermes-plugin-tidal project banner](https://raw.githubusercontent.com/lEWFkRAD/hermes-plugin-tidal/85c864a5ff45d69cdea6d54d24c010080cc17a40/docs/banner.jpg)

**[TIDAL for Hermes project homepage](https://lewfkrad.github.io/hermes-plugin-tidal/)** · [Documentation](https://github.com/lEWFkRAD/hermes-plugin-tidal#login)

Search your TIDAL library, organize playlists, and control local music playback through Hermes.

<!-- project-home:end -->

# TIDAL for Hermes Agent

A Hermes plugin that gives the agent five TIDAL tools — playback, search,
playlists, library, and mixes — over the unofficial TIDAL API via
[tidalapi](https://github.com/tidal-api/tidalapi).

## Tools

| Tool | What it does |
|---|---|
| `tidal_playback` | Play TIDAL music through this machine's speakers (mpv) and control it (play/pause/stop/volume/seek/status) |
| `tidal_search` | Search tracks, albums, artists, and playlists |
| `tidal_playlists` | List, inspect, create, and add to your playlists |
| `tidal_library` | Your favorites and saved albums/tracks |
| `tidal_mixes` | Your TIDAL mixes and radio |

Playback runs on the machine Hermes runs on, through a local `mpv` process —
TIDAL has no remote-device API like Spotify Connect, so there is no way to
play on a phone or speaker from here.

## Requirements

- Hermes Agent >= 0.21.6
- A TIDAL subscription (any tier)
- `mpv` installed on the machine (playback only; search/library tools work without it)
- Linux or macOS for playback (the player talks to mpv over a Unix socket)
- Python dependency: `tidalapi>=0.8.11,<0.9` (declared in `pyproject.toml`)

## Login

Login is TIDAL's own PKCE flow — no developer app or API key needed:

```
hermes tidal login
```

The command prints a TIDAL login URL. Open it, log in with your TIDAL
account, and when the browser lands on an "Oops" page, copy that page's
URL from the address bar and paste it back to finish the login. The
session is saved to `<Hermes profile home>/plugin-data/tidal/session.json` (tidalapi's own
session file format).

Check state or log out with:

```
hermes tidal status
hermes tidal logout
```

Tools stay hidden until a login exists: the toolset's availability check
only passes when a saved session is present.

## Quality

The plugin manifest declares one config option, `quality`
(`low | high | lossless | hi_res`, default `high`) — the ceiling for
streamed audio. `lossless` / `hi_res` need a HiFi Plus tier and enough
bandwidth.

## Notes

- This is an unofficial integration built on the community `tidalapi`
  library; it is not affiliated with or endorsed by TIDAL.
- Author: lewfkrad (built by Hermes on the author's laptop).

Login requires an interactive terminal and keeps PKCE state in memory.
Session files have owner-only POSIX permissions; Windows privacy follows the
profile directory ACL. Player state and its socket use the same profile directory.
Older shared sessions are not imported across profiles; log in in each profile.
