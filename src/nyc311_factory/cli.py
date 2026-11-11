"""Command line: run / fetch / process."""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

from .config import Config, load_config, with_overrides
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
    parser.add_argument("--dataset", help="override dataset name")
    parser.add_argument("--source-type", choices=["api", "csv", "jsonl"],
                        help="override source_type")
    parser.add_argument("--input", help="input file for csv / jsonl sources")
    parser.add_argument("--destinations", help="comma separated: csv,database")
    return parser


def last_window_end(config: Config) -> str:
    manifest_path = Path(config.curated_dir) / "manifest_run.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return manifest["window"]["end"]
    except (OSError, KeyError, json.JSONDecodeError) as error:
        raise ConfigError(f"no usable previous manifest: {error}") from error


def apply_overrides(config: Config, args) -> Config:
    start, end = args.start, args.end
    if args.since_last_run:
        start = last_window_end(config)
        end = date.today().isoformat()
    destinations = tuple(args.destinations.split(",")) if args.destinations else None
    return with_overrides(
        config, start_date=start, end_date=end, dataset=args.dataset,
        source_type=args.source_type, input_path=args.input, destinations=destinations,
    )


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
