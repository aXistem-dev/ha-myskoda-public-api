"""Tests of the controls and the actions."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
import voluptuous as vol

from custom_components.skoda_api.const import (
    CONF_AUTO_WAKE_MINUTES,
    CONF_READONLY,
    CONF_SPIN,
    CONF_VIN,
    DOMAIN,
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
    setup_integration,
)

PROBLEMS = "https://public.api.connect.skoda-auto.cz/problems"


def _state(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    assert state is not None, f"{entity_id} does not exist"
    return state.state


async def _call(
    hass: HomeAssistant, domain: str, service: str, entity_id: str, **data: Any
) -> None:
    await hass.services.async_call(
        domain, service, {"entity_id": entity_id, **data}, blocking=True
    )


async def _advance(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: int
) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def _device_id(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, entry.unique_id), entry.entry_id
    )
    assert device is not None
    return device.id


def _enyaq(**changes: Any) -> dict[str, Any]:
    """Return the sample vehicle as reported at a later moment."""
    payload = load_fixture("enyaq")
    vehicle = payload["vehicle"]
    for section in ("charging", "airConditioning", "chargingProfiles"):
        vehicle[section]["carCapturedTimestamp"] = "2026-06-29T08:05:00Z"
    for path, value in changes.items():
        node = vehicle
        *parents, leaf = path.split("__")
        for key in parents:
            node = node[int(key)] if key.isdigit() else node[key]
        node[leaf] = value
    return payload


async def test_charging_switch_shows_result_until_confirmed(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A stop shows at once and stays until the vehicle reports again."""
    await setup_integration(hass, config_entry, aioclient_mock)
    mock_command(aioclient_mock, "post", "charging/stop")

    await _call(hass, "switch", "turn_off", "switch.enyaq_charging")

    assert calls(aioclient_mock, "post", "charging/stop") == [None]
    assert _state(hass, "switch.enyaq_charging") == "off"
    # The sensor keeps what the vehicle says.
    assert _state(hass, "binary_sensor.enyaq_charging") == "on"

    # 30 s later the data is fetched. The vehicle sent a newer sample, but it
    # still charges: the stop is not confirmed and the switch keeps showing it.
    mock_vehicle(aioclient_mock, _enyaq())
    await _advance(hass, freezer, 31)
    assert len(calls(aioclient_mock, "get")) == 1
    assert _state(hass, "switch.enyaq_charging") == "off"
    assert _state(hass, "binary_sensor.enyaq_charging") == "on"

    # At 120 s the vehicle has reported: its word counts again.
    mock_vehicle(
        aioclient_mock,
        _enyaq(charging__status__state="READY_FOR_CHARGING"),
    )
    await _advance(hass, freezer, 90)
    assert len(calls(aioclient_mock, "get")) == 1
    assert _state(hass, "switch.enyaq_charging") == "off"
    assert _state(hass, "binary_sensor.enyaq_charging") == "off"


