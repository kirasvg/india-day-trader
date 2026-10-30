"""Optional loopback integration; enable with INDIA_TRADER_HTTP_TESTS=1."""

import http.client
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path

from india_trader.desk import refresh
from india_trader.server import DeskServer


@unittest.skipUnless(
    os.environ.get("INDIA_TRADER_HTTP_TESTS") == "1",
    "Loopback integration requires explicit socket permission",
)
class HTTPTests(unittest.TestCase):
    def test_private_desk_lifecycle_and_origin_guards(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = DeskServer(Path(tmp), 0, demo=True)
            refresh(server.workspace, server.clock())
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()

            def request(method, path, payload=None, headers=None):
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
                connection.request(
                    method,
                    path,
                    json.dumps(payload) if payload is not None else None,
                    headers or {},
                )
                response = connection.getresponse()
                result = response.status, dict(response.getheaders()), response.read()
                connection.close()
                return result

            try:
                status, headers, body = request("GET", "/api/bootstrap")
                self.assertEqual(status, 200)
                token = json.loads(body)["token"]
                for invalid in (
                    {"Origin": "https://example.com"},
                    {"Host": "attacker.example"},
                    {"Sec-Fetch-Site": "same-site"},
                ):
                    self.assertEqual(request("GET", "/api/state", headers=invalid)[0], 403)
                self.assertEqual(
                    request("POST", "/api/refresh", {}, {"Content-Type": "application/json"})[0],
                    403,
                )
                trusted = {
                    "Content-Type": "application/json",
                    "X-Desk-Token": token,
                    "Origin": server.origin,
                }
                state = json.loads(request("GET", "/api/state")[2])
                identity = state["candidates"][0]["id"]
                self.assertEqual(
                    request("POST", "/api/action", {"action": "track", "id": identity}, trusted)[0],
                    200,
                )
                self.assertEqual(
                    request("POST", "/api/action", {"action": "track", "id": identity}, trusted)[0],
                    400,
                )
                self.assertEqual(
                    request(
                        "POST",
                        "/api/action",
                        {"action": "close", "instrument": "NSE:RELIANCE"},
                        trusted,
                    )[0],
                    200,
                )
                state = json.loads(request("GET", "/api/state")[2])
                self.assertEqual(state["candidates"][0]["state"], "CLOSED")
                self.assertEqual(
                    len(json.loads(request("GET", "/api/review")[2])["closed_trades"]), 1
                )
                self.assertEqual(
                    json.loads(request("GET", "/api/validation")[2])["qualified_sessions"], 0
                )
                self.assertEqual(
                    json.loads(request("GET", "/api/evidence")[2])["status"], "GATES_OPEN"
                )
                self.assertEqual(
                    json.loads(request("GET", "/api/context")[2])["origin"], "SYNTHETIC"
                )
                self.assertEqual(request("POST", "/api/context", {}, trusted)[0], 400)
                self.assertEqual(
                    request("POST", "/api/validate-broker", {"broker": "groww"}, trusted)[0], 400
                )
                self.assertEqual(request("GET", "/../../etc/passwd")[0], 404)
                self.assertTrue(
                    request("GET", "/app.js")[1]["Content-Type"].startswith("text/javascript")
                )
                self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=2)
