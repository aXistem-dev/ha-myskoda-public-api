"""Tests of the API client."""

from __future__ import annotations

from datetime import UTC, datetime

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.skoda_api.api import (
    SkodaApiAuthError,
    SkodaApiClient,
    SkodaApiConnectionError,
    SkodaApiError,
    SkodaApiForbiddenError,
    SkodaApiNotFoundError,
    SkodaApiRateLimitError,
    SkodaApiServerError,
    SkodaApiUnsupportedError,
    _parse_datetime,
)

from .conftest import (
    API_KEY,
    HEADERS,
    VEHICLE_URL,
    VIN,
    calls,
    load_fixture,
    mock_command,
    mock_vehicle,
)

PROBLEMS = "https://public.api.connect.skoda-auto.cz/problems"


def _client(hass: HomeAssistant) -> SkodaApiClient:
    return SkodaApiClient(async_get_clientsession(hass), API_KEY)


async def test_get_vehicle_reads_data_and_headers(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The response body is returned and the quota headers are kept."""
    mock_vehicle(aioclient_mock)
    client = _client(hass)

    payload = await client.get_vehicle(VIN)

    assert payload["vehicle"]["name"] == "Enyaq"
    assert client.key_expires_at == datetime(2099, 1, 1, tzinfo=UTC)
    assert client.rate_limit is not None
    assert client.rate_limit.limit == 20
    assert client.rate_limit.remaining == 17
    assert client.rate_limit.reset_at > datetime.now(UTC)
    assert aioclient_mock.mock_calls[0][3]["X-API-Key"] == API_KEY


async def test_get_vehicle_include(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The selected parts are sent as a comma-separated list."""
    mock_vehicle(aioclient_mock)

    await _client(hass).get_vehicle(VIN, include=["info", "charging"])

    assert aioclient_mock.mock_calls[0][1].query["include"] == "info,charging"


async def test_get_vehicle_without_vehicle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A body without a vehicle is an error, not an empty car."""
    mock_vehicle(aioclient_mock, {"errors": []})

    with pytest.raises(SkodaApiError):
        await _client(hass).get_vehicle(VIN)


@pytest.mark.parametrize(
    ("status", "problem", "expected"),
    [
        (401, "api-key-expired", SkodaApiAuthError),
        (401, None, SkodaApiAuthError),
        (403, "api-key-not-authorized", SkodaApiAuthError),
        (403, None, SkodaApiAuthError),
        (403, "operation-not-authorized", SkodaApiForbiddenError),
        (404, None, SkodaApiNotFoundError),
        (422, "operation-not-supported", SkodaApiUnsupportedError),
        (422, "operation-disabled", SkodaApiUnsupportedError),
        (429, "rate-limit-exceeded", SkodaApiRateLimitError),
        (500, None, SkodaApiServerError),
        (504, None, SkodaApiServerError),
        (400, None, SkodaApiError),
    ],
)
async def test_errors(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    status: int,
    problem: str | None,
    expected: type[SkodaApiError],
) -> None:
    """Every documented failure maps onto its own error."""
    body = {
        "type": f"{PROBLEMS}/{problem}" if problem else "about:blank",
        "title": "Problem",
        "detail": "What went wrong",
    }
    aioclient_mock.get(VEHICLE_URL, status=status, json=body)

    with pytest.raises(expected) as raised:
        await _client(hass).get_vehicle(VIN)

    assert type(raised.value) is expected
    assert raised.value.status == status
    assert raised.value.problem == problem
    assert raised.value.detail == "What went wrong"


async def test_rate_limit_details(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A refusal tells how long to wait and who refused."""
    aioclient_mock.post(
        f"{VEHICLE_URL}/charging/start",
        status=429,
        json={"type": f"{PROBLEMS}/vehicle-not-accepting-requests"},
        headers={"Retry-After": "120", "RateLimit-Remaining": "0"},
    )
    client = _client(hass)

    with pytest.raises(SkodaApiRateLimitError) as raised:
        await client.start_charging(VIN)

    assert raised.value.retry_after == 120
    assert raised.value.vehicle_declined
    assert client.rate_limit is not None
    assert client.rate_limit.remaining == 0


async def test_error_without_body(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """An error without a problem document still maps by its status."""
    aioclient_mock.get(VEHICLE_URL, status=503, text="unavailable")

    with pytest.raises(SkodaApiServerError):
        await _client(hass).get_vehicle(VIN)


async def test_timeout(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """No answer in time is a connection error."""
    aioclient_mock.get(VEHICLE_URL, exc=TimeoutError())

    with pytest.raises(SkodaApiConnectionError):
        await _client(hass).get_vehicle(VIN)


async def test_commands(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Each command goes to its endpoint with the documented body."""
    client = _client(hass)
    for method, path in (
        ("post", "charging/start"),
        ("post", "charging/stop"),
        ("put", "charging/limit"),
        ("put", "charging/mode"),
        ("put", "charging-profiles/1"),
        ("post", "air-conditioning/start"),
        ("post", "air-conditioning/stop"),
        ("post", "auxiliary-heating/start"),
        ("post", "auxiliary-heating/stop"),
        ("post", "active-ventilation/start"),
        ("post", "active-ventilation/stop"),
    ):
        mock_command(aioclient_mock, method, path)
    profile = load_fixture("enyaq")["vehicle"]["chargingProfiles"]["profiles"][0]

    await client.start_charging(VIN)
    await client.stop_charging(VIN)
    await client.set_charging_limit(VIN, 90)
    await client.set_charge_mode(VIN, "TIMER")
    await client.update_charging_profile(VIN, profile)
    await client.start_air_conditioning(VIN)
    await client.start_air_conditioning(
        VIN, temperature=21.5, without_external_power=False
    )
    await client.stop_air_conditioning(VIN)
    await client.start_auxiliary_heating(VIN, spin="1234")
    await client.start_auxiliary_heating(
        VIN, spin="1234", duration_seconds=600, start_mode="VENTILATION", temperature=20
    )
    await client.stop_auxiliary_heating(VIN)
    await client.start_active_ventilation(VIN)
    await client.stop_active_ventilation(VIN)

    assert calls(aioclient_mock, "post", "charging/start") == [None]
    assert calls(aioclient_mock, "post", "charging/stop") == [None]
    assert calls(aioclient_mock, "put", "charging/limit") == [
        {"targetStateOfChargeInPercent": 90}
    ]
    assert calls(aioclient_mock, "put", "charging/mode") == [{"chargeMode": "TIMER"}]
    assert calls(aioclient_mock, "put", "charging-profiles/1") == [profile]
    assert calls(aioclient_mock, "post", "air-conditioning/start") == [
        {},
        {
            "targetTemperature": {"value": 21.5, "unit": "CELSIUS"},
            "airConditioningWithoutExternalPower": False,
        },
    ]
    assert calls(aioclient_mock, "post", "auxiliary-heating/start") == [
        {"spin": "1234"},
        {
            "spin": "1234",
            "durationInSeconds": 600,
            "startMode": "VENTILATION",
            "targetTemperature": {"value": 20, "unit": "CELSIUS"},
        },
    ]
    assert len(calls(aioclient_mock, "post", "active-ventilation/start")) == 1
    assert len(calls(aioclient_mock, "post", "active-ventilation/stop")) == 1
    assert client.rate_limit is not None
    assert client.rate_limit.remaining == int(HEADERS["RateLimit-Remaining"])


@pytest.mark.parametrize(
    ("headers", "seconds"),
    [
        ({"RateLimit-Remaining": "0", "RateLimit-Reset": "900"}, 900),
        # A moment in time instead of a number of seconds.
        ({"RateLimit-Remaining": "0", "RateLimit-Reset": "EPOCH+600"}, 600),
        ({"RateLimit-Remaining": "0", "RateLimit-Reset": "EPOCH_MS+600"}, 600),
        # Nothing usable: the wait the API asks for, else one window.
        ({"RateLimit-Remaining": "0", "Retry-After": "120"}, 120),
        ({"RateLimit-Remaining": "0"}, 3600),
        ({"RateLimit-Remaining": "0", "RateLimit-Reset": "99999"}, 3600),
        ({"RateLimit-Remaining": "0", "RateLimit-Reset": "-5"}, 3600),
        # A moment already past: the quota has refilled.
        ({"RateLimit-Remaining": "0", "RateLimit-Reset": "EPOCH-30"}, 0),
    ],
)
async def test_rate_limit_reset(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    headers: dict[str, str],
    seconds: int,
) -> None:
    """The quota always gets a reset time within the hour."""
    now = datetime.now(UTC)
    reset = headers.get("RateLimit-Reset", "")
    if reset.startswith("EPOCH"):
        milliseconds = reset.startswith("EPOCH_MS")
        offset = int(reset.removeprefix("EPOCH_MS" if milliseconds else "EPOCH"))
        value = (now.timestamp() + offset) * (1000 if milliseconds else 1)
        headers = {**headers, "RateLimit-Reset": str(int(value))}
    mock_vehicle(aioclient_mock, headers=headers)
    client = _client(hass)

    await client.get_vehicle(VIN)

    assert client.rate_limit is not None
    wait = (client.rate_limit.reset_at - now).total_seconds()
    assert abs(wait - seconds) < 5


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-12-31T23:59:59Z", datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC)),
        ("2026-12-31T23:59:59+00:00", datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC)),
        ("2026-12-31T23:59:59", datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC)),
        ("1798761599", datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC)),
        ("1798761599000", datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC)),
        (
            "Thu, 31 Dec 2026 23:59:59 GMT",
            datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC),
        ),
        ("soon", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_datetime(value: str | None, expected: datetime | None) -> None:
    """The expiry header is read in whatever common notation it comes."""
    assert _parse_datetime(value) == expected


async def test_error_is_logged_with_trace_id(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A refused request is logged with its trace id, without the full VIN."""
    aioclient_mock.get(
        VEHICLE_URL,
        status=500,
        json={"type": "about:blank", "detail": "Internal error"},
        headers={"traceid": "abc123"},
    )
    client = _client(hass)

    with pytest.raises(SkodaApiServerError) as raised:
        await client.get_vehicle(VIN)

    assert raised.value.trace_id == "abc123"
    assert "trace id abc123" in raised.value.detail
    assert "trace id abc123" in caplog.text
    assert VIN not in caplog.text
    assert VIN[-4:] in caplog.text
