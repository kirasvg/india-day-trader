# Security policy

## Reporting a vulnerability

Please use [GitHub private vulnerability reporting](https://github.com/kirasvg/india-day-trader/security/advisories/new) for issues involving credentials, local-server access, unsafe source imports or account-data exposure. If the private reporting form is unavailable, open an issue requesting a private contact channel without disclosing exploit details or private data.

Include the affected version, a minimal reproduction using synthetic data, expected/actual behavior and your assessment of impact. Never include real broker tokens, PAN/document passwords, account identifiers or unredacted notes. Do not test against another person's accounts or machine.

The maintainer is [Kartik Parsoya](https://github.com/kirasvg). Reports are handled on a best-effort basis; no response-time SLA or bounty is promised.

## Supported versions and boundaries

Security fixes currently target the latest 0.3.x research preview. Earlier development builds are not maintained separately. Python 3.9 compatibility is retained for legacy environments; use a currently maintained Python version for private account work.

The app binds to 127.0.0.1, validates same-origin requests and uses mutation tokens. This is a local single-user boundary, not protection against other trusted local programs. Do not expose its port publicly. Credentials belong in environment variables or explicitly enabled macOS Keychain storage, never source files.

The project cannot place, modify or cancel live orders. A simulated result is not an actual fill, an authenticated integration, or a profit forecast. Current and historical data/source/fee gaps are described in the release status. No independent security audit or production certification is claimed.
