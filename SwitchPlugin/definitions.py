from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class SwitchGame:
    id: str                              # Galaxy game ID: base Title ID, or NSWITCH-NAME-<hash>
    name: str
    path: str                            # file launched by the emulator
    title_id: Optional[str] = None       # base application Title ID, when known
    legacy_ids: Tuple[str, ...] = ()     # older Galaxy IDs of the same game (playtime is moved from them)
    source: str = ""                     # filename | container | catalog | name
