# Public release process

The public research preview uses a fresh source history. Private workspaces, original user documents, credentials and earlier development history are excluded. Release preparation follows the [Trail of Bits open-sourcing workflow](https://github.com/trailofbits/skills/blob/main/plugins/open-sourcing/skills/open-sourcing/SKILL.md); the upstream skill itself is not redistributed.

## Before publishing

1. Run a dedicated full-history and current-tree credential scan, with redacted reports. Review file names, documentation, screenshots and Git author metadata separately; a scanner is not proof of absence.
2. Publish only the audited source snapshot if earlier history is uncertain. Preserve the original privately; never push all old branches/tags into the new repository.
3. Run tests, both demos, Ruff formatting/linting, ty, actionlint, zizmor, build checks and the clean-installed smoke test. Build the documentation and follow README instructions from a clean clone.
4. Confirm MIT in LICENSE, README and package metadata. Keep source/data attribution and the experimental release limits visible.
5. After the initial push, enable private vulnerability reporting, secret scanning/push protection, Pages from GitHub Actions, and main-branch protections. Require the Quality and Python 3.12 Linux checks; block force pushes/deletion and require pull requests.

## Contributor checks

Use a maintained Python version, preferably Python 3.12+, for development tools:

```bash
python3 -m pip install -r requirements-dev.txt
ruff format .
ruff check .
ty check india_trader
python3 -m unittest discover -s tests -v
python3 scripts/demo.py
python3 scripts/evidence_demo.py
actionlint
zizmor --offline --no-progress .github/workflows/
python3 scripts/build_docs.py
python3 -m build
python3 -m pip install .
python3 scripts/verify_install.py
```

The application remains standard-library-only and retains Python 3.9 compatibility. CI is configured for Linux Python 3.9–3.14 plus Python 3.12 on macOS and Windows. That compatibility does not make an end-of-life Python runtime suitable for private account use.

## Releases

A maintainer creates a matching `vX.Y.Z` tag and pushes that tag. The release workflow verifies the package version, reruns checks, builds wheel/source distributions, generates artifact provenance and uploads a GitHub **prerelease**. Research previews remain prereleases while live evidence gates are open. Do not publish a package name to PyPI without first establishing ownership and configuring trusted publishing; no PyPI token or automatic PyPI publishing is included here.

Dependency and Action updates are grouped and delayed by seven days. Pinned Actions and developer tools still require review before merging. Repository/Pages settings and hosted CI results are separate from checks run locally and must be verified on GitHub after publication.

## Executed local preparation — 2026-10-30

The release snapshot passed Gitleaks 8.30.1 current-tree scanning (zero detected secrets), Ruff 0.17.3 formatting/linting, ty 0.0.95 core checks, actionlint and zizmor workflow checks, the existing offline suite and both synthetic tours. API/guide pages build locally. These are tool-specific results, not a security certification or live-market validation. Earlier development history is excluded from this public repository.
