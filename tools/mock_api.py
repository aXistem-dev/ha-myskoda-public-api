"""A stand-in for the MyŠkoda Public API with the sample vehicles of tests/fixtures."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import threading
import time
from typing import Any

FIXTURES = Path(__file__).parent.parent / "tests" / "fixtures"
PROBLEMS = "https://public.api.connect.skoda-auto.cz/problems"
PATH = re.compile(r"^/api/v1/vehicles/(?P<vin>[^/]+)(?:/(?P<rest>.+))?$")

# A plain drawing in place of the vehicle picture the real service links to.
RENDER = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 260">
<path d="M70 170c10-40 40-52 80-58l60-52c14-12 30-18 50-18h130c24 0 42 8 58
24l44 46c50 6 82 22 88 60l4 28H56z" fill="#0e3a2f"/>
<path d="M222 70c8-7 18-10 30-10h60v54H170zm108-10h58c14 0 26 5 36 15l38
39H330z" fill="#cfe8e0"/>
<circle cx="180" cy="200" r="40" fill="#1c1c1c"/><circle cx="180" cy="200" r="18" fill="#bdbdbd"/>
<circle cx="470" cy="200" r="40" fill="#1c1c1c"/><circle cx="470" cy="200" r="18" fill="#bdbdbd"/>
</svg>"""


