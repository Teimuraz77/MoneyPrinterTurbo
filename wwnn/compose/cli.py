"""Container entry point for the compositing stage: ``python -m wwnn.compose.cli --run-dir ...``."""

from __future__ import annotations

import argparse
from pathlib import Path

from wwnn.compose.timeline import compose_all
from wwnn.config import Settings
from wwnn.util import read_json


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True, type=Path)
    args = ap.parse_args(argv)
    compose_all(args.run_dir, Settings.from_env(), read_json(args.run_dir / "script" / "approved.json"))


if __name__ == "__main__":
    main()
