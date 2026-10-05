"""game_times.json: playtime per Galaxy game ID.

{"__meta__": {...}, "<id>": {"name", "time_played" (minutes), "time_remainder_seconds", "last_time_played"}}
Schema stays at 2 (minutes) so older plugin versions can still read the file; the seconds
remainder is an extra field they ignore.
"""
import json
import logging
import os
import re
import shutil
import tempfile
import unicodedata

import config

META_KEY = "__meta__"
NAME_ID_PREFIX = "NSWITCH-NAME-"
_META = {"schema_version": 2, "time_unit": "minutes", "precision": "seconds"}


def _norm_name(value):
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch)).casefold()
    return re.sub(r"\s+", " ", re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)).strip()


def _int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _blank(name):
    return {"name": name, "time_played": 0, "time_remainder_seconds": 0, "last_time_played": None}


def _seconds(entry):
    return _int(entry.get("time_played")) * 60 + _int(entry.get("time_remainder_seconds"))


def _set_seconds(entry, total):
    entry["time_played"], entry["time_remainder_seconds"] = divmod(max(0, total), 60)


def _entries(data):
    return [(k, v) for k, v in data.items() if k != META_KEY and isinstance(v, dict)]


class PlaytimeStore:
    @staticmethod
    def path():
        return config.expand(config.GAME_TIMES_LOC)

    def load(self):
        path = self.path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, encoding="utf-8") as fh:
                value = json.load(fh)
            return value if isinstance(value, dict) else {}
        except FileNotFoundError:
            return {}
        except (ValueError, OSError):
            # Keep an unreadable file instead of silently overwriting the playtime in it.
            logging.exception("DEV: game_times.json unreadable, keeping a .bak copy")
            try:
                shutil.copyfile(path, path + ".bak")
            except OSError:
                pass
            return {}

    def save(self, data):
        path = self.path()
        directory = os.path.dirname(path)
        os.makedirs(directory, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix="game_times_", suffix=".json", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=4)
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                try:
                    os.unlink(temp)
                except OSError:
                    pass

    @staticmethod
    def upgrade(data):
        """Bring an old file up to date. Returns True when it changed."""
        meta = data.get(META_KEY)
        version = _int(meta.get("schema_version")) if isinstance(meta, dict) else 0
        changed = False
        if version < 2:
            # 0.1.x stored seconds while Galaxy's GameTime API stores minutes.
            for _key, entry in _entries(data):
                entry["time_played"] = _int(entry.get("time_played")) // 60
            changed = True
        if version < 2 or not isinstance(meta, dict) or meta.get("precision") != "seconds":
            data[META_KEY] = dict(_META, schema_version=max(version, 2)) if version >= 2 else dict(_META)
            changed = True
        for _key, entry in _entries(data):
            if "time_remainder_seconds" not in entry:
                entry["time_remainder_seconds"] = 0
                changed = True
        return changed

    def reconcile(self, games, data):
        """Make sure every game has an entry and move playtime recorded under its older IDs.

        Older IDs: explicit game.legacy_ids (update/DLC Title IDs, name-hash IDs) and, for games
        that now have a real Title ID, old NSWITCH-NAME-* records with the same name.
        Returns True when data changed.
        """
        changed = self.upgrade(data)
        by_name = {}
        for key, entry in _entries(data):
            if key.startswith(NAME_ID_PREFIX):
                name = _norm_name(entry.get("name", ""))
                if name:
                    by_name.setdefault(name, []).append(key)

        for game in games:
            sources = [k for k in game.legacy_ids if k != game.id and isinstance(data.get(k), dict)]
            if not game.id.startswith(NAME_ID_PREFIX):
                for key in by_name.get(_norm_name(game.name), []):
                    if key != game.id and key not in sources and isinstance(data.get(key), dict):
                        sources.append(key)
            target = data.get(game.id)
            if not isinstance(target, dict):
                target = data[game.id] = _blank(game.name)
                changed = True
            for key in sources:
                source = data.pop(key)
                _set_seconds(target, _seconds(target) + _seconds(source))
                last = _int(source.get("last_time_played"))
                if last and last > _int(target.get("last_time_played")):
                    target["last_time_played"] = last
                logging.info("DEV: Switch playtime identity migrated - %s -> %s", key, game.id)
                changed = True
            if target.get("name") != game.name:
                target["name"] = game.name
                changed = True
        return changed

    @staticmethod
    def add_seconds(data, game_id, name, seconds, last_played):
        entry = data.get(game_id)
        if not isinstance(entry, dict):
            entry = data[game_id] = _blank(name)
        _set_seconds(entry, _seconds(entry) + max(0, int(seconds)))
        entry["last_time_played"] = last_played
        return entry
