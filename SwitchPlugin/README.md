# Galaxy Nintendo Switch Integration 0.4.0

GOG Galaxy 2.1+ integration for a local Nintendo Switch library, launched through an emulator (Eden by default; yuzu, suyu and Ryujinx work too). By Notimagination.

## Features
- `.nsp`, `.xci`, `.nsz` and `.xcz` files; subfolders are scanned. More extensions: `[Detection] extensions` in `config.ini`.
- Title ID detection, in this order:
  1. a 16-digit Title ID in the file name, e.g. `Game [0100ABCD00012000][v0].nsp`;
  2. inside NSP/NSZ packages: the ticket names (plaintext) and, for decrypted dumps, the NCA headers;
  3. the game name, looked up in a cached title catalogue;
  4. otherwise a stable ID generated from the title.
- Update and DLC Title IDs are folded into their base game, so a game and its update are one library entry, and the base game file is the one launched.
- Official names from the Nlib API, cached on disk (an offline PC just keeps the names from the files).
- Playtime tracking, saved while you play (every 15 s) and when the emulator closes.
- Fullscreen option and custom launch arguments.

## Install
Close Galaxy, replace the plugin folder with this one and start Galaxy. Do not use "Disconnect" on the integration afterwards: Galaxy discards custom covers and edits made to the games when a platform is disconnected and reconnected.

## config.ini
Stored in `%LOCALAPPDATA%\GOG.com\Galaxy\Configuration\plugins\nswitch\config.ini` and edited from the plugin's settings page. Extra options that only exist in the file:

```ini
[EmuSettings]
; replaces the built-in options; {game} is the game path (appended if missing)
launch_args = -f -g {game}

[Detection]
extensions = .nsp,.xci,.nsz,.xcz
```

## Notes
- XCI/XCZ files carry no readable Title ID without console keys, so they are identified by file name or title.
- There is intentionally no global region selector.
- Covers, dates and descriptions come from GOG's GamesDB, which plugins cannot edit. Use Edit in Galaxy for games it does not know.

## Data sources
- Title catalogue: Langegen/switch-game-collection (downloaded at most every 14 days, only when a file has no readable Title ID).
- Names: Nlib API (api.nlib.cc).

## License
MIT. See LICENSE.md.
