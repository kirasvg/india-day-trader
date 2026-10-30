"""Locate the bundled engine in an installed skill or source checkout."""

import sys
from pathlib import Path

location = Path(__file__).resolve().parent
root = location if (location / "india_trader").is_dir() else location.parents[1]
sys.path.insert(0, str(root))
from india_trader.cli import main

raise SystemExit(main())
