import os
import shlex

_QT_FULLSCREEN = {"eden", "eden-cli", "yuzu", "yuzu-mainline", "suyu"}


def build_launch_args(emu_path, game_path, fullscreen=False, custom_args=""):
    """argv for Eden/yuzu/suyu/Ryujinx, or for the user's own template.

    custom_args (config.ini: [EmuSettings] launch_args) replaces the built-in options.
    "{game}" is replaced by the game path, also inside a token (--game={game});
    without a placeholder the game path is appended.
    """
    if custom_args.strip():
        tokens, used = [], False
        for token in shlex.split(custom_args, posix=False):
            token = token.strip('"')
            if "{game}" in token:
                token = token.replace("{game}", game_path)
                used = True
            tokens.append(token)
        if not used:
            tokens.append(game_path)
        return [emu_path] + tokens

    exe_name = os.path.splitext(os.path.basename(emu_path))[0].casefold()
    args = [emu_path]
    if fullscreen:
        if exe_name in _QT_FULLSCREEN:
            args.append("-f")
        elif "ryujinx" in exe_name:
            args.append("--fullscreen")
    if exe_name == "eden-cli":
        args.extend(["--game", game_path])
    else:
        args.append(game_path)
    return args
