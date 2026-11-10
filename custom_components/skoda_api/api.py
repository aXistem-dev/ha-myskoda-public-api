"""Client for the MyŠkoda Public API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
import logging
import re
from typing import Any

from aiohttp import ClientError, ClientResponse, ClientSession, ClientTimeout

from .const import API_BASE_URL, REQUEST_TIMEOUT

_LOGGER = logging.getLogger(__name__)

# The quota is counted per hour.
RATE_LIMIT_WINDOW = 3600

PROBLEM_KEY_EXPIRED = "api-key-expired"
PROBLEM_KEY_NOT_AUTHORIZED = "api-key-not-authorized"
PROBLEM_OPERATION_NOT_AUTHORIZED = "operation-not-authorized"
PROBLEM_OPERATION_NOT_SUPPORTED = "operation-not-supported"
PROBLEM_OPERATION_DISABLED = "operation-disabled"
PROBLEM_RATE_LIMIT = "rate-limit-exceeded"
PROBLEM_VEHICLE_BUSY = "vehicle-not-accepting-requests"


class SkodaApiError(Exception):
    """An error returned by the API or raised while talking to it."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        problem: str | None = None,
        detail: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        """Store the HTTP status, problem type and trace id of the response."""
        super().__init__(message)
        self.status = status
        self.problem = problem
        self.detail = detail
        self.trace_id = trace_id


class SkodaApiConnectionError(SkodaApiError):
    """The API could not be reached, or it did not answer in time."""


class SkodaApiAuthError(SkodaApiError):
    """The API key is invalid, expired, or does not cover the vehicle."""


class SkodaApiForbiddenError(SkodaApiError):
    """The vehicle refused the operation for the owner of the API key."""


class SkodaApiNotFoundError(SkodaApiError):
    """The vehicle, or the charging profile, is unknown."""


class SkodaApiUnsupportedError(SkodaApiError):
    """The vehicle lacks the capability, or the capability is disabled."""


class SkodaApiRateLimitError(SkodaApiError):
    """Too many requests, or the vehicle declined the operation for now."""

    def __init__(self, message: str, *, retry_after: int | None, **kwargs: Any) -> None:
        """Store how long to wait before the next request."""
        super().__init__(message, **kwargs)
        self.retry_after = retry_after

    @property
    def vehicle_declined(self) -> bool:
        """Return True when the vehicle, not the quota, caused the refusal."""
        return self.problem == PROBLEM_VEHICLE_BUSY


class SkodaApiServerError(SkodaApiError):
    """The API failed, or the vehicle did not respond in time."""


