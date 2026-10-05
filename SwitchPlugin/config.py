import configparser
import logging
import os
import tempfile

PLUGIN_DIR = r"%LOCALAPPDATA%\GOG.com\Galaxy\Configuration\plugins\nswitch"
CONFIG_LOC = PLUGIN_DIR + r"\config.ini"
GAME_TIMES_LOC = PLUGIN_DIR + r"\game_times.json"
CATALOG_CACHE_LOC = PLUGIN_DIR + r"\title_catalog_cache.json"
METADATA_CACHE_LOC = PLUGIN_DIR + r"\metadata_cache.json"

DEFAULTS = {
    "Paths": {
        "roms_path": "",
        "emu_path": "",
    },
    "EmuSettings": {"emu_fullscreen": "False", "launch_args": ""},
    "Detection": {"extensions": ".nsp,.xci,.nsz,.xcz"},
}


def expand(location):
    return os.path.expandvars(location)


def _read_text(path):
    """Read config.ini as UTF-8 (how the plugin writes it); fall back to ANSI for hand-edited files."""
    with open(path, "rb") as fh:
        raw = fh.read()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def load_config():
    """Defaults overlaid with config.ini. Never raises: a broken file just yields the defaults."""
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_dict(DEFAULTS)
    try:
        parser.read_string(_read_text(expand(CONFIG_LOC)))
    except FileNotFoundError:
        pass
    except (OSError, configparser.Error):
        logging.exception("DEV: could not read the Switch config file, using defaults")
    return parser


def save_config(parser):
    target = expand(CONFIG_LOC)
    directory = os.path.dirname(target)
    os.makedirs(directory, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix="config_", suffix=".ini", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            parser.write(fh)
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            try:
                os.unlink(temp)
            except OSError:
                pass


def clean_path(value):
    """Trim spaces and the quotes Windows adds with 'Copy as path'."""
    return (value or "").strip().strip('"').strip()


def path_value(parser, section, option):
    return clean_path(parser.get(section, option, fallback=""))