class Garage:
    """The vehicles, their quota, and the commands under way."""

    def __init__(
        self, limit: int, delay: float, key_days: int, render_base: str | None
    ) -> None:
        self.limit = limit
        self.delay = delay
        self.expires = datetime.now(UTC) + timedelta(days=key_days)
        self.lock = threading.Lock()
        self.vehicles: dict[str, dict[str, Any]] = {}
        self.windows: dict[str, tuple[float, int]] = {}
        for path in sorted(FIXTURES.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            vin = payload["vehicle"].get("vin")
            if vin and not payload.get("errors"):
                if render_base and "renderUrl" in payload["vehicle"]:
                    payload["vehicle"]["renderUrl"] = f"{render_base}/render/{vin}.svg"
                self.vehicles[vin] = payload

    def spend(self, vin: str) -> tuple[bool, dict[str, str]]:
        """Count a request; return (allowed, quota headers)."""
        now = time.monotonic()
        start, used = self.windows.get(vin, (now, 0))
        if now - start >= 3600:
            start, used = now, 0
        allowed = used < self.limit
        if allowed:
            used += 1
        self.windows[vin] = (start, used)
        reset = max(1, round(3600 - (now - start)))
        headers = {
            "RateLimit-Limit": str(self.limit),
            "RateLimit-Remaining": str(self.limit - used),
            "RateLimit-Reset": str(reset),
        }
        if not allowed:
            headers["Retry-After"] = str(reset)
        return allowed, headers

    def later(self, vin: str, section: str, change: Any) -> None:
        """Apply a change once the vehicle has 'carried it out'."""

        def _apply() -> None:
            with self.lock:
                vehicle = self.vehicles[vin]["vehicle"]
                change(vehicle)
                stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                if isinstance(vehicle.get(section), dict):
                    vehicle[section]["carCapturedTimestamp"] = stamp

        threading.Timer(self.delay, _apply).start()


def _set(*path: str, value: Any) -> Any:
    def _change(vehicle: dict[str, Any]) -> None:
        node = vehicle
        for key in path[:-1]:
            node = node.setdefault(key, {})
        node[path[-1]] = value

    return _change


def _charging(on: bool) -> Any:
    def _change(vehicle: dict[str, Any]) -> None:
        status = vehicle["charging"]["status"]
        status["state"] = "CHARGING" if on else "READY_FOR_CHARGING"
        status["chargePowerInKw"] = 10.5 if on else 0
        status["chargingRateInKilometersPerHour"] = 52.0 if on else 0
        status["chargeType"] = "AC" if on else "OFF"

    return _change


def _climate(body: dict[str, Any]) -> Any:
    def _change(vehicle: dict[str, Any]) -> None:
        climate = vehicle["airConditioning"]
        if target := body.get("targetTemperature"):
            climate["targetTemperature"] = target
        climate["state"] = "HEATING"

    return _change


def _profile(body: dict[str, Any]) -> Any:
    def _change(vehicle: dict[str, Any]) -> None:
        profiles = vehicle["chargingProfiles"]["profiles"]
        for index, profile in enumerate(profiles):
            if profile["id"] == body["id"]:
                profiles[index] = body

    return _change


class Handler(BaseHTTPRequestHandler):
    """Answer like the public API does."""

    garage: Garage
    protocol_version = "HTTP/1.1"

    def _send(
        self, status: int, body: Any = None, headers: dict[str, str] | None = None
    ) -> None:
        data = b"" if body is None else json.dumps(body).encode()
        self.send_response(status)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        if body is not None:
            content_type = (
                "application/problem+json" if status >= 400 else "application/json"
            )
            self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _problem(
        self, status: int, slug: str | None, headers: dict[str, str] | None = None
    ) -> None:
        self._send(
            status,
            {
                "type": f"{PROBLEMS}/{slug}" if slug else "about:blank",
                "title": slug or "Error",
                "status": status,
                "detail": (slug or "error").replace("-", " "),
            },
            headers,
        )

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            body = json.loads(self.rfile.read(length))
        except ValueError:
            return {}
        return body if isinstance(body, dict) else {}

    def _handle(self, method: str) -> None:
        garage = self.garage
        body = self._body()
        path, _, query = self.path.partition("?")
        if method == "GET" and path.startswith("/render/"):
            data = RENDER.encode()
            self.send_response(200)
            self.send_header("Content-Type", "image/svg+xml")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return None
        match = PATH.match(path)
        if match is None:
            return self._problem(404, None)
        key = self.headers.get("X-API-Key")
        if not key or key == "expired":
            return self._problem(401, "api-key-expired" if key else None)
        if key == "unauthorized":
            return self._problem(403, "api-key-not-authorized")
        vin, rest = match["vin"], match["rest"]
        if vin not in garage.vehicles:
            return self._problem(404, None)

        with garage.lock:
            allowed, headers = garage.spend(vin)
            headers["X-API-Key-Expires-At"] = garage.expires.strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            if not allowed:
                return self._problem(429, "rate-limit-exceeded", headers)
            payload = json.loads(json.dumps(garage.vehicles[vin]))
        vehicle = payload["vehicle"]
        operations = {op["name"] for op in vehicle.get("operations", [])}

        if rest is None:
            if method != "GET":
                return self._problem(405, None, headers)
            include = [p for p in query.removeprefix("include=").split(",") if p]
            if include and "include=" in query:
                keep = {"vin"}
                for part in include:
                    keep.update(
                        ("name", "licensePlate", "renderUrl")
                        if part == "info"
                        else (part,)
                    )
                payload["vehicle"] = {k: v for k, v in vehicle.items() if k in keep}
            return self._send(200, payload, headers)

        commands: dict[tuple[str, str], tuple[str, str, Any]] = {
            ("POST", "charging/start"): ("startCharging", "charging", _charging(True)),
            ("POST", "charging/stop"): ("stopCharging", "charging", _charging(False)),
            ("PUT", "charging/limit"): (
                "setChargingLimit",
                "charging",
                _set(
                    "charging",
                    "settings",
                    "targetStateOfChargeInPercent",
                    value=body.get("targetStateOfChargeInPercent"),
                ),
            ),
            ("PUT", "charging/mode"): (
                "setChargeMode",
                "charging",
                _set(
                    "charging",
                    "settings",
                    "preferredChargeMode",
                    value=body.get("chargeMode"),
                ),
            ),
            ("POST", "air-conditioning/start"): (
                "startAirConditioning",
                "airConditioning",
                _climate(body),
            ),
            ("POST", "air-conditioning/stop"): (
                "stopAirConditioning",
                "airConditioning",
                _set("airConditioning", "state", value="OFF"),
            ),
            ("POST", "auxiliary-heating/start"): (
                "startAuxiliaryHeating",
                "auxiliaryHeating",
                _set("auxiliaryHeating", "state", value="HEATING_AUXILIARY"),
            ),
            ("POST", "auxiliary-heating/stop"): (
                "stopAuxiliaryHeating",
                "auxiliaryHeating",
                _set("auxiliaryHeating", "state", value="OFF"),
            ),
            ("POST", "active-ventilation/start"): (
                "startActiveVentilation",
                "activeVentilation",
                _set("activeVentilation", "state", value="VENTILATION"),
            ),
            ("POST", "active-ventilation/stop"): (
                "stopActiveVentilation",
                "activeVentilation",
                _set("activeVentilation", "state", value="OFF"),
            ),
        }
        command = commands.get((method, rest))
        if (
            command is None
            and method == "PUT"
            and rest.startswith("charging-profiles/")
        ):
            profile_id = rest.rsplit("/", 1)[1]
            if str(body.get("id")) != profile_id:
                return self._problem(412, None, headers)
            known = {
                str(p["id"])
                for p in vehicle.get("chargingProfiles", {}).get("profiles", [])
            }
            if profile_id not in known:
                return self._problem(404, None, headers)
            command = ("updateChargingProfile", "chargingProfiles", _profile(body))
        if command is None:
            return self._problem(404, None, headers)
        operation, section, change = command
        if operation not in operations:
            return self._problem(422, "operation-not-supported", headers)
        if operation == "startAuxiliaryHeating" and not body.get("spin"):
            return self._problem(400, None, headers)
        garage.later(vin, section, change)
        return self._send(202, None, headers)

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")

    def do_PUT(self) -> None:
        self._handle("PUT")

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.log_date_time_string()} {format % args}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--limit", type=int, default=20, help="requests per hour")
    parser.add_argument(
        "--delay", type=float, default=20, help="seconds a command takes"
    )
    parser.add_argument(
        "--key-days", type=int, default=365, help="days until the key expires"
    )
    parser.add_argument(
        "--render-base",
        help="address under which Home Assistant reaches this server, to serve "
        "a drawing as the vehicle picture (e.g. http://localhost:8099)",
    )
    args = parser.parse_args()
    Handler.garage = Garage(args.limit, args.delay, args.key_days, args.render_base)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Mock MyŠkoda Public API on http://{args.host}:{args.port}", flush=True)
    print("Vehicles:", ", ".join(Handler.garage.vehicles), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
