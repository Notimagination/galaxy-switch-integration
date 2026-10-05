"""Switch Title ID helpers: filename parsing, ID kinds and NSP/NSZ (PFS0) inspection.

Everything here reads plaintext only (file names and headers); no keys are needed.
"""
import re
import struct

# 16 hex digits that are not part of a longer hex run.
ID_RE = re.compile(r"(?<![0-9A-Fa-f])([0-9A-Fa-f]{16})(?![0-9A-Fa-f])")
# Tickets inside an NSP/NSZ are named after their rights ID: <title id><16 digits of key generation>.tik
_TICKET_RE = re.compile(r"^([0-9a-f]{32})\.tik$", re.I)

BASE, UPDATE, DLC = "base", "update", "dlc"
_KIND_RANK = {BASE: 0, UPDATE: 1, DLC: 2}


def find_in_text(text):
    """First Title ID in a file name, preferring IDs in the retail 01xxxxxx range."""
    ids = [m.upper() for m in ID_RE.findall(text or "")]
    for title_id in ids:
        if title_id.startswith("01"):
            return title_id
    return ids[0] if ids else None


def kind_of(title_id):
    """BASE for an application, UPDATE for its patch (ID | 0x800) or DLC for add-on content (ID | 0x1000+n).

    Application IDs have their low 13 bits clear. IDs outside the regular 0100... application
    range (system/homebrew) are always treated as BASE and never rewritten.
    """
    value = int(title_id, 16)
    if value >> 56 != 0x01 or not value & 0x00FFFFFFFFFFE000:
        return BASE
    if value & 0x1000:
        return DLC
    if value & 0x1FFF == 0x800:
        return UPDATE
    return BASE


def base_of(title_id):
    """Title ID of the base application an update/DLC ID belongs to (unchanged for anything else)."""
    if kind_of(title_id) == BASE:
        return title_id
    return f"{int(title_id, 16) & ~0x1FFF:016X}"


def kind_rank(kind):
    return _KIND_RANK[kind]


def read_pfs0_entries(fileobj):
    """Return [(name, absolute_offset, size)] for the members of a PFS0 container (NSP/NSZ)."""
    header = fileobj.read(0x10)
    if len(header) != 0x10 or header[:4] != b"PFS0":
        raise ValueError("Not a PFS0 container")
    file_count, string_table_size, _ = struct.unpack("<III", header[4:16])
    if file_count <= 0 or file_count > 10000:
        raise ValueError("Invalid PFS0 file count")
    table_size = file_count * 0x18
    table = fileobj.read(table_size)
    if len(table) != table_size:
        raise ValueError("Truncated PFS0 file table")
    string_table = fileobj.read(string_table_size)
    if len(string_table) != string_table_size:
        raise ValueError("Truncated PFS0 string table")
    data_base = 0x10 + table_size + string_table_size

    entries = []
    for i in range(file_count):
        offset, size, name_offset, _ = struct.unpack_from("<QQII", table, i * 0x18)
        if name_offset >= string_table_size:
            continue
        end = string_table.find(b"\0", name_offset)
        if end < 0:
            end = string_table_size
        name = string_table[name_offset:end].decode("utf-8", errors="replace")
        entries.append((name, data_base + offset, size))
    return entries


def _nca_title_id(fileobj, offset):
    """(title_id, content_type) from a *plaintext* NCA header, else None (retail NCA headers are encrypted)."""
    fileobj.seek(offset)
    header = fileobj.read(0x218)
    if len(header) < 0x218 or header[0x200:0x204] not in (b"NCA0", b"NCA2", b"NCA3"):
        return None
    title_id = int.from_bytes(header[0x210:0x218], "little")
    return (f"{title_id:016X}", header[0x205]) if title_id else None


def _pick(title_ids):
    """Most 'base-like' ID; ties keep the first one found."""
    return min(title_ids, key=lambda t: _KIND_RANK[kind_of(t)]) if title_ids else None


def title_id_from_pfs0(path):
    """Title ID of an NSP/NSZ, or None.

    1. Ticket names (<rights id>.tik): plaintext in every standard-crypto dump.
    2. Plaintext NCA headers (decrypted/converted dumps only).
    """
    try:
        with open(path, "rb") as fh:
            members = read_pfs0_entries(fh)

            tickets = []
            for name, _offset, _size in members:
                match = _TICKET_RE.match(name)
                if match:
                    tickets.append(match.group(1)[:16].upper())
            found = _pick(tickets)
            if found:
                return found

            candidates = []
            for name, offset, _size in members:
                if name.lower().endswith((".nca", ".ncz")):
                    result = _nca_title_id(fh, offset)
                    if result:
                        candidates.append(result)
            if not candidates:
                return None
            pool = [c for c in candidates if int(c[0], 16) & 0xFFF == 0] or candidates
            pool = [c for c in pool if c[1] in (0, 1, 2)] or pool   # program / meta / control NCAs first
            counts = {}
            for title_id, _content_type in pool:
                counts[title_id] = counts.get(title_id, 0) + 1
            return max(counts, key=counts.get)
    except (OSError, ValueError, struct.error):
        return None
