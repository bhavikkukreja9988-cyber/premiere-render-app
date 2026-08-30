"""Entry point.

    python -m src.main                launch the desktop app
    python -m src.main --station      run a headless render station
    python -m src.main --check        print an environment report and exit
"""

from __future__ import annotations

import argparse
import sys

from src import __version__
from src.app import PremiereRenderApp
from src.core.config import load_config, save_config
from src.core.log import get_logger, setup_logging

logger = get_logger("main")


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="premiere-render-app",
        description="Send a Premiere Pro project to a render station on your LAN, "
                    "render it in Media Encoder, and get the MP4 back.")
    parser.add_argument("--station", action="store_true",
                        help="run as a headless render station (no window)")
    parser.add_argument("--check", action="store_true",
                        help="report on Media Encoder and the agent, then exit")
    parser.add_argument("--port", type=int, default=0, help="override the TCP port")
    parser.add_argument("--log-level", default="", help="DEBUG, INFO, WARNING…")
    parser.add_argument("--version", action="version", version=__version__)
    return parser.parse_args(argv)


def run_check(config) -> int:
    from src.render import media_encoder as ame
    status = ame.probe(config.ame_path)
    print(f"Premiere Render App {__version__}")
    print(f"  workspace         : {config.workspace_dir}")
    print(f"  media encoder     : {status.exe or 'NOT FOUND'}")
    print(f"  version           : {status.version or 'unknown'}")
    print(f"  agent installed   : {status.agent_installed} "
          f"({status.agent_version or '-'})")
    print(f"  agent reporting   : {status.agent_alive}")
    print(f"  encoder running   : {status.running}")
    presets = ame.list_presets()
    print(f"  presets found     : {len(presets)}")
    for name, _ in presets[:10]:
        print(f"      - {name}")
    for note in status.notes:
        print(f"  ! {note}")
    return 0 if status.ready else 1


def main(argv=None) -> int:
    args = parse_args(argv)
    config = load_config()
    if args.port:
        config.tcp_port = args.port
    setup_logging(args.log_level or config.log_level)
    logger.info("Premiere Render App %s starting", __version__)
    save_config(config)

    app = PremiereRenderApp(config)
    if args.check:
        return run_check(config)
    if args.station:
        return app.start_station()
    return app.start()


if __name__ == "__main__":
    sys.exit(main())
