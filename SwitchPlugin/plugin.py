"""Galaxy Nintendo Switch Integration: local Switch library launched through an emulator (Eden and similar).

Author: Notimagination
"""
import asyncio
import logging
import os
import subprocess
import sys
import time

import config
from backend import AuthenticationServer
from galaxy.api.consts import LicenseType, LocalGameState, Platform
from galaxy.api.errors import UnknownError
from galaxy.api.plugin import Plugin, create_and_run_plugin
from galaxy.api.types import Authentication, Game, GameTime, LicenseInfo, LocalGame, NextStep
from launcher import build_launch_args
from playtime import PlaytimeStore
from SwitchClient import SwitchClient
from version import __version__

CHECKPOINT_INTERVAL = 15      # seconds between playtime saves while a game runs
CHECKPOINT_MIN_SECONDS = 30   # ...but only when at least this much unsaved time has piled up


class NintendoSwitchPlugin(Plugin):
    def __init__(self, reader, writer, token):
        super().__init__(Platform.NintendoSwitch, __version__, reader, writer, token)
        self.auth_server = AuthenticationServer()
        self.auth_server.start()
        self.switch_client = SwitchClient()
        self.playtime = PlaytimeStore()
        self.games = []
        self.local_games_cache = None
        self.proc = None
        self.running_game_id = ""
        self._session_start = 0.0      # time.monotonic() at launch
        self._session_saved = 0        # session seconds already written to game_times.json
        self.update_local_games_task = self.create_task(asyncio.sleep(0), "Update local games")
        # Galaxy may issue one start_game_times_import request per game in quick succession;
        # handling them one at a time avoids Galaxy's ImportInProgress errors.
        self._game_time_queue = asyncio.Queue()
        self._game_time_worker_task = self.create_task(self._run_game_time_queue(), "Serialized game time imports")
        self._time_checkpoint_task = self.create_task(self._checkpoint_loop(), "Switch time checkpoint")

    # ---- authentication ----------------------------------------------------------------------
    async def authenticate(self, stored_credentials=None):
        if not stored_credentials:
            return NextStep(
                "web_session",
                {
                    "window_title": "Configure Nintendo Switch Integration",
                    "window_width": 550,
                    "window_height": 800,
                    "start_uri": f"http://localhost:{self.auth_server.port}",
                    "end_uri_regex": ".*/end.*",
                },
            )
        return self._do_auth()

    async def pass_login_credentials(self, step, credentials, cookies):
        return self._do_auth()

    def _do_auth(self):
        roms = config.path_value(config.load_config(), "Paths", "roms_path")
        self.store_credentials({"username": roms})
        return Authentication("switch_user", roms)

    # ---- library -----------------------------------------------------------------------------
    async def get_owned_games(self):
        cfg = config.load_config()
        self.games = await asyncio.to_thread(self.switch_client.scan_games, cfg)
        return [Game(g.id, g.name, [], LicenseInfo(LicenseType.SinglePurchase, None)) for g in self.games]

    async def get_local_games(self):
        self.local_games_cache = self._local_games_list()
        return self.local_games_cache

    def _local_games_list(self):
        result = []
        for game in self.games:
            state = LocalGameState.Installed
            if self.running_game_id == game.id:
                state |= LocalGameState.Running
            result.append(LocalGame(game.id, state))
        return result

    async def install_game(self, game_id):
        return

    async def uninstall_game(self, game_id):
        return

    async def prepare_local_size_context(self, game_ids):
        sizes = {}
        for game in self.games:
            try:
                sizes[game.id] = os.path.getsize(game.path)
            except OSError:
                pass
        return sizes

    async def get_local_size(self, game_id, context):
        return context.get(game_id)

    # ---- launching ---------------------------------------------------------------------------
    async def launch_game(self, game_id):
        cfg = config.load_config()
        emu_path = config.path_value(cfg, "Paths", "emu_path")
        fullscreen = cfg.getboolean("EmuSettings", "emu_fullscreen", fallback=False)
        custom_args = cfg.get("EmuSettings", "launch_args", fallback="")
        if not emu_path or not os.path.isfile(emu_path):
            raise RuntimeError("Switch emulator executable not found: " + emu_path)
        if self.proc is not None and self.proc.poll() is None:
            raise RuntimeError("A Switch game is already running")
        game = next((g for g in self.games if g.id == game_id), None)
        if game is None:
            raise RuntimeError("Switch game not found: " + str(game_id))
        if not os.path.exists(game.path):
            raise RuntimeError("Switch game file not found: " + game.path)

        args = build_launch_args(emu_path, game.path, fullscreen, custom_args)
        self.proc = subprocess.Popen(args, cwd=os.path.dirname(emu_path) or None)
        self.running_game_id = game.id
        self._session_start = time.monotonic()
        self._session_saved = 0
        logging.info("DEV: Switch emulator launched - %s", args)
        if self.local_games_cache is not None:
            self._sync_local_states()       # show "Running" right away instead of at the next 5 s poll
        try:    # make sure the playtime record exists under the right ID
            data = self.playtime.load()
            if self.playtime.reconcile(self.games, data):
                self.playtime.save(data)
        except Exception:
            logging.exception("DEV: Switch playtime reconcile at launch failed")

    # ---- playtime ----------------------------------------------------------------------------
    def _times_snapshot(self):
        data = self.playtime.load()
        if self.playtime.reconcile(self.games, data):
            self.playtime.save(data)
        return {
            game.id: GameTime(game.id, _minutes(data[game.id]), data[game.id].get("last_time_played"))
            for game in self.games
        }

    async def prepare_game_times_context(self, game_ids):
        return self._times_snapshot()

    async def get_game_time(self, game_id, context):
        return context.get(game_id, GameTime(game_id, 0, None))

    async def _start_game_times_import(self, game_ids):
        await self._game_time_queue.put(list(game_ids or []))

    async def _run_game_time_queue(self):
        while True:
            ids = await self._game_time_queue.get()
            try:
                context = await self.prepare_game_times_context(ids)
                for game_id in ids:
                    try:
                        self._game_time_import_success(game_id, await self.get_game_time(game_id, context))
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logging.exception("DEV: Switch game time import failed - %s", game_id)
                        self._game_time_import_failure(game_id, UnknownError())
                self._game_times_import_finished()
                self.game_times_import_complete()
            except asyncio.CancelledError:
                raise
            except Exception:
                logging.exception("DEV: Switch game time import batch failed")
            finally:
                self._game_time_queue.task_done()

    def _flush_session(self, min_seconds=0):
        """Write the part of the running session that is not saved yet and tell Galaxy."""
        game_id = self.running_game_id
        if not game_id:
            return
        elapsed = int(time.monotonic() - self._session_start)
        pending = elapsed - self._session_saved
        if pending <= 0 or pending < min_seconds:
            return
        name = next((g.name for g in self.games if g.id == game_id), game_id)
        data = self.playtime.load()
        self.playtime.upgrade(data)
        entry = self.playtime.add_seconds(data, game_id, name, pending, int(time.time()))
        self.playtime.save(data)
        self._session_saved = elapsed
        self.update_game_time(GameTime(game_id, _minutes(entry), entry["last_time_played"]))

    async def _checkpoint_loop(self):
        while True:
            await asyncio.sleep(CHECKPOINT_INTERVAL)
            try:
                if self.proc is not None and self.proc.poll() is None:
                    self._flush_session(CHECKPOINT_MIN_SECONDS)
            except asyncio.CancelledError:
                raise
            except Exception:
                logging.exception("DEV: Switch playtime checkpoint failed")

    def _end_session(self):
        try:
            self._flush_session()
            logging.info("DEV: Switch session finished - %s", self.running_game_id)
        except Exception:
            logging.exception("DEV: Switch playtime save failed")
        finally:
            self.proc = None
            self.running_game_id = ""
            self._session_saved = 0
            if self.local_games_cache is not None:
                self._sync_local_states()

    # ---- housekeeping ------------------------------------------------------------------------
    def tick(self):
        try:
            if self.proc is not None and self.proc.poll() is not None:
                self._end_session()
        except Exception:
            logging.exception("DEV: Error checking Switch emulator process")
        if self.local_games_cache is not None and self.update_local_games_task.done():
            self.update_local_games_task = self.create_task(self._update_local_games(), "Update local games")

    def _sync_local_states(self):
        """Tell Galaxy about local games whose state (installed / running) changed."""
        new_list = self._local_games_list()
        old = {g.game_id: g.local_game_state for g in self.local_games_cache or []}
        for game in new_list:
            if old.get(game.game_id) != game.local_game_state:
                self.update_local_game_status(game)
        self.local_games_cache = new_list

    async def _update_local_games(self):
        self._sync_local_states()
        await asyncio.sleep(5)

    async def shutdown(self):
        for task in (self._game_time_worker_task, self._time_checkpoint_task):
            if not task.done():
                task.cancel()
        try:
            if self.proc is not None:
                self._flush_session()     # Galaxy is closing while a game runs: keep what was played
        except Exception:
            logging.exception("DEV: Switch playtime save at shutdown failed")
        self.auth_server.stop()


def _minutes(entry):
    try:
        return int(entry.get("time_played", 0) or 0)
    except (TypeError, ValueError):
        return 0


def main():
    create_and_run_plugin(NintendoSwitchPlugin, sys.argv)


if __name__ == "__main__":
    main()
