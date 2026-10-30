"""Portable entrypoint usable from an installed skill directory."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from india_trader.cli import main

raise SystemExit(main())
