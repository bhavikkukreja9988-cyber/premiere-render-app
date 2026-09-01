"""FileSender application entry point."""

from __future__ import annotations

import argparse
import sys

from src import __version__
from src.app import PremiereRenderApp
from src.core.config import load_config
from src.core.log import get_logger, setup_logging

logger = get_logger("main")


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="filesender",
        description="FileSender — send Premiere projects to a remote Render Station.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report the local Adobe Media Encoder environment and exit",
    )
    parser.add_argument(
        "--log-level",
        default="",
        help="logging level (DEBUG, INFO, WARNING, ERROR)",
    )
    parser.add_argument("--version", action="version", version=__version__)
    return parser.parse_args(argv)


def run_check(config) -> int:
    from src.render import media_encoder as ame

    status = ame.probe(config.ame_path)
    print(f"FileSender {__version__}")
    print(f"  workspace       : {config.workspace_dir}")
    print(f"  media encoder   : {status.exe or 'NOT FOUND'}")
    print(f"  version         : {status.version or 'unknown'}")
    print(f"  agent installed : {status.agent_installed} ({status.agent_version or '-'})")
    print(f"  agent reporting : {status.agent_alive}")
    print(f"  encoder running : {status.running}")
    print(f"  presets found   : {len(ame.list_presets())}")
    for note in status.notes:
        print(f"  ! {note}")
    return 0 if status.ready else 1


def main(argv=None) -> int:
    args = parse_args(argv)
    config = load_config()
    setup_logging(args.log_level or config.log_level)
    logger.info("FileSender %s starting", __version__)

    if args.check:
        return run_check(config)

    return PremiereRenderApp(config).start()


if __name__ == "__main__":
    sys.exit(main())