@dataclass(frozen=True, slots=True)
class RateLimit:
    """The request quota as reported by the API."""

    limit: int | None
    remaining: int | None
    reset_at: datetime | None

    def refilled(self, now: datetime) -> bool:
        """Return True once the reported reset time has passed."""
        return self.reset_at is not None and self.reset_at <= now

    def left(self, now: datetime) -> int | None:
        """Return the requests left now; unknown after a refill without a limit."""
        if self.refilled(now):
            return self.limit
        return self.remaining


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse a timestamp header: ISO 8601, epoch seconds or an HTTP date."""
    if not value:
        return None
    value = value.strip()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        parsed = None
    if parsed is None:
        try:
            epoch = float(value)
        except ValueError:
            pass
        else:
            # Millisecond epochs are far beyond any plausible second epoch.
            if epoch > 1e11:
                epoch /= 1000
            parsed = datetime.fromtimestamp(epoch, UTC)
    if parsed is None:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _parse_int(value: str | None) -> int | None:
    """Parse an integer header, tolerating decimals and junk."""
    if value is None:
        return None
    try:
        return int(float(value.strip()))
    except ValueError:
        return None


def _problem_slug(problem_type: Any) -> str | None:
    """Return the last path segment of a problem type URI."""
    if not isinstance(problem_type, str) or problem_type in ("", "about:blank"):
        return None
    return problem_type.rstrip("/").rsplit("/", 1)[-1]


class SkodaApiClient:
    """Talk to the MyŠkoda Public API on behalf of one API key."""

    def __init__(
        self,
        session: ClientSession,
        api_key: str,
        base_url: str = API_BASE_URL,
    ) -> None:
        """Create a client; the session stays owned by the caller."""
        self._session = session
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self.key_expires_at: datetime | None = None
        self.rate_limit: RateLimit | None = None

    # ------------------------------------------------------------------ reads

    async def get_vehicle(
        self, vin: str, include: list[str] | None = None
    ) -> dict[str, Any]:
        """Return the vehicle and its current state as sent by the API."""
        params = {"include": ",".join(include)} if include else None
        payload = await self._request("GET", self._path(vin), params=params)
        if not isinstance(payload, dict) or not isinstance(
            payload.get("vehicle"), dict
        ):
            raise SkodaApiError("The API returned no vehicle data")
        return payload

    # --------------------------------------------------------------- commands

    async def start_charging(self, vin: str) -> None:
        """Start charging."""
        await self._request("POST", self._path(vin, "charging/start"))

    async def stop_charging(self, vin: str) -> None:
        """Stop charging."""
        await self._request("POST", self._path(vin, "charging/stop"))

    async def set_charging_limit(self, vin: str, percent: int) -> None:
        """Set the target state of charge."""
        await self._request(
            "PUT",
            self._path(vin, "charging/limit"),
            json={"targetStateOfChargeInPercent": int(percent)},
        )

    async def set_charge_mode(self, vin: str, mode: str) -> None:
        """Change the charge mode (API value, e.g. MANUAL)."""
        await self._request(
            "PUT", self._path(vin, "charging/mode"), json={"chargeMode": mode}
        )

    async def update_charging_profile(self, vin: str, profile: dict[str, Any]) -> None:
        """Replace a charging profile; the vehicle applies it as a whole."""
        await self._request(
            "PUT",
            self._path(vin, f"charging-profiles/{profile['id']}"),
            json=profile,
        )

    async def start_air_conditioning(
        self,
        vin: str,
        *,
        temperature: float | None = None,
        without_external_power: bool | None = None,
    ) -> None:
        """Start the air conditioning, optionally towards a temperature."""
        body: dict[str, Any] = {}
        if temperature is not None:
            body["targetTemperature"] = {"value": temperature, "unit": "CELSIUS"}
        if without_external_power is not None:
            body["airConditioningWithoutExternalPower"] = without_external_power
        await self._request(
            "POST", self._path(vin, "air-conditioning/start"), json=body
        )

    async def stop_air_conditioning(self, vin: str) -> None:
        """Stop the air conditioning."""
        await self._request("POST", self._path(vin, "air-conditioning/stop"))

    async def start_auxiliary_heating(
        self,
        vin: str,
        *,
        spin: str,
        duration_seconds: int | None = None,
        start_mode: str | None = None,
        temperature: float | None = None,
    ) -> None:
        """Start the auxiliary heater; needs the S-PIN of the account."""
        body: dict[str, Any] = {"spin": spin}
        if duration_seconds is not None:
            body["durationInSeconds"] = int(duration_seconds)
        if start_mode is not None:
            body["startMode"] = start_mode
        if temperature is not None:
            body["targetTemperature"] = {"value": temperature, "unit": "CELSIUS"}
        await self._request(
            "POST", self._path(vin, "auxiliary-heating/start"), json=body
        )

    async def stop_auxiliary_heating(self, vin: str) -> None:
        """Stop the auxiliary heater."""
        await self._request("POST", self._path(vin, "auxiliary-heating/stop"))

    async def start_active_ventilation(self, vin: str) -> None:
        """Start the active ventilation."""
        await self._request("POST", self._path(vin, "active-ventilation/start"))

    async def stop_active_ventilation(self, vin: str) -> None:
        """Stop the active ventilation."""
        await self._request("POST", self._path(vin, "active-ventilation/stop"))

    # --------------------------------------------------------------- internals

    @staticmethod
    def _path(vin: str, suffix: str | None = None) -> str:
        path = f"/api/v1/vehicles/{vin}"
        return f"{path}/{suffix}" if suffix else path

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> Any:
        headers = {"X-API-Key": self._api_key, "Accept": "application/json"}
        try:
            response = await self._session.request(
                method,
                f"{self._base_url}{path}",
                headers=headers,
                json=json,
                params=params,
                timeout=ClientTimeout(total=REQUEST_TIMEOUT),
            )
            try:
                self._read_headers(response)
                if response.status >= 400:
                    error = await self._error(response)
                    # Refusals the integration handles are routine; others are not.
                    _LOGGER.log(
                        logging.WARNING
                        if response.status >= 500 or response.status in (400, 409)
                        else logging.DEBUG,
                        "%s %s refused: HTTP %s, problem %s, trace id %s: %s",
                        method,
                        _shorten_vin(path),
                        error.status,
                        error.problem or "-",
                        error.trace_id or "-",
                        _shorten_vin((error.detail or "")[:300]),
                    )
                    raise error
                if response.status == 204 or method != "GET":
                    return None
                try:
                    return await response.json(content_type=None)
                except ValueError as err:
                    raise SkodaApiError(
                        "The API returned an unreadable response",
                        status=response.status,
                    ) from err
            finally:
                response.release()
        except TimeoutError as err:
            raise SkodaApiConnectionError("The API did not answer in time") from err
        except ClientError as err:
            raise SkodaApiConnectionError(f"The API is unreachable: {err}") from err

    def _read_headers(self, response: ClientResponse) -> None:
        headers = response.headers
        if expires := _parse_datetime(headers.get("X-API-Key-Expires-At")):
            self.key_expires_at = expires
        remaining = _parse_int(headers.get("RateLimit-Remaining"))
        limit = _parse_int(headers.get("RateLimit-Limit"))
        reset = _parse_int(headers.get("RateLimit-Reset"))
        if remaining is None and limit is None and reset is None:
            return
        now = datetime.now(UTC)
        if reset is not None and reset > 1_000_000_000:
            # An epoch time, not seconds; one in the past means refilled.
            reset = max(
                0,
                round(
                    reset / (1000 if reset > 100_000_000_000 else 1) - now.timestamp()
                ),
            )
        if reset is None or not 0 <= reset <= RATE_LIMIT_WINDOW:
            # No usable reset time: use Retry-After, else a full window.
            reset = _parse_int(headers.get("Retry-After")) or RATE_LIMIT_WINDOW
            reset = min(max(reset, 0), RATE_LIMIT_WINDOW)
        self.rate_limit = RateLimit(
            limit=limit,
            remaining=remaining,
            reset_at=now + timedelta(seconds=reset),
        )

    @staticmethod
    async def _error(response: ClientResponse) -> SkodaApiError:
        status = response.status
        problem: str | None = None
        detail: str | None = None
        try:
            body = await response.json(content_type=None)
        except (TimeoutError, ValueError, ClientError):
            body = None
        if isinstance(body, dict):
            problem = _problem_slug(body.get("type"))
            detail = body.get("detail") or body.get("title")
        # Škoda support can find a request by this id.
        trace_id = response.headers.get("traceid") or None
        message = f"HTTP {status}" + (f": {detail}" if detail else "")
        if status >= 500 and trace_id:
            detail = f"{detail or message} (trace id {trace_id})"
        kwargs: dict[str, Any] = {
            "status": status,
            "problem": problem,
            "detail": detail,
            "trace_id": trace_id,
        }

        if status == 401 or problem in (
            PROBLEM_KEY_EXPIRED,
            PROBLEM_KEY_NOT_AUTHORIZED,
        ):
            return SkodaApiAuthError(message, **kwargs)
        if status == 403:
            # A 403 without a problem type is treated as a refused key.
            if problem == PROBLEM_OPERATION_NOT_AUTHORIZED:
                return SkodaApiForbiddenError(message, **kwargs)
            return SkodaApiAuthError(message, **kwargs)
        if status == 404:
            return SkodaApiNotFoundError(message, **kwargs)
        if status == 422:
            return SkodaApiUnsupportedError(message, **kwargs)
        if status == 429:
            return SkodaApiRateLimitError(
                message,
                retry_after=_parse_int(response.headers.get("Retry-After")),
                **kwargs,
            )
        if status >= 500:
            return SkodaApiServerError(message, **kwargs)
        return SkodaApiError(message, **kwargs)


def _shorten_vin(path: str) -> str:
    """Hide all but the last four characters of any VIN in a text."""
    return re.sub(r"\b[A-HJ-NPR-Z0-9]{13}([A-HJ-NPR-Z0-9]{4})\b", r"…\1", path)
