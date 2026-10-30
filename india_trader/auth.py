"""User-driven login/session exchange. Never places an order."""

import getpass
import hashlib
import json
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, build_opener

from .brokers import NoRedirect
from .core import read, write
from .secrets import ENV_NAMES, Keychain, credentials


def broker_client(workspace, name=None):
    from .brokers import Broker

    settings = read(workspace / "settings.json") if (workspace / "settings.json").exists() else {}
    name = name or settings.get("broker")
    if name not in ENV_NAMES:
        raise ValueError("Choose a broker during setup or specify --broker")
    values = credentials(name, workspace, settings.get("credential_store") == "keychain")
    return Broker(name, credentials=values)


def exchange_kite(api_key, api_secret, reply):
    request_token = parse_qs(urlparse(reply).query).get("request_token", [reply])[0]
    if not request_token or any(ch.isspace() for ch in request_token):
        raise ValueError("Invalid Kite request token")
    checksum = hashlib.sha256((api_key + request_token + api_secret).encode()).hexdigest()
    body = urlencode(
        {"api_key": api_key, "request_token": request_token, "checksum": checksum}
    ).encode()
    request = Request(
        "https://api.kite.trade/session/token",
        data=body,
        method="POST",
        headers={"X-Kite-Version": "3", "Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with build_opener(NoRedirect).open(request, timeout=25) as response:
            result = json.load(response)
        token = result.get("data", {}).get("access_token")
        if result.get("status") != "success" or not token:
            raise ValueError("Session exchange failed; restart the documented Kite login flow")
        return token
    except (HTTPError, URLError, TimeoutError):
        raise ValueError(
            "Session exchange failed; check network, app configuration and request-token expiry"
        ) from None


def connect(workspace, broker, flow="token", clear=False, prompt=getpass.getpass):
    store = Keychain(workspace)
    settings_path = workspace / "settings.json"
    settings = read(settings_path) if settings_path.exists() else {}
    if clear:
        for name in ENV_NAMES[broker]:
            store.delete(broker, name)
        if settings.get("broker") == broker:
            settings.pop("credential_store", None)
            write(settings_path, settings)
        return {
            "status": "CLEARED",
            "broker": broker,
            "note": "Only this workspace's Keychain entries removed; environment credentials and broker sessions are unchanged",
        }
    values = {}
    if broker == "zerodha":
        values["api_key"] = prompt("Kite API key (hidden): ").strip()
        if flow == "login":
            secret = prompt("Kite API secret (hidden; used once, never stored): ").strip()
            print(
                "Complete login in your browser: https://kite.zerodha.com/connect/login?"
                + urlencode({"v": "3", "api_key": values["api_key"]})
            )
            reply = prompt("Request token or redirect URL after login (hidden): ").strip()
            values["access_token"] = exchange_kite(values["api_key"], secret, reply)
        else:
            values["access_token"] = prompt("Existing Kite access token (hidden): ").strip()
    else:
        if flow != "token":
            raise ValueError(
                "Groww uses a user-generated daily token in this release; choose --flow token"
            )
        print(
            "Generate a daily token in Groww's Trading APIs page: https://groww.in/user/profile/trading-apis"
        )
        values["access_token"] = prompt("Groww access token (hidden): ").strip()
    if not all(values.values()):
        raise ValueError("Empty credential; nothing stored")
    for name, value in values.items():
        store.set(broker, name, value)
    settings.setdefault("broker", broker)
    settings["credential_store"] = "keychain"
    write(settings_path, settings)
    return {
        "status": "STORED",
        "broker": broker,
        "storage": "macOS Keychain",
        "next": "Run doctor --online to verify login and market-data entitlement",
        "note": "No access token or API secret is written to project files",
    }
