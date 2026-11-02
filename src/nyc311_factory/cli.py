"""Command line: run / fetch / process."""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

from .config import Config, load_config, with_window
from .exceptions import ConfigError, FactoryError
from .pipeline import run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nyc311-factory")
    parser.add_argument("command", choices=["run", "fetch", "process"])
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--start", help="override start_date (YYYY-MM-DD)")
    parser.add_argument("--end", help="override end_date (YYYY-MM-DD)")
    parser.add_argument("--since-last-run", action="store_true",
                        help="start from the end of the last manifest window")
    return parser


def last_window_end(config: Config) -> str:
    manifest_path = Path(config.curated_dir) / "manifest_run.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return manifest["window"]["end"]
    except (OSError, KeyError, json.JSONDecodeError) as error:
        raise ConfigError(f"no usable previous manifest: {error}") from error


def apply_overrides(config: Config, args) -> Config:
    start = args.start or config.start_date
    end = args.end or config.end_date
    if args.since_last_run:
        start = last_window_end(config)
        end = date.today().isoformat()
    return with_window(config, start, end)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = apply_overrides(load_config(args.config), args)
        run_pipeline(config,
                     do_fetch=args.command in ("run", "fetch"),
                     do_process=args.command in ("run", "process"))
    except FactoryError as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return error.exit_code
    return 0