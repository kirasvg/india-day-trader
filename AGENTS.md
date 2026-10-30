# Project guidance

This project implements eleven Indian cash-equity research skills with a shared Python standard-library engine.

- Run `python3 -m unittest discover -s tests -v` and `python3 scripts/demo.py` after behavioral changes.
- Keep Python 3.9 compatibility and no runtime dependencies. Monetary arithmetic uses Decimal. Market-data and account adapters are GET-only. The explicit user-driven Kite login flow alone may POST to the fixed session-token endpoint; no order mutation endpoints are implemented.
- Do not substitute US calendars, symbols, tax assumptions or broker semantics. User inputs have explicit timezone offsets; broker-naive response times are normalized to IST.
- Preserve closed-bar signal timing, prior-session-only simulation pools, fresh exchange timestamps, and risk rechecks at ticket/paper-fill time.
- All fixtures in `india_trader/templates/demo/` are synthetic. Regenerate with `python3 scripts/make_demo.py`; never relabel them as market observations.
- User credentials/account state belong outside the source tree. Do not add live order submission casually to the research or paper modules.
- Update README, data contracts and skill instructions when CLI behavior changes. Installed skills bundle code/templates/references; test installation into a temporary destination.
- `docs/validation.md` distinguishes executed checks from configured CI and untested account-authenticated integrations.
