"""Explicit user attestations; never relabel these as broker-authenticated facts."""

from .core import key, number, read, write
from .store import Store


def confirm_account(workspace, cash, exposed, now, reviewed=False):
    config = read(workspace / "config.json")
    if config.get("account_source") != "MANUAL_ATTESTATION" or reviewed is not True:
        raise ValueError("Manual account confirmation requires data-only mode and explicit review")
    cash = number(cash)
    if cash < 0:
        raise ValueError("Available unleveraged cash cannot be negative")
    if not isinstance(exposed, str):
        raise ValueError("Exposure must be a comma-separated string")
    names = [v.strip().upper() for v in exposed.split(",") if v.strip()]
    if len(names) > 500 or len(names) != len(set(names)):
        raise ValueError("Use at most 500 distinct exposure instruments")
    for name in names:
        if len(name.split(":")) != 2:
            raise ValueError("Use EXCHANGE:SYMBOL for every exposure")
        key(*name.split(":"))
    # Block a matching symbol on either exchange conservatively.
    symbols = {name.split(":")[1] for name in names}
    names = sorted(set(names) | {k for k in config["watchlist"] if k.split(":")[1] in symbols})
    result = {
        "status": "MANUAL_ATTESTED",
        "broker": config["broker"],
        "source": "USER_ATTESTATION",
        "checked_at": now.isoformat(),
        "available_cash_inr": str(cash),
        "exposed_instruments": names,
        "note": "User confirmed all holdings, positions and pending orders. Not verified against broker. Reconfirm within 120 seconds before tracking an entry and after any account change.",
    }
    write(workspace / "broker-snapshot.json", result)
    Store(workspace).event("MANUAL_ACCOUNT_ATTESTATION", result, now.isoformat(), "USER")
    return result
