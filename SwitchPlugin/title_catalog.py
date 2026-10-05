"""Offline-first title catalogue: game name -> base Title ID.

Used only for files whose Title ID cannot be read from the file name or the NSP/NSZ container.
The catalogue (Langegen/switch-game-collection) is downloaded at most once per CACHE_TTL.
"""
import difflib
import json
import logging
import os
import re
import tempfile
import threading
import time
import unicodedata
import urllib.request

import config
from version import __version__

CATALOG_URL = "https://raw.githubusercontent.com/Langegen/switch-game-collection/main/EN_catalog.json"
CACHE_TTL = 14 * 24 * 60 * 60
TIMEOUT = 10
_MAX_BYTES = 32 * 1024 * 1024
FUZZY_THRESHOLD = 0.93

_TAG_RE = re.compile(r"\[[^\]]*\]|\([^)]*\)", re.UNICODE)
_DLC_SUFFIX_RE = re.compile(r"\s+\+\s*(?:\d+\s+)?dlc\b.*$", re.I)
_RELEASE_WORD_RE = re.compile(r"\b(?:repack|demo|update|patch|nsp|nsz|xci|xcz)\b", re.I)
_WHITESPACE_RE = re.compile(r"\s+")
_ID_RE = re.compile(r"[0-9A-F]{16}")

_lock = threading.Lock()
_catalog = None      # built once per plugin process (a failed download is not retried until restart)


def normalize_title(value):
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.casefold()
    value = value.replace("™", " ").replace("®", " ").replace("©", " ")
    value = _TAG_RE.sub(" ", value)
    value = _DLC_SUFFIX_RE.sub(" ", value)
    value = _RELEASE_WORD_RE.sub(" ", value)
    value = re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)
    return _WHITESPACE_RE.sub(" ", value).strip()


def _variants(value):
    key = normalize_title(value)
    if not key:
        return []
    variants = [key]
    words = key.split()
    if words[0] == "the" and len(words) > 1:
        variants.append(" ".join(words[1:]))
    if len(words) > 1 and words[-1] == "the":
        variants.append(" ".join(words[:-1]))
    return variants


def _entry_from_raw(entry):
    """Slim catalogue entry {t, id, q}. Accepts both the raw catalogue and our own cache format.

    q is a 3-bit quality hint (1 cover, 2 description, 4 rating) used to choose between
    several entries that share the same name.
    """
    if not isinstance(entry, dict):
        return None
    title = str(entry.get("title") or entry.get("name") or entry.get("t") or "").strip()
    title_id = str(entry.get("title_id") or entry.get("id") or "").upper()
    if not title or not _ID_RE.fullmatch(title_id):
        return None
    if int(title_id, 16) & 0x1FFF:
        # Only base applications (low 13 bits clear); updates and DLC IDs would match the wrong game.
        return None
    if isinstance(entry.get("q"), int):
        quality = entry["q"]
    else:
        rating = entry.get("rating") if entry.get("rating") is not None else entry.get("metacritic")
        quality = (1 if entry.get("cover") is not None else 0) | (2 if entry.get("description") else 0) | (4 if rating is not None else 0)
    return {"t": title, "id": title_id, "q": quality}


def _compact(raw_entries):
    compact, seen = [], set()
    for raw in raw_entries:
        entry = _entry_from_raw(raw)
        if entry and (entry["id"], entry["t"]) not in seen:
            seen.add((entry["id"], entry["t"]))
            compact.append(entry)
    return compact


def _save_atomic(path, data):
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix="switch_catalog_", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            try:
                os.unlink(temp)
            except OSError:
                pass


def _download(cache_path):
    request = urllib.request.Request(CATALOG_URL, headers={"User-Agent": "GOG-Galaxy-SwitchPlugin/" + __version__})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        raw = response.read(_MAX_BYTES + 1)
    if len(raw) > _MAX_BYTES:
        raise ValueError("Switch catalog exceeds safety limit")
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, list):
        raise ValueError("Unexpected Switch catalog format")
    entries = _compact(data)
    _save_atomic(cache_path, {"fetched_at": int(time.time()), "entries": entries})
    logging.info("DEV: Switch title catalogue cached - %d titles", len(entries))
    return entries


def _load_entries():
    cache_path = config.expand(config.CATALOG_CACHE_LOC)
    stale = []
    try:
        with open(cache_path, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and isinstance(data.get("entries"), list):
            stale = _compact(data["entries"])
            fetched_at = int(data.get("fetched_at", 0) or 0)
            if stale and fetched_at and time.time() - fetched_at <= CACHE_TTL:
                return stale
    except (OSError, ValueError, TypeError):
        pass
    try:
        return _download(cache_path)
    except Exception as exc:
        logging.warning("DEV: Switch title catalogue refresh unavailable - %s", exc)
        return stale


class _Catalog:
    def __init__(self, entries):
        self.index = {}      # normalized variant -> [entry]
        self.fuzzy = []      # (entry, normalized title, token set) for the fuzzy fallback
        for entry in entries:
            for key in _variants(entry["t"]):
                self.index.setdefault(key, []).append(entry)
            norm = normalize_title(entry["t"])
            if norm:
                self.fuzzy.append((entry, norm, set(norm.split())))


def _get_catalog():
    global _catalog
    with _lock:
        if _catalog is None:
            _catalog = _Catalog(_load_entries())
        return _catalog


def _pick_candidate(candidates, query_norm):
    # Prefer entries with real artwork/description/rating, then the closest textual match.
    return max(
        candidates,
        key=lambda e: (
            bool(e["q"] & 1),
            bool(e["q"] & 2),
            bool(e["q"] & 4),
            difflib.SequenceMatcher(None, query_norm, normalize_title(e["t"])).ratio(),
        ),
    )


def match_title(title):
    """Catalogue entry {t, id, q} for a game name, or None. Never accepts a weak fuzzy match."""
    catalog = _get_catalog()
    candidates, seen = [], set()
    for key in _variants(title):
        for item in catalog.index.get(key, []):
            if (item["id"], item["t"]) not in seen:
                seen.add((item["id"], item["t"]))
                candidates.append(item)
    query_norm = normalize_title(title)
    if candidates:
        return _pick_candidate(candidates, query_norm)
    if not query_norm:
        return None

    query_tokens = set(query_norm.split())
    query_len = len(query_norm)
    best, best_score = None, 0.0
    for item, item_norm, tokens in catalog.fuzzy:
        overlap = len(query_tokens & tokens) / max(1, len(query_tokens | tokens))
        # score = ratio * 0.75 + overlap * 0.25 and ratio <= 2*min(len)/(len sum): skip hopeless entries
        # before running the expensive matcher. The result is identical to scoring every entry.
        bound = 0.75 * (2.0 * min(query_len, len(item_norm)) / (query_len + len(item_norm))) + 0.25 * overlap
        if bound < FUZZY_THRESHOLD or bound <= best_score:
            continue
        ratio = difflib.SequenceMatcher(None, query_norm, item_norm).ratio()
        score = ratio * 0.75 + overlap * 0.25
        if score > best_score:
            best, best_score = item, score
    return best if best_score >= FUZZY_THRESHOLD else None
