"""Tests of the config flow and the options."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.skoda_api.const import (
    API_BASE_URL,
    CONF_ACTIVE_POLL_INTERVAL,
    CONF_AUTO_WAKE_MINUTES,
    CONF_BASE_URL,
    CONF_FAST_POLL_WHEN_PLUGGED,
    CONF_POLL_INTERVAL,
    CONF_READONLY,
    CONF_SPIN,
    CONF_VIN,
    DOMAIN,
)

from .conftest import (
    API_KEY,
    VEHICLE_URL,
    VIN,
    calls,
    mock_command,
    mock_vehicle,
    setup_integration,
)

PROBLEMS = "https://public.api.connect.skoda-auto.cz/problems"
INFO = {"vehicle": {"vin": VIN, "name": "Enyaq", "licensePlate": "1MB 1234"}}


async def test_user_flow(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A VIN and a key that work create the vehicle, named as in the app."""
    mock_vehicle(aioclient_mock, INFO)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_VIN: f" {VIN.lower()} ",
            CONF_API_KEY: f" {API_KEY} ",
            "advanced": {CONF_BASE_URL: API_BASE_URL},
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Enyaq"
    assert result["data"] == {CONF_VIN: VIN, CONF_API_KEY: API_KEY}
    assert result["result"].unique_id == VIN
    # Checking the key asks for the basic details only.
    assert aioclient_mock.mock_calls[0][1].query["include"] == "info"


async def test_user_flow_without_name(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A vehicle without a name is titled by its VIN."""
    mock_vehicle(aioclient_mock, {"vehicle": {"vin": VIN}})
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={CONF_VIN: VIN, CONF_API_KEY: API_KEY},
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == VIN


async def test_user_flow_test_server(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Another API address, given under Advanced, is used and stored."""
    aioclient_mock.get(f"http://localhost:8099/api/v1/vehicles/{VIN}", json=INFO)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_VIN: VIN,
            CONF_API_KEY: API_KEY,
            "advanced": {CONF_BASE_URL: "http://localhost:8099/"},
        },
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_BASE_URL] == "http://localhost:8099"


