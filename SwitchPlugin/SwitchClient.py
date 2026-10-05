import hashlib
import logging
import os
import re

import config
from definitions import SwitchGame
from metadata import enrich_games
from title_catalog import match_title, normalize_title
from titleid import BASE, ID_RE, base_of, find_in_text, kind_of, kind_rank, title_id_from_pfs0
from playtime import NAME_ID_PREFIX

DEFAULT_EXTENSIONS = {".nsp", ".xci", ".nsz", ".xcz"}
PFS0_EXTENSIONS = {".nsp", ".nsz"}      # containers whose member names reveal the Title ID

_REGION_TAG_RE = re.compile(
    r"(?:\[|\()(?:usa|eur|europe|eu|jpn|jap|japan|jp|kor|chn|china|ww|world|us|uk)(?:[^\])]*)(?:\]|\))",
    re.I,
)
# v1.0 / ver2 / rev 3 as a stand-alone tag (not the end of a word such as "Nov 5")
_VERSION_RE = re.compile(r"(?:\[|\()?(?<![A-Za-z])(?:v|ver|rev)\.?\s*\d+(?:\.\d+)*(?:\]|\))?", re.I)


def parse_extensions(value):
    result = set(DEFAULT_EXTENSIONS)
    for part in (value or "").replace(";", ",").split(","):
        ext = part.strip().lower()
        if ext:
            result.add(ext if ext.startswith(".") else "." + ext)
    return result


def display_title(filename):
    """File name -> readable title: no extension, Title ID, region or version tags."""
    stem = os.path.basename(filename)
    dot = stem.rfind(".")        # titles can contain periods, so only the last one is the extension
    if dot > 0:
        stem = stem[:dot]
    stem = ID_RE.sub(" ", stem)
    stem = _REGION_TAG_RE.sub(" ", stem)
    stem = _VERSION_RE.sub(" ", stem)
    stem = re.sub(r"\[\s*\]|\(\s*\)", " ", stem).replace("_", " ")
    stem = re.sub(r"\s{2,}", " ", stem).strip(" -_")
    return stem or os.path.basename(filename)


def name_game_id(title):
    """Stable ID for games without a Title ID (kept identical to every earlier version)."""
    digest = hashlib.sha1(normalize_title(title).encode("utf-8")).hexdigest()[:16].upper()
    return NAME_ID_PREFIX + digest


class SwitchClient:
    def __init__(self):
        self.games = []

    def scan_games(self, cfg):
        """Scan the ROM folder in cfg. Blocking: run it in a worker thread."""
        rom_path = config.path_value(cfg, "Paths", "roms_path")
        self.games = []
        if not rom_path or not os.path.isdir(rom_path):
            logging.warning("DEV: Switch ROM folder does not exist - %s", rom_path)
            return self.games
        extensions = parse_extensions(cfg.get("Detection", "extensions", fallback=""))

        found = {}                                  # game id -> (rank, SwitchGame)
        legacy = {}                                 # game id -> older IDs of the same game
        stats = {"filename": 0, "container": 0, "catalog": 0, "name": 0}
        scanned = 0
        for root, dirs, files in os.walk(rom_path):
            dirs.sort(key=str.casefold)
            for file in sorted(files, key=str.casefold):
                if file.startswith("._") or os.path.splitext(file)[1].lower() not in extensions:
                    continue
                scanned += 1
                path = os.path.normpath(os.path.join(root, file))
                name = display_title(file)
                name_id = name_game_id(name)

                source = "filename"
                title_id = find_in_text(file)
                if not title_id and os.path.splitext(file)[1].lower() in PFS0_EXTENSIONS:
                    source, title_id = "container", title_id_from_pfs0(path)
                if not title_id:
                    source = "catalog"
                    match = match_title(name)
                    if match:
                        title_id = match["id"]
                        name = match["t"].strip() or name
                if not title_id:
                    source = "name"
                stats[source] += 1

                if title_id:
                    kind, game_id = kind_of(title_id), base_of(title_id)
                    old_ids = {name_id}
                    if game_id != title_id:
                        old_ids.add(title_id)      # updates/DLC used to be listed under their own ID
                else:
                    kind, game_id, old_ids = BASE, name_id, set()
                legacy.setdefault(game_id, set()).update(old_ids)

                logging.debug("DEV: Switch file %s -> %s (%s, %s)", file, game_id, source, kind)
                game = SwitchGame(game_id, name, path, game_id if title_id else None, source=source)
                current = found.get(game_id)
                if current is None or kind_rank(kind) < current[0]:
                    # A base game file beats its update/DLC file as the file to launch.
                    found[game_id] = (kind_rank(kind), game)
                else:
                    logging.debug("DEV: duplicate Switch title ignored - %s", file)

        for game_id, (_rank, game) in found.items():
            game.legacy_ids = tuple(sorted(legacy[game_id] - {game_id}))
            self.games.append(game)

        # Network lookups are optional and cached; failures never remove games.
        enrich_games(self.games)
        self.games.sort(key=lambda g: (g.name.casefold(), g.id))
        logging.info(
            "DEV: Switch scan summary - scanned=%d, filename_ids=%d, container_ids=%d, catalog_ids=%d, "
            "name_only=%d, imported=%d",
            scanned, stats["filename"], stats["container"], stats["catalog"], stats["name"], len(self.games),
        )
        return self.games
