"""Tests of the diagnostics."""

from __future__ import annotations

import json

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.skoda_api.const import CONF_SPIN
from custom_components.skoda_api.diagnostics import async_get_config_entry_diagnostics

from .conftest import API_KEY, VIN, setup_integration


async def test_diagnostics_hide_the_vehicle(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Nothing that identifies the car or opens it leaves the system."""
    await setup_integration(hass, config_entry, aioclient_mock)
    hass.config_entries.async_update_entry(config_entry, options={CONF_SPIN: "1234"})

    diagnostics = await async_get_config_entry_diagnostics(hass, config_entry)

    text = json.dumps(diagnostics)
    for secret in (
        VIN,
        API_KEY,
        "1MB 1234",
        "Example Street",
        "50.0755",
        "14.4378",
        "enyaq.png",
        '"1234"',
    ):
        assert secret not in text, secret
    assert diagnostics["vehicle"]["charging"]["status"]["battery"] == {
        "remainingCruisingRangeInMeters": 312000,
        "stateOfChargeInPercent": 64,
    }
    # Names the owner chose are hidden; names the API gives are kept.
    assert diagnostics["vehicle"]["name"] == "**REDACTED**"
    profiles = diagnostics["vehicle"]["chargingProfiles"]
    assert {profile["name"] for profile in profiles["profiles"]} == {"**REDACTED**"}
    assert profiles["currentVehiclePositionProfile"]["name"] == "**REDACTED**"
    assert {"name": "startCharging"} in diagnostics["vehicle"]["operations"]
    assert diagnostics["api"]["rate_limit_remaining"] == 17
    assert diagnostics["api"]["key_expires_at"] == "2099-01-01T00:00:00+00:00"
    assert diagnostics["last_update_success"] is True