async def test_unconfirmed_command_falls_back(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A result the vehicle never confirms does not stick."""
    await setup_integration(hass, config_entry, aioclient_mock)
    mock_command(aioclient_mock, "post", "charging/stop")
    await _call(hass, "switch", "turn_off", "switch.enyaq_charging")
    assert _state(hass, "switch.enyaq_charging") == "off"

    polls = len(calls(aioclient_mock, "get"))
    await _advance(hass, freezer, 31)
    await _advance(hass, freezer, 90)
    assert _state(hass, "switch.enyaq_charging") == "off"

    # At 3 minutes the vehicle's last word counts again; that takes no request.
    await _advance(hass, freezer, 61)
    assert len(calls(aioclient_mock, "get")) == polls + 2
    assert _state(hass, "switch.enyaq_charging") == "on"


async def test_expired_value_does_not_return(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A later command does not bring back a value the vehicle never took."""
    await setup_integration(hass, config_entry, aioclient_mock)
    mock_command(aioclient_mock, "put", "charging/limit")
    mock_command(aioclient_mock, "post", "charging/stop")
    await _call(hass, "number", "set_value", "number.enyaq_charge_limit", value=60)
    assert _state(hass, "number.enyaq_charge_limit") == "60"

    await _advance(hass, freezer, 181)
    assert _state(hass, "number.enyaq_charge_limit") == "80"

    await _call(hass, "switch", "turn_off", "switch.enyaq_charging")
    assert _state(hass, "switch.enyaq_charging") == "off"
    assert _state(hass, "number.enyaq_charge_limit") == "80"


async def test_second_follow_up_is_skipped_once_confirmed(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """No request is spent on a command that is already confirmed."""
    await setup_integration(hass, config_entry, aioclient_mock)
    mock_vehicle(aioclient_mock, _enyaq(charging__status__state="CHARGING"))
    mock_command(aioclient_mock, "post", "charging/start")
    await _call(hass, "switch", "turn_on", "switch.enyaq_charging")

    await _advance(hass, freezer, 31)
    assert len(calls(aioclient_mock, "get")) == 1
    await _advance(hass, freezer, 90)
    assert len(calls(aioclient_mock, "get")) == 1


async def test_charge_limit_and_mode(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """The limit and the mode are sent in the notation of the API."""
    await setup_integration(hass, config_entry, aioclient_mock)
    mock_command(aioclient_mock, "put", "charging/limit")
    mock_command(aioclient_mock, "put", "charging/mode")

    await _call(hass, "number", "set_value", "number.enyaq_charge_limit", value=90)
    await _call(
        hass, "select", "select_option", "select.enyaq_charge_mode", option="timer"
    )

    assert calls(aioclient_mock, "put", "charging/limit") == [
        {"targetStateOfChargeInPercent": 90}
    ]
    assert calls(aioclient_mock, "put", "charging/mode") == [{"chargeMode": "TIMER"}]
    assert _state(hass, "number.enyaq_charge_limit") == "90"
    assert _state(hass, "select.enyaq_charge_mode") == "timer"


async def test_climate(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A temperature chosen while off travels with the next start."""
    await setup_integration(hass, config_entry, aioclient_mock)
    mock_command(aioclient_mock, "post", "air-conditioning/start")
    mock_command(aioclient_mock, "post", "air-conditioning/stop")
    entity_id = "climate.enyaq_air_conditioning"

    await _call(hass, "climate", "set_temperature", entity_id, temperature=20.5)
    assert calls(aioclient_mock, "post", "air-conditioning/start") == []
    assert hass.states.get(entity_id).attributes["temperature"] == 20.5

    await _call(hass, "climate", "turn_on", entity_id)
    assert calls(aioclient_mock, "post", "air-conditioning/start") == [
        {"targetTemperature": {"value": 20.5, "unit": "CELSIUS"}}
    ]
    assert _state(hass, entity_id) == "heat_cool"
    assert hass.states.get(entity_id).attributes["temperature"] == 20.5
    # Started, but what it does is not known until the vehicle reports.
    assert hass.states.get(entity_id).attributes.get("hvac_action") is None

    # While it runs, a new temperature is sent at once.
    await _call(hass, "climate", "set_temperature", entity_id, temperature=23)
    assert calls(aioclient_mock, "post", "air-conditioning/start")[-1] == {
        "targetTemperature": {"value": 23, "unit": "CELSIUS"}
    }

    await _call(hass, "climate", "set_hvac_mode", entity_id, hvac_mode="off")
    assert calls(aioclient_mock, "post", "air-conditioning/stop") == [None]
    assert _state(hass, entity_id) == "off"
    assert hass.states.get(entity_id).attributes["hvac_action"] == "off"


async def test_climate_chosen_temperature_yields_to_the_vehicle(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A temperature chosen while off does not outlive a start elsewhere."""
    await setup_integration(hass, config_entry, aioclient_mock)
    entity_id = "climate.enyaq_air_conditioning"
    await _call(hass, "climate", "set_temperature", entity_id, temperature=24)
    assert hass.states.get(entity_id).attributes["temperature"] == 24

    # Started from the app at 20 degrees.
    mock_vehicle(
        aioclient_mock,
        _enyaq(
            airConditioning__state="HEATING",
            airConditioning__targetTemperature={"value": 20, "unit": "CELSIUS"},
        ),
    )
    mock_command(aioclient_mock, "post", "air-conditioning/start")
    await _advance(hass, freezer, 601)
    state = hass.states.get(entity_id)
    assert state.state == "heat_cool"
    assert state.attributes["temperature"] == 20

    # A new temperature while it runs shows at once.
    await _call(hass, "climate", "set_temperature", entity_id, temperature=26)
    assert hass.states.get(entity_id).attributes["temperature"] == 26
    assert calls(aioclient_mock, "post", "air-conditioning/start") == [
        {"targetTemperature": {"value": 26, "unit": "CELSIUS"}}
    ]


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("HEATING", "on"),
        ("PREHEATING", "on"),
        ("OFF", "off"),
        ("SOMETHING_NEW", "unknown"),
        ("UNKNOWN", "unknown"),
    ],
)
async def test_running_states(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    state: str,
    expected: str,
) -> None:
    """Only a known idle state reads as off; an unnamed one is unknown."""
    vin = "TMBAR7NP9R7999999"
    payload = load_fixture("superb")
    payload["vehicle"]["auxiliaryHeating"]["state"] = state
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=vin, data={CONF_VIN: vin, CONF_API_KEY: API_KEY}
    )
    aioclient_mock.get(VEHICLE_URL.replace(VIN, vin), json=payload)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert _state(hass, "switch.superb_auxiliary_heating") == expected


async def test_climate_actions(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """The running state tells what the air conditioning is doing."""
    payload = load_fixture("enyaq")
    payload["vehicle"]["airConditioning"]["state"] = "HEATING"
    await setup_integration(hass, config_entry, aioclient_mock, payload)

    state = hass.states.get("climate.enyaq_air_conditioning")
    assert state.state == "heat_cool"
    assert state.attributes["hvac_action"] == "heating"


async def test_charging_profile_entities_send_whole_profile(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A changed setting goes out inside the complete profile."""
    await setup_integration(hass, config_entry, aioclient_mock)
    mock_command(aioclient_mock, "put", "charging-profiles/1")
    original = load_fixture("enyaq")["vehicle"]["chargingProfiles"]["profiles"][0]

    await _call(hass, "number", "set_value", "number.enyaq_home_charge_limit", value=90)

    sent = calls(aioclient_mock, "put", "charging-profiles/1")
    assert sent == [
        {
            **original,
            "settings": {**original["settings"], "targetStateOfChargeInPercent": 90},
        }
    ]
    assert _state(hass, "number.enyaq_home_charge_limit") == "90"

    # A second change before the vehicle confirms builds on the first.
    await _call(
        hass, "switch", "turn_on", "switch.enyaq_home_unlock_cable_when_charged"
    )
    await _call(
        hass,
        "select",
        "select_option",
        "select.enyaq_home_charging_current",
        option="reduced",
    )
    await _call(hass, "switch", "turn_off", "switch.enyaq_home_minimum_charge")
    await _call(
        hass, "number", "set_value", "number.enyaq_home_minimum_charge_level", value=30
    )

    last = calls(aioclient_mock, "put", "charging-profiles/1")[-1]
    assert last["settings"] == {
        "maxChargingCurrent": "REDUCED",
        "minBatteryStateOfCharge": {
            "enabled": False,
            "minimumBatteryStateOfChargeInPercent": 30,
        },
        "targetStateOfChargeInPercent": 90,
        "autoUnlockPlugWhenCharged": "PERMANENT",
    }
    assert last["timers"] == original["timers"]
    assert last["preferredChargingTimes"] == original["preferredChargingTimes"]
    assert _state(hass, "switch.enyaq_home_unlock_cable_when_charged") == "on"
    assert _state(hass, "select.enyaq_home_charging_current") == "reduced"
    assert _state(hass, "switch.enyaq_home_minimum_charge") == "off"
    assert _state(hass, "number.enyaq_home_minimum_charge_level") == "30"
    # The other profile is untouched.
    assert _state(hass, "number.enyaq_work_charge_limit") == "100"


async def test_update_charging_profile_action(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """The action changes settings, charging times and timers by id."""
    await setup_integration(hass, config_entry, aioclient_mock)
    mock_command(aioclient_mock, "put", "charging-profiles/1")
    original = load_fixture("enyaq")["vehicle"]["chargingProfiles"]["profiles"][0]

    await hass.services.async_call(
        DOMAIN,
        "update_charging_profile",
        {
            "device_id": _device_id(hass, config_entry),
            "profile": "home",
            "target_state_of_charge": 70,
            "max_charging_current": "Reduced",
            "auto_unlock_plug": True,
            "min_battery_enabled": False,
            "min_battery_state_of_charge": 10,
            "preferred_charging_times": [
                {"id": 2, "enabled": True, "start_time": "13:00", "end_time": "15:30"}
            ],
            "timers": [
                {
                    "id": 2,
                    "enabled": True,
                    "time": "06:45",
                    "type": "recurring",
                    "recurring_on": ["Tuesday", "sunday"],
                }
            ],
        },
        blocking=True,
    )

    assert calls(aioclient_mock, "put", "charging-profiles/1") == [
        {
            "id": 1,
            "name": "Home",
            "settings": {
                "maxChargingCurrent": "REDUCED",
                "minBatteryStateOfCharge": {
                    "enabled": False,
                    "minimumBatteryStateOfChargeInPercent": 10,
                },
                "targetStateOfChargeInPercent": 70,
                "autoUnlockPlugWhenCharged": "PERMANENT",
            },
            "preferredChargingTimes": [
                original["preferredChargingTimes"][0],
                {"id": 2, "enabled": True, "startTime": "13:00", "endTime": "15:30"},
            ],
            "timers": [
                original["timers"][0],
                {
                    "id": 2,
                    "enabled": True,
                    "time": "06:45",
                    "type": "RECURRING",
                    "oneOffDay": "SATURDAY",
                    "recurringOn": ["TUESDAY", "SUNDAY"],
                },
            ],
        }
    ]


@pytest.mark.parametrize(
    ("data", "key"),
    [
        ({"profile": "Cabin", "target_state_of_charge": 70}, "profile_not_found"),
        ({"profile": 1}, "nothing_to_change"),
        (
            {"profile": 1, "timers": [{"id": 9, "enabled": True}]},
            "profile_entry_not_found",
        ),
    ],
)
async def test_update_charging_profile_action_errors(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    data: dict[str, Any],
    key: str,
) -> None:
    """A wrong profile, entry or an empty change is refused before sending."""
    await setup_integration(hass, config_entry, aioclient_mock)

    with pytest.raises(ServiceValidationError) as raised:
        await hass.services.async_call(
            DOMAIN,
            "update_charging_profile",
            {"device_id": _device_id(hass, config_entry), **data},
            blocking=True,
        )

    assert raised.value.translation_key == key
    assert calls(aioclient_mock, "put", "charging-profiles/1") == []


async def test_timers_and_charging_times(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Each timer and charging time can be switched and set on its own."""
    await setup_integration(hass, config_entry, aioclient_mock)
    mock_command(aioclient_mock, "put", "charging-profiles/1")
    original = load_fixture("enyaq")["vehicle"]["chargingProfiles"]["profiles"][0]

    expected = {
        "switch.enyaq_home_timer_1": "on",
        "switch.enyaq_home_timer_2": "off",
        "time.enyaq_home_timer_1_time": "07:30:00",
        "switch.enyaq_home_charging_time_1": "on",
        "switch.enyaq_home_charging_time_2": "off",
        "time.enyaq_home_charging_time_1_start": "22:00:00",
        "time.enyaq_home_charging_time_1_end": "06:00:00",
    }
    assert {entity_id: _state(hass, entity_id) for entity_id in expected} == expected
    timer = hass.states.get("switch.enyaq_home_timer_1")
    assert timer.attributes["type"] == "recurring"
    assert timer.attributes["recurring_on"] == ["monday", "friday"]
    assert timer.attributes["item_id"] == 1
    # A profile without timers has no timer entities.
    assert hass.states.get("switch.enyaq_work_timer_1") is None

    await _call(hass, "switch", "turn_off", "switch.enyaq_home_timer_1")
    await _call(
        hass, "time", "set_value", "time.enyaq_home_timer_2_time", time="06:45:00"
    )
    await _call(hass, "switch", "turn_on", "switch.enyaq_home_charging_time_2")
    await _call(
        hass,
        "time",
        "set_value",
        "time.enyaq_home_charging_time_2_start",
        time="13:00:00",
    )
    await _call(
        hass,
        "time",
        "set_value",
        "time.enyaq_home_charging_time_2_end",
        time="15:30:00",
    )

    last = calls(aioclient_mock, "put", "charging-profiles/1")[-1]
    assert last["timers"] == [
        {**original["timers"][0], "enabled": False},
        {**original["timers"][1], "time": "06:45"},
    ]
    assert last["preferredChargingTimes"] == [
        original["preferredChargingTimes"][0],
        {"id": 2, "enabled": True, "startTime": "13:00", "endTime": "15:30"},
    ]
    assert last["settings"] == original["settings"]
    assert _state(hass, "switch.enyaq_home_timer_1") == "off"
    assert _state(hass, "time.enyaq_home_timer_2_time") == "06:45:00"
    assert _state(hass, "switch.enyaq_home_charging_time_2") == "on"
    assert _state(hass, "time.enyaq_home_charging_time_2_end") == "15:30:00"


async def test_an_action_for_every_operation(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Every operation of the API can be called as an action."""
    payload = load_fixture("enyaq")
    vehicle = payload["vehicle"]
    vehicle["operations"] = [
        {"name": name}
        for name in (
            "startCharging",
            "stopCharging",
            "setChargingLimit",
            "setChargeMode",
            "updateChargingProfile",
            "startAirConditioning",
            "stopAirConditioning",
            "startAuxiliaryHeating",
            "stopAuxiliaryHeating",
            "startActiveVentilation",
            "stopActiveVentilation",
        )
    ]
    vehicle["auxiliaryHeating"] = {"state": "OFF"}
    vehicle["activeVentilation"] = {"state": "OFF"}
    await setup_integration(hass, config_entry, aioclient_mock, payload)
    device_id = _device_id(hass, config_entry)
    expected = {
        "start_charging": ("post", "charging/start", {}, None),
        "stop_charging": ("post", "charging/stop", {}, None),
        "set_charging_limit": (
            "put",
            "charging/limit",
            {"target_state_of_charge": 60},
            {"targetStateOfChargeInPercent": 60},
        ),
        "set_charge_mode": (
            "put",
            "charging/mode",
            {"charge_mode": "Preferred_Charging_Times"},
            {"chargeMode": "PREFERRED_CHARGING_TIMES"},
        ),
        "update_charging_profile": (
            "put",
            "charging-profiles/2",
            {"profile": "Work", "name": "Office"},
            {
                **vehicle["chargingProfiles"]["profiles"][1],
                "name": "Office",
            },
        ),
        "start_air_conditioning": ("post", "air-conditioning/start", {}, {}),
        "stop_air_conditioning": ("post", "air-conditioning/stop", {}, None),
        "start_auxiliary_heating": (
            "post",
            "auxiliary-heating/start",
            {"spin": "1234"},
            {"spin": "1234"},
        ),
        "stop_auxiliary_heating": ("post", "auxiliary-heating/stop", {}, None),
        "start_active_ventilation": ("post", "active-ventilation/start", {}, None),
        "stop_active_ventilation": ("post", "active-ventilation/stop", {}, None),
    }
    assert set(hass.services.async_services_for_domain(DOMAIN)) == set(expected)

    for service, (method, path, data, body) in expected.items():
        mock_command(aioclient_mock, method, path)
        await hass.services.async_call(
            DOMAIN, service, {"device_id": device_id, **data}, blocking=True
        )
        assert calls(aioclient_mock, method, path) == [body], service


async def test_start_charging_needs_a_cable(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Without a cable a start is refused before it is sent; a stop is not."""
    payload = load_fixture("enyaq")
    status = payload["vehicle"]["charging"]["status"]
    status["state"] = "CONNECT_CABLE"
    status["plugConnectionState"] = "DISCONNECTED"
    await setup_integration(hass, config_entry, aioclient_mock, payload)
    mock_command(aioclient_mock, "post", "charging/start")
    mock_command(aioclient_mock, "post", "charging/stop")
    assert _state(hass, "switch.enyaq_charging") == "off"

    with pytest.raises(ServiceValidationError) as raised:
        await _call(hass, "switch", "turn_on", "switch.enyaq_charging")
    assert raised.value.translation_key == "cable_not_connected"
    assert calls(aioclient_mock, "post", "charging/start") == []
    assert _state(hass, "switch.enyaq_charging") == "off"

    await _call(hass, "switch", "turn_off", "switch.enyaq_charging")
    assert calls(aioclient_mock, "post", "charging/stop") == [None]


async def test_start_air_conditioning_action(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """The action passes the temperature and the power setting on."""
    await setup_integration(hass, config_entry, aioclient_mock)
    mock_command(aioclient_mock, "post", "air-conditioning/start")

    await hass.services.async_call(
        DOMAIN,
        "start_air_conditioning",
        {
            "device_id": _device_id(hass, config_entry),
            "temperature": 21,
            "without_external_power": True,
        },
        blocking=True,
    )

    assert calls(aioclient_mock, "post", "air-conditioning/start") == [
        {
            "targetTemperature": {"value": 21.0, "unit": "CELSIUS"},
            "airConditioningWithoutExternalPower": True,
        }
    ]
    assert _state(hass, "climate.enyaq_air_conditioning") == "heat_cool"


async def test_action_on_unsupported_vehicle(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """An action the vehicle does not list is refused before sending."""
    await setup_integration(hass, config_entry, aioclient_mock)

    with pytest.raises(ServiceValidationError) as raised:
        await hass.services.async_call(
            DOMAIN,
            "start_auxiliary_heating",
            {"device_id": _device_id(hass, config_entry)},
            blocking=True,
        )
    assert raised.value.translation_key == "command_not_supported"

    with pytest.raises(ServiceValidationError) as raised:
        await hass.services.async_call(
            DOMAIN, "start_air_conditioning", {"device_id": "nope"}, blocking=True
        )
    assert raised.value.translation_key == "vehicle_not_loaded"


async def test_auxiliary_heating_and_ventilation(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The heater needs the S-PIN; the ventilation does not."""
    vin = "TMBAR7NP9R7999999"
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Superb",
        unique_id=vin,
        data={CONF_VIN: vin, CONF_API_KEY: API_KEY},
    )
    url = VEHICLE_URL.replace(VIN, vin)
    aioclient_mock.get(url, json=load_fixture("superb"))
    for path in (
        "auxiliary-heating/start",
        "auxiliary-heating/stop",
        "active-ventilation/stop",
    ):
        aioclient_mock.post(f"{url}/{path}", status=202)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    def sent(path: str) -> list[Any]:
        return [
            call[2]
            for call in aioclient_mock.mock_calls
            if str(call[1]) == f"{url}/{path}"
        ]

    with pytest.raises(ServiceValidationError) as raised:
        await _call(hass, "switch", "turn_on", "switch.superb_auxiliary_heating")
    assert raised.value.translation_key == "spin_required"
    assert sent("auxiliary-heating/start") == []

    hass.config_entries.async_update_entry(entry, options={CONF_SPIN: "1234"})
    await _call(hass, "switch", "turn_on", "switch.superb_auxiliary_heating")
    # The duration the vehicle reports is used unless one is given.
    assert sent("auxiliary-heating/start") == [
        {"spin": "1234", "durationInSeconds": 1200}
    ]
    assert _state(hass, "switch.superb_auxiliary_heating") == "on"

    await hass.services.async_call(
        DOMAIN,
        "start_auxiliary_heating",
        {
            "device_id": _device_id(hass, entry),
            "duration": 30,
            "start_mode": "ventilation",
            "temperature": 22,
            "spin": "4321",
        },
        blocking=True,
    )
    assert sent("auxiliary-heating/start")[-1] == {
        "spin": "4321",
        "durationInSeconds": 1800,
        "startMode": "VENTILATION",
        "targetTemperature": {"value": 22.0, "unit": "CELSIUS"},
    }

    await _call(hass, "switch", "turn_off", "switch.superb_auxiliary_heating")
    assert sent("auxiliary-heating/stop") == [None]
    assert _state(hass, "switch.superb_auxiliary_heating") == "off"

    await _call(hass, "switch", "turn_off", "switch.superb_active_ventilation")
    assert sent("active-ventilation/stop") == [None]
    assert _state(hass, "switch.superb_active_ventilation") == "off"


@pytest.mark.parametrize(
    ("status", "problem", "key"),
    [
        (429, "vehicle-not-accepting-requests", "vehicle_declined"),
        (429, "rate-limit-exceeded", "command_rate_limited"),
        (422, "operation-not-supported", "command_not_supported"),
        (422, "operation-disabled", "command_disabled"),
        (403, "operation-not-authorized", "command_not_authorized"),
        (404, None, "command_not_found"),
        (504, None, "vehicle_timeout"),
        (500, None, "command_failed"),
        (401, "api-key-expired", "auth_failed"),
    ],
)
async def test_command_errors(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    status: int,
    problem: str | None,
    key: str,
) -> None:
    """A refused command tells why and leaves the state alone."""
    await setup_integration(hass, config_entry, aioclient_mock)
    mock_command(
        aioclient_mock,
        "post",
        "charging/stop",
        status=status,
        json={"type": f"{PROBLEMS}/{problem}" if problem else "about:blank"},
        headers={"Retry-After": "600"},
    )

    with pytest.raises(HomeAssistantError) as raised:
        await _call(hass, "switch", "turn_off", "switch.enyaq_charging")

    assert raised.value.translation_key == key
    assert _state(hass, "switch.enyaq_charging") == "on"
    if status == 429:
        assert raised.value.translation_placeholders["minutes"] == "10"
    reauth = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert bool(reauth) is (status == 401)


async def test_quota_used_up_by_command_pauses_polls(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A command refused for the quota stops polls and Refresh until the wait."""
    await setup_integration(hass, config_entry, aioclient_mock)
    mock_command(
        aioclient_mock,
        "post",
        "charging/stop",
        status=429,
        json={"type": f"{PROBLEMS}/rate-limit-exceeded"},
        headers={"Retry-After": "1500"},
    )
    with pytest.raises(HomeAssistantError):
        await _call(hass, "switch", "turn_off", "switch.enyaq_charging")
    requests = len(aioclient_mock.mock_calls)

    # The next scheduled poll falls inside the wait: nothing is sent.
    await _advance(hass, freezer, 660)
    assert len(aioclient_mock.mock_calls) == requests

    with pytest.raises(HomeAssistantError) as raised:
        await hass.services.async_call(
            "button", "press", {"entity_id": "button.enyaq_refresh_data"}, blocking=True
        )
    assert raised.value.translation_key == "refresh_rate_limited"
    assert len(aioclient_mock.mock_calls) == requests

    # Once the wait is over, polling resumes.
    await _advance(hass, freezer, 1200)
    assert len(aioclient_mock.mock_calls) > requests
    assert _state(hass, "switch.enyaq_charging") == "on"


async def test_quota_refusal_without_retry_after_waits_for_the_refill(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Without Retry-After the wait lasts until the quota refills."""
    await setup_integration(hass, config_entry, aioclient_mock)
    mock_command(
        aioclient_mock,
        "post",
        "charging/stop",
        status=429,
        json={"type": f"{PROBLEMS}/rate-limit-exceeded"},
        headers={"RateLimit-Remaining": "0", "RateLimit-Reset": "2400"},
    )
    with pytest.raises(HomeAssistantError):
        await _call(hass, "switch", "turn_off", "switch.enyaq_charging")
    requests = len(aioclient_mock.mock_calls)

    # Well past the default five minutes, still inside the refill time:
    # Refresh, which skips the low-quota check, still waits.
    await _advance(hass, freezer, 660)
    with pytest.raises(HomeAssistantError) as raised:
        await hass.services.async_call(
            "button", "press", {"entity_id": "button.enyaq_refresh_data"}, blocking=True
        )
    assert raised.value.translation_key == "refresh_rate_limited"
    assert len(aioclient_mock.mock_calls) == requests


async def test_update_charging_profile_by_number(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Timers and charging times can be named by their place in the list."""
    await setup_integration(hass, config_entry, aioclient_mock)
    mock_command(aioclient_mock, "put", "charging-profiles/1")
    original = load_fixture("enyaq")["vehicle"]["chargingProfiles"]["profiles"][0]

    await hass.services.async_call(
        DOMAIN,
        "update_charging_profile",
        {
            "device_id": _device_id(hass, config_entry),
            "profile": "Home",
            "preferred_charging_times": [{"position": 2, "enabled": True}],
            "timers": [{"position": 1, "time": "06:15"}, {"id": 2, "enabled": True}],
        },
        blocking=True,
    )

    [sent] = calls(aioclient_mock, "put", "charging-profiles/1")
    assert sent["preferredChargingTimes"] == [
        original["preferredChargingTimes"][0],
        {**original["preferredChargingTimes"][1], "enabled": True},
    ]
    assert sent["timers"] == [
        {**original["timers"][0], "time": "06:15"},
        {**original["timers"][1], "enabled": True},
    ]


async def test_update_charging_profile_number_errors(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A number past the end, or both id and number, is refused."""
    await setup_integration(hass, config_entry, aioclient_mock)
    device_id = _device_id(hass, config_entry)

    with pytest.raises(ServiceValidationError) as raised:
        await hass.services.async_call(
            DOMAIN,
            "update_charging_profile",
            {
                "device_id": device_id,
                "profile": "Home",
                "timers": [{"position": 3, "enabled": True}],
            },
            blocking=True,
        )
    assert raised.value.translation_key == "profile_entry_position_not_found"
    assert raised.value.translation_placeholders == {
        "field": "timers",
        "position": "3",
        "count": "2",
    }

    for entry in ({"id": 1, "position": 1, "enabled": True}, {"enabled": True}):
        with pytest.raises(vol.Invalid):
            await hass.services.async_call(
                DOMAIN,
                "update_charging_profile",
                {"device_id": device_id, "profile": "Home", "timers": [entry]},
                blocking=True,
            )
    assert calls(aioclient_mock, "put", "charging-profiles/1") == []


async def test_wake_button(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Wake re-sends the charge mode and counts once the car reports anew."""
    await setup_integration(hass, config_entry, aioclient_mock)
    mock_command(aioclient_mock, "put", "charging/mode")

    await hass.services.async_call(
        "button", "press", {"entity_id": "button.enyaq_wake_vehicle"}, blocking=True
    )
    assert calls(aioclient_mock, "put", "charging/mode") == [{"chargeMode": "MANUAL"}]
    # Nothing is shown in advance.
    assert _state(hass, "select.enyaq_charge_mode") == "manual"

    # The same report again: not confirmed, so the second follow-up runs.
    mock_vehicle(aioclient_mock)
    await _advance(hass, freezer, 31)
    await _advance(hass, freezer, 90)
    assert len(calls(aioclient_mock, "get")) == 2

    # A newer report confirms the wake: the second follow-up is skipped.
    mock_command(aioclient_mock, "put", "charging/mode")
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.enyaq_wake_vehicle"}, blocking=True
    )
    mock_vehicle(aioclient_mock, _enyaq())
    await _advance(hass, freezer, 31)
    await _advance(hass, freezer, 90)
    assert len(calls(aioclient_mock, "get")) == 1


async def test_wake_button_needs_charge_mode(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Without a reported charge mode there is nothing to re-send."""
    payload = load_fixture("enyaq")
    del payload["vehicle"]["charging"]["settings"]["preferredChargeMode"]
    await setup_integration(hass, config_entry, aioclient_mock, payload)

    assert hass.states.get("button.enyaq_wake_vehicle") is None
    assert hass.states.get("number.enyaq_wake_charging_vehicle_after") is None


async def _setup_auto_wake(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    *,
    headers: dict[str, str] | None = None,
    **options: Any,
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Enyaq",
        unique_id=VIN,
        data={CONF_VIN: VIN, CONF_API_KEY: API_KEY},
        options={CONF_AUTO_WAKE_MINUTES: 30, **options},
    )
    entry.add_to_hass(hass)
    mock_vehicle(aioclient_mock, _enyaq(), headers=headers)
    mock_command(aioclient_mock, "put", "charging/mode")
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_auto_wake_while_charging(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A charging car silent for too long is woken, at most once per wait."""
    # The sample report is 40 minutes old.
    freezer.move_to("2026-06-29T08:45:00+00:00")
    await _setup_auto_wake(hass, aioclient_mock)
    assert calls(aioclient_mock, "put", "charging/mode") == [{"chargeMode": "MANUAL"}]

    # The car keeps silent: no new wake before 30 minutes have passed.
    for _ in range(5):
        await _advance(hass, freezer, 301)
    assert len(calls(aioclient_mock, "put", "charging/mode")) == 1
    await _advance(hass, freezer, 301)
    assert len(calls(aioclient_mock, "put", "charging/mode")) == 2


async def test_auto_wake_off_or_not_needed(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A recent report, or a car that does not charge, is left alone."""
    freezer.move_to("2026-06-29T08:20:00+00:00")
    await _setup_auto_wake(hass, aioclient_mock)
    assert calls(aioclient_mock, "put", "charging/mode") == []

    freezer.move_to("2026-06-29T09:30:00+00:00")
    mock_vehicle(aioclient_mock, _enyaq(charging__status__state="READY_FOR_CHARGING"))
    mock_command(aioclient_mock, "put", "charging/mode")
    await _advance(hass, freezer, 601)
    assert calls(aioclient_mock, "put", "charging/mode") == []


@pytest.mark.parametrize(
    ("options", "headers"),
    [
        ({CONF_AUTO_WAKE_MINUTES: 0}, None),
        ({CONF_READONLY: True}, None),
        # Too few requests left for a command and its follow-ups.
        ({}, {**HEADERS, "RateLimit-Remaining": "5"}),
    ],
)
async def test_auto_wake_held_back(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    options: dict[str, Any],
    headers: dict[str, str] | None,
) -> None:
    """Off, read only or a low quota: nothing is sent."""
    freezer.move_to("2026-06-29T09:45:00+00:00")
    await _setup_auto_wake(hass, aioclient_mock, headers=headers, **options)
    assert calls(aioclient_mock, "put", "charging/mode") == []


async def test_auto_wake_number(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """The wake delay is 0 (off) or 10 to 120 minutes."""
    await setup_integration(hass, config_entry, aioclient_mock)
    entity_id = "number.enyaq_wake_charging_vehicle_after"
    assert _state(hass, entity_id) == "0"

    with pytest.raises(ServiceValidationError) as raised:
        await _call(hass, "number", "set_value", entity_id, value=5)
    assert raised.value.translation_key == "auto_wake_range"

    await _call(hass, "number", "set_value", entity_id, value=45)
    assert config_entry.options[CONF_AUTO_WAKE_MINUTES] == 45
    assert _state(hass, entity_id) == "45"


async def test_auto_wake_gives_up_on_a_silent_car(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """After three unanswered wakes it stops until the car reports again."""
    freezer.move_to("2026-06-29T08:45:00+00:00")
    await _setup_auto_wake(hass, aioclient_mock)
    for _ in range(40):
        await _advance(hass, freezer, 301)
    assert len(calls(aioclient_mock, "put", "charging/mode")) == 3


async def test_wake_waits_for_a_pending_change(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Waking would re-send the old charge mode over one still on its way."""
    await setup_integration(hass, config_entry, aioclient_mock)
    mock_command(aioclient_mock, "put", "charging/mode")
    await _call(
        hass, "select", "select_option", "select.enyaq_charge_mode", option="timer"
    )

    with pytest.raises(ServiceValidationError) as raised:
        await hass.services.async_call(
            "button", "press", {"entity_id": "button.enyaq_wake_vehicle"}, blocking=True
        )
    assert raised.value.translation_key == "wake_command_pending"
    assert calls(aioclient_mock, "put", "charging/mode") == [{"chargeMode": "TIMER"}]


async def test_quota_wait_entity_clears_when_the_wait_ends(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The wait shown after a quota refusal ends on time, without a request."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Enyaq",
        unique_id=VIN,
        data=config_entry.data,
        options={"poll_interval": 60, "active_poll_interval": 60},
    )
    await setup_integration(hass, config_entry, aioclient_mock)
    mock_command(
        aioclient_mock,
        "post",
        "charging/stop",
        status=429,
        json={"type": f"{PROBLEMS}/rate-limit-exceeded"},
        headers={"Retry-After": "120"},
    )
    with pytest.raises(HomeAssistantError):
        await _call(hass, "switch", "turn_off", "switch.enyaq_charging")
    assert _state(hass, "sensor.enyaq_waiting_for_quota_until") != "unknown"
    requests = len(aioclient_mock.mock_calls)

    await _advance(hass, freezer, 122)

    assert _state(hass, "sensor.enyaq_waiting_for_quota_until") == "unknown"
    assert len(aioclient_mock.mock_calls) == requests
