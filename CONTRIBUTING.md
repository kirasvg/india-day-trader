# Contributing

Use Python 3.9 or newer. The checkout runs without installing dependencies.

```bash
python3 -m unittest discover -s tests -v
python3 scripts/demo.py
python3 -m compileall -q india_trader scripts skills
```

Add focused tests for observable behavior, especially session boundaries, no-look-ahead behavior, quote freshness, fees, position sizing and state transitions. Keep provider contract fixtures sourced to official documentation and separate from any private account responses. Use invented credentials only in tests; never commit actual access tokens.

New setups should specify an unambiguous closed-bar trigger, deterministic stop/target rules, an invalidation rule and a consistent historical replay. New data providers should normalize into existing schemas, preserve trade timestamps and surface incomplete data explicitly. Compare documented formats with real account access only in a separately authorized private environment; keep those results out of offline CI.

Before changing installed skill instructions, run the installer into a temporary directory and invoke a bundled runner from outside the checkout. Avoid silently overwriting users' installed skills or paper-account state.

Run the isolated local HTTP integration with `INDIA_TRADER_HTTP_TESTS=1 python3 -m unittest discover -s tests -p test_http.py -v` when loopback sockets are permitted. The test creates its own temporary synthetic workspace and never contacts a broker. GitHub CI enables this check.

Run `python3 scripts/evidence_demo.py` after evidence/source changes. Keep actual account data out of fixtures. An injected client or clock, invented note, mock source or simulated session must never increment a real release gate. Test source-specific time normalization against explicit raw formats and reject unknown hosts/date bases rather than using receipt time as publication.


Development formatting/lint/type checks use pinned Ruff and ty versions in `requirements-dev.txt`; use Python 3.12+ for those tools. Run `ruff format .`, `ruff check .`, and `ty check india_trader` before submitting. Keep runtime compatibility at Python 3.9 and do not add runtime dependencies without an explicit architecture decision. The [release guide](docs/public-release.md) covers workflow checks, built docs and distribution verification.
