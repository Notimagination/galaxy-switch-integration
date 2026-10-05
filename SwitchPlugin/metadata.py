"""Official game names from the Nlib API, cached on disk. Network trouble never removes games."""
import json
import logging
import os
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

import config
from version import __version__

NLIB_BASE = "https://api.nlib.cc/nx"
FOUND_TTL = 30 * 24 * 60 * 60
MISSING_TTL = 7 * 24 * 60 * 60          # Title IDs Nlib does not know (404) are retried weekly, not on every scan
TIMEOUT = 3.5
MAX_NETWORK_FAILURES = 3                # consecutive timeouts/errors before giving up for this scan
FIELDS = (
    "name,description,publisher,developer,releaseDate,category,region,"
    "isDemo,ratingContent,icon,banner,screens"
)
_KEEP = ("name", "missing", "fetched_at")   # the plugin only needs the name; everything else is dropped


def _load_cache():
    """Return (cache, dirty). dirty means old entries carried extra fields that a save will trim."""
    try:
        with open(config.expand(config.METADATA_CACHE_LOC), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}, False
    if not isinstance(data, dict):
        return {}, False
    cache, dirty = {}, False
    for key, entry in data.items():
        if isinstance(entry, dict):
            slim = {k: entry[k] for k in _KEEP if k in entry}
            dirty = dirty or len(slim) != len(entry)
            cache[str(key).upper()] = slim
    return cache, dirty


def _save_cache(cache):
    path = config.expand(config.METADATA_CACHE_LOC)
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix="metadata_", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(cache, fh, ensure_ascii=False, indent=2)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            try:
                os.unlink(temp)
            except OSError:
                pass


def _fetch(title_id):
    """Nlib record for a Title ID, or None when Nlib does not know it (HTTP 404)."""
    url = f"{NLIB_BASE}/{urllib.parse.quote(title_id, safe='')}?lang=en&fields={urllib.parse.quote(FIELDS, safe=',')}"
    request = urllib.request.Request(url, headers={"User-Agent": "GOG-Galaxy-SwitchPlugin/" + __version__})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            data = json.loads(response.read(512 * 1024).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    return data if isinstance(data, dict) else None


def _is_fresh(entry, now):
    ttl = MISSING_TTL if entry.get("missing") else FOUND_TTL
    return now - int(entry.get("fetched_at", 0) or 0) <= ttl


def _refresh(cache, title_ids, now):
    """Fetch the given IDs into cache. Returns True when the cache changed."""
    state = {"failures": 0}

    def work(title_id):
        if state["failures"] >= MAX_NETWORK_FAILURES:
            raise ConnectionAbortedError("offline")
        try:
            result = _fetch(title_id)
        except Exception:
            state["failures"] += 1
            raise
        state["failures"] = 0
        return result

    changed = False
    with ThreadPoolExecutor(max_workers=min(6, len(title_ids))) as pool:
        futures = {pool.submit(work, tid): tid for tid in title_ids}
        for future in as_completed(futures):
            title_id = futures[future]
            try:
                data = future.result()
            except ConnectionAbortedError:
                continue
            except Exception as exc:
                logging.warning("DEV: metadata lookup failed - %s (%s)", title_id, exc)
                continue
            name = data.get("name") if data else None
            if isinstance(name, str) and name.strip():
                cache[title_id] = {"name": name.strip(), "fetched_at": now}
                logging.debug("DEV: metadata matched - %s -> %s", title_id, name.strip())
            else:
                cache[title_id] = {"missing": True, "fetched_at": now}
            changed = True
    if state["failures"] >= MAX_NETWORK_FAILURES:
        logging.warning("DEV: Nlib unreachable, remaining Switch titles keep their local names")
    return changed


def enrich_games(games):
    """Replace each game's name with the official one when Nlib (or its cache) knows the Title ID."""
    cache, dirty = _load_cache()
    now = int(time.time())
    stale = sorted({g.title_id for g in games if g.title_id and not _is_fresh(cache.get(g.title_id, {}), now)})
    if stale:
        logging.info("DEV: metadata refresh queued for %d Switch title IDs", len(stale))
        dirty = _refresh(cache, stale, now) or dirty
    if dirty:
        try:
            _save_cache(cache)
        except OSError:
            logging.exception("DEV: Could not save Switch metadata cache")

    enriched = 0
    for game in games:
        name = (cache.get(game.title_id) or {}).get("name") if game.title_id else None
        if isinstance(name, str) and name.strip():
            game.name = name.strip()
            enriched += 1
    logging.info("DEV: metadata enriched %d/%d Switch games", enriched, len(games))
    return games
