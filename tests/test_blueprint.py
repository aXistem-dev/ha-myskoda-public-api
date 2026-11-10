"""Tests of the parking alert blueprint."""

from __future__ import annotations

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

from .conftest import load_fixture, setup_integration

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
