"""Tests of the parking alert blueprint."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.automation.config import AUTOMATION_BLUEPRINT_SCHEMA
from homeassistant.components.blueprint.models import Blueprint, BlueprintInputs
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util.yaml import load_yaml_dict
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from .conftest import load_fixture, mock_vehicle, setup_integration

BLUEPRINT = (
    Path(__file__).parent.parent
    / "blueprints"
    / "automation"
    / "skoda_api"
    / "parked_unsecured.yaml"
)


def _automation(**inputs: Any) -> dict[str, Any]:
    """Return the automation the blueprint makes from the given inputs."""
    blueprint = Blueprint(
        load_yaml_dict(BLUEPRINT),
        expected_domain="automation",
        schema=AUTOMATION_BLUEPRINT_SCHEMA,
    )
    assert blueprint.validate() is None
    config = {
        "id": "parked_unsecured",
        "alias": "Parked unsecured",
        "use_blueprint": {
            "path": "skoda_api/parked_unsecured.yaml",
            "input": {
                "vehicle_sensor": "binary_sensor.enyaq_parked_unsecured",
                "notify_action": "notify.phone",
                **inputs,
            },
        },
    }
    instance = BlueprintInputs(blueprint, config)
    instance.validate()
    return instance.async_substitute()


@pytest.mark.parametrize("critical", [False, True])
async def test_parked_unsecured_blueprint(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    critical: bool,
) -> None:
    """The blueprint notifies once the car has stayed unsecured for the delay."""
    notifications = async_mock_service(hass, "notify", "phone")
    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(
        hass, "automation", {"automation": [_automation(critical=critical)]}
    )
    payload = load_fixture("enyaq")
    payload["vehicle"]["status"]["overall"]["locked"] = "NO"
    payload["vehicle"]["status"]["detail"]["trunk"] = "OPEN"
    await setup_integration(hass, config_entry, aioclient_mock, payload)
    assert hass.states.get("binary_sensor.enyaq_parked_unsecured").state == "on"

    freezer.tick(timedelta(minutes=4))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert notifications == []

    # Before notifying it fetches the latest status; a newer report counts.
    mock_vehicle(aioclient_mock, _newer(payload))
    freezer.tick(timedelta(minutes=1, seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    [call] = notifications
    assert call.data["title"] == "Enyaq is not secured"
    assert call.data["message"] == (
        "Enyaq is parked and not secured: the trunk is open, it is unlocked."
    )
    if critical:
        assert call.data["data"]["push"] == {"interruption-level": "critical"}
    else:
        assert "data" not in call.data


async def _settle() -> None:
    """Let the automation run until it waits; it may be in a delay."""
    for _ in range(50):
        await asyncio.sleep(0)


def _newer(payload: dict[str, Any], **detail: str) -> dict[str, Any]:
    """Return the payload as reported a few minutes later."""
    newer = deepcopy(payload)
    status = newer["vehicle"]["status"]
    status["carCapturedTimestamp"] = "2099-01-01T00:00:00Z"
    status["detail"].update(detail)
    return newer


async def _unsecured(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> tuple[list, dict[str, Any]]:
    notifications = async_mock_service(hass, "notify", "phone")
    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(
        hass, "automation", {"automation": [_automation()]}
    )
    payload = load_fixture("enyaq")
    payload["vehicle"]["status"]["detail"]["trunk"] = "OPEN"
    # Not charging, so no poll of its own comes before the notification.
    payload["vehicle"]["charging"]["status"]["state"] = "READY_FOR_CHARGING"
    await setup_integration(hass, config_entry, aioclient_mock, payload)
    return notifications, payload


async def test_blueprint_quiet_when_the_newer_report_is_secured(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A car that reports its closed boot late gets no notification."""
    notifications, payload = await _unsecured(hass, config_entry, aioclient_mock)
    mock_vehicle(aioclient_mock, _newer(payload, trunk="CLOSED"))
    freezer.tick(timedelta(minutes=5, seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.enyaq_parked_unsecured").state == "off"
    assert notifications == []


async def test_blueprint_notifies_when_no_newer_report_comes(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Without a newer report it asks a few times, then notifies anyway."""
    notifications, _ = await _unsecured(hass, config_entry, aioclient_mock)
    freezer.tick(timedelta(minutes=5, seconds=1))
    async_fire_time_changed(hass)
    await _settle()
    assert notifications == []
    for _ in range(4):
        freezer.tick(timedelta(minutes=2, seconds=1))
        async_fire_time_changed(hass)
        await _settle()
    [call] = notifications
    assert call.data["message"] == "Enyaq is parked and not secured: the trunk is open."