@pytest.mark.parametrize(
    ("status", "problem", "error"),
    [
        (401, "api-key-expired", "invalid_auth"),
        (401, None, "invalid_auth"),
        (403, "api-key-not-authorized", "key_not_authorized"),
        (404, None, "vehicle_not_found"),
        (429, "rate-limit-exceeded", "rate_limited"),
        (503, None, "cannot_connect"),
        (400, None, "unknown"),
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    status: int,
    problem: str | None,
    error: str,
) -> None:
    """Each refusal is explained, and a correction goes through."""
    aioclient_mock.get(
        VEHICLE_URL,
        status=status,
        json={"type": f"{PROBLEMS}/{problem}" if problem else "about:blank"},
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={CONF_VIN: VIN, CONF_API_KEY: API_KEY},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    mock_vehicle(aioclient_mock, INFO)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_VIN: VIN,
            CONF_API_KEY: API_KEY,
            "advanced": {CONF_BASE_URL: API_BASE_URL},
        },
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_unreachable(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """No answer is reported as a connection problem."""
    aioclient_mock.get(VEHICLE_URL, exc=TimeoutError())
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={CONF_VIN: VIN, CONF_API_KEY: API_KEY},
    )
    assert result["errors"] == {"base": "cannot_connect"}


@pytest.mark.parametrize("vin", ["TMB123", "TMBJB9NY5RF99999O", "TMBJB9NY5RF9999999"])
async def test_user_flow_invalid_vin(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, vin: str
) -> None:
    """A malformed VIN is caught without spending a request."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={CONF_VIN: vin, CONF_API_KEY: API_KEY},
    )
    assert result["errors"] == {CONF_VIN: "invalid_vin"}
    assert aioclient_mock.mock_calls == []


async def test_user_flow_duplicate(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A vehicle is set up once."""
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={CONF_VIN: VIN, CONF_API_KEY: "another-key"},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.parametrize("step", ["reauth", "reconfigure"])
async def test_new_key(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    step: str,
) -> None:
    """A new key is checked against the same vehicle and then stored."""
    await setup_integration(hass, config_entry, aioclient_mock)
    if step == "reauth":
        result = await config_entry.start_reauth_flow(hass)
        step_id, reason = "reauth_confirm", "reauth_successful"
    else:
        result = await config_entry.start_reconfigure_flow(hass)
        step_id, reason = "reconfigure", "reconfigure_successful"
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == step_id
    assert result["description_placeholders"]["name"] == "Enyaq"

    aioclient_mock.clear_requests()
    aioclient_mock.get(
        VEHICLE_URL, status=401, json={"type": f"{PROBLEMS}/api-key-expired"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "expired-key"}
    )
    assert result["errors"] == {"base": "invalid_auth"}
    assert config_entry.data[CONF_API_KEY] == API_KEY

    mock_vehicle(aioclient_mock)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "new-key"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == reason
    assert config_entry.data == {CONF_VIN: VIN, CONF_API_KEY: "new-key"}
    assert aioclient_mock.mock_calls[-1][3]["X-API-Key"] == "new-key"


async def test_options(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Options are validated, stored, and applied by a reload."""
    await setup_integration(hass, config_entry, aioclient_mock)
    mock_command(aioclient_mock, "put", "charging/mode")
    # The sample vehicle charges: it is polled at the shorter interval.
    assert config_entry.runtime_data.update_interval.total_seconds() == 300

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    user_input: dict[str, Any] = {
        CONF_POLL_INTERVAL: 15,
        CONF_ACTIVE_POLL_INTERVAL: 7,
        CONF_FAST_POLL_WHEN_PLUGGED: True,
        CONF_AUTO_WAKE_MINUTES: 30,
        CONF_SPIN: "12",
        CONF_READONLY: False,
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input
    )
    assert result["errors"] == {CONF_SPIN: "invalid_spin"}

    # An automatic wake is off (0) or at least ten minutes.
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**user_input, CONF_SPIN: "1234", CONF_AUTO_WAKE_MINUTES: 5}
    )
    assert result["errors"] == {CONF_AUTO_WAKE_MINUTES: "invalid_auto_wake"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**user_input, CONF_SPIN: "1234"}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {
        CONF_POLL_INTERVAL: 15,
        CONF_ACTIVE_POLL_INTERVAL: 7,
        CONF_FAST_POLL_WHEN_PLUGGED: True,
        CONF_AUTO_WAKE_MINUTES: 30,
        CONF_SPIN: "1234",
        CONF_READONLY: False,
    }
    assert config_entry.runtime_data.update_interval.total_seconds() == 420
    assert config_entry.runtime_data.spin == "1234"
    # The sample vehicle reported long ago while charging: it is woken.
    assert calls(aioclient_mock, "put", "charging/mode") == [{"chargeMode": "MANUAL"}]

    # Leaving the S-PIN empty removes it; read only drops the controls.
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_POLL_INTERVAL: 15, CONF_READONLY: True}
    )
    await hass.async_block_till_done()
    # Fields left out keep what was stored.
    assert config_entry.options == {
        CONF_POLL_INTERVAL: 15,
        CONF_ACTIVE_POLL_INTERVAL: 7,
        CONF_FAST_POLL_WHEN_PLUGGED: True,
        CONF_AUTO_WAKE_MINUTES: 30,
        CONF_READONLY: True,
    }
    assert config_entry.runtime_data.spin is None
    # The controls are gone, not left behind as unavailable.
    assert hass.states.get("switch.enyaq_charging") is None
    assert hass.states.get("number.enyaq_home_charge_limit") is None
    assert hass.states.get("sensor.enyaq_charge_limit").state == "80"
    assert hass.states.get("sensor.enyaq_charge_mode").state == "manual"
    assert hass.states.get("sensor.enyaq_target_temperature").state == "22"
