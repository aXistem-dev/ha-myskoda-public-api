"""Tests of setting the integration up and of its entities."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.skoda_api.const import (
    CONF_ACTIVE_POLL_INTERVAL,
    CONF_FAST_POLL_WHEN_PLUGGED,
    CONF_POLL_INTERVAL,
    CONF_READONLY,
    DOMAIN,
    STALE_SECTION_POLLS,
)

from .conftest import (
    HEADERS,
    VEHICLE_URL,
    VIN,
    load_fixture,
    mock_vehicle,
    setup_integration,
)

PROBLEMS = "https://public.api.connect.skoda-auto.cz/problems"


def _state(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    assert state is not None, f"{entity_id} does not exist"
    return state.state


async def _poll(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.tick(timedelta(minutes=10, seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_electric_vehicle(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    device_registry: dr.DeviceRegistry,
) -> None:
    """An electric vehicle gets its charging, climate and status entities."""
    await setup_integration(hass, config_entry, aioclient_mock)

    assert config_entry.state is ConfigEntryState.LOADED
    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, VIN), config_entry.entry_id
    )
    assert device is not None
    assert device.name == "Enyaq"
    assert device.manufacturer == "Škoda"

    expected = {
        "sensor.enyaq_battery": "64",
        "sensor.enyaq_range": "312.0",
        "sensor.enyaq_mileage": "23456",
        "sensor.enyaq_charging_state": "charging",
        "sensor.enyaq_charge_type": "ac",
        "sensor.enyaq_charging_power": "10.5",
        "sensor.enyaq_charging_rate": "52.0",
        "sensor.enyaq_remaining_charging_time": "95",
        "sensor.enyaq_fully_charged": "2026-06-29T09:35:00+00:00",
        "sensor.enyaq_battery_care_charge_limit": "80",
        "sensor.enyaq_charging_current": "maximum",
        "sensor.enyaq_charging_location": "Home",
        "sensor.enyaq_next_charging_time": "22:00",
        "sensor.enyaq_air_conditioning_state": "off",
        "sensor.enyaq_lock_state": "locked",
        "sensor.enyaq_parking_address": "Example Street 1, 110 00 Prague, Czechia",
        "sensor.enyaq_last_vehicle_update": "2026-06-29T08:00:00+00:00",
        "sensor.enyaq_license_plate": "1MB 1234",
        "sensor.enyaq_unavailable_data": "0",
        "sensor.enyaq_api_key_expiry": "2099-01-01T00:00:00+00:00",
        "sensor.enyaq_api_requests_remaining": "17",
        "sensor.enyaq_home_schedules": "2",
        "sensor.enyaq_work_schedules": "0",
        "binary_sensor.enyaq_lock": "off",
        "binary_sensor.enyaq_doors": "off",
        "binary_sensor.enyaq_windows": "off",
        "binary_sensor.enyaq_trunk": "off",
        "binary_sensor.enyaq_bonnet": "off",
        "binary_sensor.enyaq_lights": "off",
        "binary_sensor.enyaq_in_motion": "off",
        "binary_sensor.enyaq_charging": "on",
        "binary_sensor.enyaq_charging_cable": "on",
        "binary_sensor.enyaq_charging_cable_lock": "off",
        "binary_sensor.enyaq_at_saved_charging_location": "on",
        "binary_sensor.enyaq_battery_care_mode": "on",
        "binary_sensor.enyaq_unlock_cable_when_charged": "on",
        "binary_sensor.enyaq_front_window_heating": "off",
        "binary_sensor.enyaq_rear_window_heating": "off",
        "binary_sensor.enyaq_air_conditioning_at_unlock": "off",
        "binary_sensor.enyaq_air_conditioning_without_external_power": "on",
        "switch.enyaq_charging": "on",
        "number.enyaq_charge_limit": "80",
        "select.enyaq_charge_mode": "manual",
        "climate.enyaq_air_conditioning": "off",
        "device_tracker.enyaq": "not_home",
        "number.enyaq_home_charge_limit": "80",
        "number.enyaq_home_minimum_charge_level": "20",
        "select.enyaq_home_charging_current": "maximum",
        "switch.enyaq_home_unlock_cable_when_charged": "off",
        "switch.enyaq_home_minimum_charge": "on",
        "number.enyaq_work_charge_limit": "100",
        "select.enyaq_work_charging_current": "reduced",
        "switch.enyaq_work_unlock_cable_when_charged": "on",
        "switch.enyaq_work_minimum_charge": STATE_UNKNOWN,
    }
    assert {entity_id: _state(hass, entity_id) for entity_id in expected} == expected

    # Parts this vehicle lacks have no entities.
    for missing in (
        "binary_sensor.enyaq_sunroof",
        "sensor.enyaq_diesel_range",
        "sensor.enyaq_electric_range",
        "sensor.enyaq_charge_limit",
        "sensor.enyaq_charge_mode",
        "sensor.enyaq_hybrid_battery",
        "switch.enyaq_auxiliary_heating",
        "switch.enyaq_active_ventilation",
    ):
        assert hass.states.get(missing) is None, missing

    # The quota refills within the hour, shown to the minute.
    refill = hass.states.get("sensor.enyaq_api_quota_refills")
    assert refill.state.endswith(":00+00:00")

    tracker = hass.states.get("device_tracker.enyaq")
    assert tracker.attributes["latitude"] == 50.0755
    assert tracker.attributes["longitude"] == 14.4378
    assert tracker.attributes["entity_picture"].endswith("enyaq.png")
    assert hass.states.get("image.enyaq_picture") is not None
    assert hass.states.get("button.enyaq_refresh_data") is not None

    mode = hass.states.get("select.enyaq_charge_mode")
    # A mode this integration has no name for is left out.
    assert mode.attributes["options"] == ["manual", "timer"]
    climate = hass.states.get("climate.enyaq_air_conditioning")
    assert climate.attributes["temperature"] == 22
    schedule = hass.states.get("sensor.enyaq_home_schedules")
    assert schedule.attributes["profile_name"] == "Home"
    assert schedule.attributes["timers"][0] == {
        "id": 1,
        "enabled": True,
        "time": "07:30",
        "type": "recurring",
        "one_off_day": None,
        "recurring_on": ["monday", "friday"],
    }


async def test_combustion_vehicle(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A diesel gets fuel entities and its heater, and nothing electric."""
    await setup_integration(hass, config_entry, aioclient_mock, "superb")

    expected = {
        "sensor.superb_range": "780",
        "sensor.superb_diesel_range": "780",
        "sensor.superb_diesel_level": "71",
        "sensor.superb_adblue_range": "6400",
        "sensor.superb_drivetrain": "diesel",
        "sensor.superb_mileage": "98765",
        "sensor.superb_lock_state": "trunk_opened",
        "sensor.superb_auxiliary_heating_state": "off",
        "sensor.superb_auxiliary_heating_duration": "20",
        "sensor.superb_active_ventilation_state": "ventilation",
        "binary_sensor.superb_lock": "on",
        "binary_sensor.superb_windows": "on",
        "binary_sensor.superb_trunk": "on",
        "binary_sensor.superb_sunroof": "off",
        "binary_sensor.superb_lights": "on",
        "binary_sensor.superb_in_motion": "on",
        "switch.superb_auxiliary_heating": "off",
        "switch.superb_active_ventilation": "on",
        # On the move the API gives no position.
        "device_tracker.superb": STATE_UNKNOWN,
    }
    assert {entity_id: _state(hass, entity_id) for entity_id in expected} == expected

    for missing in (
        "sensor.superb_battery",
        "sensor.superb_gasoline_range",
        "switch.superb_charging",
        "number.superb_charge_limit",
        "climate.superb_air_conditioning",
    ):
        assert hass.states.get(missing) is None, missing


async def test_plug_in_hybrid(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A hybrid shows the total range and each source on its own."""
    await setup_integration(hass, config_entry, aioclient_mock, "phev")

    expected = {
        "sensor.octavia_iv_range": "640",
        "sensor.octavia_iv_electric_range": "40.0",
        "sensor.octavia_iv_gasoline_range": "600",
        "sensor.octavia_iv_gasoline_level": "80",
        "sensor.octavia_iv_battery": "70",
        "sensor.octavia_iv_drivetrain": "hybrid",
        # The API names no state for this combination; the plug decides.
        "sensor.octavia_iv_charging_state": STATE_UNKNOWN,
        "binary_sensor.octavia_iv_charging": "off",
        "binary_sensor.octavia_iv_charging_cable": "off",
        # Without the operations the limit and the mode are read-only.
        "sensor.octavia_iv_charge_limit": "100",
    }
    assert {entity_id: _state(hass, entity_id) for entity_id in expected} == expected
    # The same level as Battery: no second battery entity.
    assert hass.states.get("sensor.octavia_iv_hybrid_battery") is None
    assert hass.states.get("number.octavia_iv_charge_limit") is None
    assert hass.states.get("switch.octavia_iv_charging") is None


async def test_readonly_has_no_controls(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Read only leaves the sensors and drops everything that sends."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Enyaq",
        unique_id=VIN,
        data=config_entry.data,
        options={CONF_READONLY: True},
    )
    await setup_integration(hass, config_entry, aioclient_mock)

    assert _state(hass, "sensor.enyaq_battery") == "64"
    assert _state(hass, "sensor.enyaq_home_schedules") == "2"
    # What the controls would have shown is still there to read.
    assert _state(hass, "sensor.enyaq_charge_limit") == "80"
    assert _state(hass, "sensor.enyaq_charge_mode") == "manual"
    assert _state(hass, "sensor.enyaq_target_temperature") == "22"
    assert _state(hass, "binary_sensor.enyaq_charging") == "on"
    for missing in (
        "switch.enyaq_charging",
        "number.enyaq_charge_limit",
        "select.enyaq_charge_mode",
        "climate.enyaq_air_conditioning",
        "number.enyaq_home_charge_limit",
        "switch.enyaq_home_timer_1",
        "time.enyaq_home_timer_1_time",
        "button.enyaq_wake_vehicle",
        "number.enyaq_wake_charging_vehicle_after",
    ):
        assert hass.states.get(missing) is None, missing
    # The polling settings send nothing to the vehicle and stay.
    assert _state(hass, "number.enyaq_polling_interval") == "10"
    assert _state(hass, "number.enyaq_polling_interval_while_active") == "5"
    assert _state(hass, "switch.enyaq_fast_polling_while_plugged_in") == "off"


async def test_partial_data_keeps_last_values_for_a_while(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A part that fails to load keeps its values briefly, then goes away."""
    await setup_integration(hass, config_entry, aioclient_mock)
    mock_vehicle(aioclient_mock, "partial")

    for _ in range(STALE_SECTION_POLLS):
        await _poll(hass, freezer)
        # Charging could not be retrieved: the last values stay.
        assert _state(hass, "sensor.enyaq_battery") == "64"
        # The status is switched off, which is no hiccup: it goes at once.
        assert _state(hass, "binary_sensor.enyaq_doors") == STATE_UNAVAILABLE
        assert _state(hass, "sensor.enyaq_mileage") == "23460"
        assert _state(hass, "sensor.enyaq_unavailable_data") == "4"
        # The picture and the known operations survive a hiccup.
        assert _state(hass, "switch.enyaq_charging") == "on"
        assert (
            hass.states.get("device_tracker.enyaq")
            .attributes["entity_picture"]
            .endswith("enyaq.png")
        )

    await _poll(hass, freezer)
    assert _state(hass, "sensor.enyaq_battery") == STATE_UNAVAILABLE
    assert _state(hass, "switch.enyaq_charging") == STATE_UNAVAILABLE

    mock_vehicle(aioclient_mock)
    await _poll(hass, freezer)
    assert _state(hass, "sensor.enyaq_battery") == "64"
    assert _state(hass, "binary_sensor.enyaq_doors") == "off"


async def test_entities_appear_when_data_arrives(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Entities of a part missing at start are added once it shows up."""
    await setup_integration(hass, config_entry, aioclient_mock, "partial")
    assert _state(hass, "sensor.enyaq_mileage") == "23460"
    assert hass.states.get("sensor.enyaq_battery") is None
    assert hass.states.get("switch.enyaq_charging") is None

    mock_vehicle(aioclient_mock)
    await _poll(hass, freezer)

    assert _state(hass, "sensor.enyaq_battery") == "64"
    assert _state(hass, "switch.enyaq_charging") == "on"
    assert _state(hass, "number.enyaq_home_charge_limit") == "80"


async def test_unknown_values_are_no_state(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Values the API adds later do not break the entities."""
    payload = load_fixture("enyaq")
    charging = payload["vehicle"]["charging"]
    charging["status"]["state"] = "SOMETHING_NEW"
    charging["status"]["chargeType"] = "WIRELESS"
    charging["settings"]["preferredChargeMode"] = "SOMETHING_NEW"
    payload["vehicle"]["status"]["overall"]["doors"] = "AJAR"
    await setup_integration(hass, config_entry, aioclient_mock, payload)

    assert _state(hass, "sensor.enyaq_charging_state") == STATE_UNKNOWN
    assert _state(hass, "sensor.enyaq_charge_type") == STATE_UNKNOWN
    assert _state(hass, "select.enyaq_charge_mode") == STATE_UNKNOWN
    assert _state(hass, "binary_sensor.enyaq_doors") == STATE_UNKNOWN
    assert _state(hass, "binary_sensor.enyaq_charging") == "off"


async def test_profile_renamed_and_removed(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    entity_registry: er.EntityRegistry,
) -> None:
    """Entities follow a profile's new name; those of a deleted one go."""
    await setup_integration(hass, config_entry, aioclient_mock)
    assert hass.states.get("number.enyaq_home_charge_limit").name == (
        "Enyaq Home charge limit"
    )

    payload = load_fixture("enyaq")
    profiles = payload["vehicle"]["chargingProfiles"]
    profiles["profiles"][0]["name"] = "Garage"
    del profiles["profiles"][1]
    mock_vehicle(aioclient_mock, payload)
    await _poll(hass, freezer)
    await hass.async_block_till_done()
    # One response without it is not enough to remove anything.
    assert entity_registry.async_get("number.enyaq_work_charge_limit") is not None
    await _poll(hass, freezer)
    await hass.async_block_till_done()

    renamed = hass.states.get("number.enyaq_home_charge_limit")
    assert renamed.name == "Enyaq Garage charge limit"
    assert renamed.attributes["profile_name"] == "Garage"
    assert hass.states.get("number.enyaq_work_charge_limit") is None
    assert entity_registry.async_get("number.enyaq_work_charge_limit") is None
    assert entity_registry.async_get("sensor.enyaq_work_schedules") is None


async def test_timestamp_without_zone(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A timestamp that names no zone is read as UTC, not refused."""
    payload = load_fixture("enyaq")
    charging = payload["vehicle"]["charging"]
    charging["status"]["fullyChargedAt"] = "2026-06-29T09:35:00"
    charging["carCapturedTimestamp"] = "2026-06-29T08:30:00"
    await setup_integration(hass, config_entry, aioclient_mock, payload)

    assert _state(hass, "sensor.enyaq_fully_charged") == "2026-06-29T09:35:00+00:00"
    assert (
        _state(hass, "sensor.enyaq_last_vehicle_update") == "2026-06-29T08:30:00+00:00"
    )


async def test_rate_limit_at_setup_waits(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Setup retries stay off the API for as long as it asked to wait."""
    aioclient_mock.get(
        VEHICLE_URL,
        status=429,
        json={"type": f"{PROBLEMS}/rate-limit-exceeded"},
        headers={"Retry-After": "1500"},
    )
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    assert len(aioclient_mock.mock_calls) == 1

    # Home Assistant retries after seconds, then minutes: none reach the API.
    for _ in range(6):
        freezer.tick(timedelta(minutes=3))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
    assert len(aioclient_mock.mock_calls) == 1
    assert config_entry.state is ConfigEntryState.SETUP_RETRY

    mock_vehicle(aioclient_mock)
    for _ in range(6):
        freezer.tick(timedelta(minutes=10))
        async_fire_time_changed(hass)
        await hass.async_block_till_done(wait_background_tasks=True)
        if config_entry.state is ConfigEntryState.LOADED:
            break
    assert config_entry.state is ConfigEntryState.LOADED
    assert _state(hass, "sensor.enyaq_battery") == "64"


async def test_unique_ids(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    entity_registry: er.EntityRegistry,
) -> None:
    """Unique ids are the VIN plus a stable key."""
    await setup_integration(hass, config_entry, aioclient_mock)

    assert (
        entity_registry.async_get("sensor.enyaq_battery").unique_id
        == f"{VIN}_battery_percentage"
    )
    assert (
        entity_registry.async_get("number.enyaq_work_charge_limit").unique_id
        == f"{VIN}_charging_profile_2_target"
    )
    entries = er.async_entries_for_config_entry(entity_registry, config_entry.entry_id)
    assert len({entry.unique_id for entry in entries}) == len(entries)
    assert all(entry.translation_key or entry.domain == "x" for entry in entries)


@pytest.mark.parametrize(
    ("status", "problem", "expected"),
    [
        (401, "api-key-expired", ConfigEntryState.SETUP_ERROR),
        (403, "api-key-not-authorized", ConfigEntryState.SETUP_ERROR),
        (500, None, ConfigEntryState.SETUP_RETRY),
        (429, "rate-limit-exceeded", ConfigEntryState.SETUP_RETRY),
    ],
)
async def test_setup_failures(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    status: int,
    problem: str | None,
    expected: ConfigEntryState,
) -> None:
    """A refused key asks for a new one; anything else is tried again."""
    aioclient_mock.get(
        VEHICLE_URL,
        status=status,
        json={"type": f"{PROBLEMS}/{problem}" if problem else "about:blank"},
    )
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is expected
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert bool(flows) is (expected is ConfigEntryState.SETUP_ERROR)
    if flows:
        assert flows[0]["context"]["source"] == "reauth"


async def test_key_refused_later_starts_reauth(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A key that expires while running asks for a new one."""
    await setup_integration(hass, config_entry, aioclient_mock)
    aioclient_mock.clear_requests()
    aioclient_mock.get(
        VEHICLE_URL, status=401, json={"type": f"{PROBLEMS}/api-key-expired"}
    )

    await _poll(hass, freezer)

    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]
    assert _state(hass, "sensor.enyaq_battery") == STATE_UNAVAILABLE


async def test_rate_limit_keeps_data(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Running out of requests keeps the data and waits for the refill."""
    await setup_integration(hass, config_entry, aioclient_mock)
    aioclient_mock.clear_requests()
    aioclient_mock.get(
        VEHICLE_URL,
        status=429,
        json={"type": f"{PROBLEMS}/rate-limit-exceeded"},
        headers={"Retry-After": "1500", "RateLimit-Remaining": "0"},
    )

    await _poll(hass, freezer)
    assert _state(hass, "sensor.enyaq_battery") == "64"
    assert _state(hass, "sensor.enyaq_api_requests_remaining") == "0"
    requests = len(aioclient_mock.mock_calls)

    # 10 and 20 minutes later the wait is not over: no request is made.
    await _poll(hass, freezer)
    await _poll(hass, freezer)
    assert len(aioclient_mock.mock_calls) == requests
    assert _state(hass, "sensor.enyaq_battery") == "64"

    mock_vehicle(aioclient_mock)
    await _poll(hass, freezer)
    assert len(aioclient_mock.mock_calls) == 1


async def test_polling_pauses_when_few_requests_remain(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The last requests of the hour are kept for commands."""
    await setup_integration(hass, config_entry, aioclient_mock)
    mock_vehicle(
        aioclient_mock,
        headers={**HEADERS, "RateLimit-Remaining": "2", "RateLimit-Reset": "1500"},
    )
    await _poll(hass, freezer)
    assert len(aioclient_mock.mock_calls) == 1

    await _poll(hass, freezer)
    assert len(aioclient_mock.mock_calls) == 1
    assert _state(hass, "sensor.enyaq_battery") == "64"

    # The button is the owner's own decision and fetches anyway.
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.enyaq_refresh_data"}, blocking=True
    )
    assert len(aioclient_mock.mock_calls) == 2

    # Once the quota has refilled, polling resumes.
    freezer.tick(timedelta(minutes=30))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(aioclient_mock.mock_calls) == 3


async def test_key_expiry_warning(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    issue_registry: ir.IssueRegistry,
) -> None:
    """A key about to expire raises a repair; a fresh key clears it."""
    freezer.move_to("2026-11-01T12:00:00+00:00")
    mock_vehicle(
        aioclient_mock,
        headers={**HEADERS, "X-API-Key-Expires-At": "2026-11-10T12:00:00Z"},
    )
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    issue_id = f"api_key_expiring_{config_entry.entry_id}"

    issue = issue_registry.async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.translation_placeholders == {"name": "Enyaq", "date": "2026-11-10"}

    mock_vehicle(
        aioclient_mock,
        headers={**HEADERS, "X-API-Key-Expires-At": "2027-11-10T12:00:00Z"},
    )
    await _poll(hass, freezer)
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is None


async def test_loads_without_a_vehicle(
    hass: HomeAssistant, mock_frontend: AsyncMock
) -> None:
    """A bare YAML entry loads the actions and the dashboard strategy."""
    assert await async_setup_component(hass, DOMAIN, {DOMAIN: None})
    await hass.async_block_till_done()

    assert hass.services.has_service(DOMAIN, "update_charging_profile")
    mock_frontend.assert_awaited_once()


async def test_unload(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """The entry unloads cleanly."""
    await setup_integration(hass, config_entry, aioclient_mock)

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.NOT_LOADED
    assert _state(hass, "sensor.enyaq_battery") == STATE_UNAVAILABLE


async def test_timer_removed(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    entity_registry: er.EntityRegistry,
) -> None:
    """The entities of a timer deleted in the app go; the others stay."""
    await setup_integration(hass, config_entry, aioclient_mock)
    assert hass.states.get("switch.enyaq_home_timer_1") is not None

    payload = load_fixture("enyaq")
    profile = payload["vehicle"]["chargingProfiles"]["profiles"][0]
    profile["timers"] = [t for t in profile["timers"] if t["id"] != 1]
    mock_vehicle(aioclient_mock, payload)
    await _poll(hass, freezer)
    await hass.async_block_till_done()
    assert entity_registry.async_get("switch.enyaq_home_timer_1") is not None
    await _poll(hass, freezer)
    await hass.async_block_till_done()

    assert entity_registry.async_get("switch.enyaq_home_timer_1") is None
    assert entity_registry.async_get("time.enyaq_home_timer_1_time") is None
    assert hass.states.get("switch.enyaq_home_timer_2") is not None
    assert hass.states.get("number.enyaq_home_charge_limit") is not None


async def test_readonly_off_removes_stand_ins(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    entity_registry: er.EntityRegistry,
) -> None:
    """Switching read only off replaces the stand-in sensors by controls."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Enyaq",
        unique_id=VIN,
        data=config_entry.data,
        options={CONF_READONLY: True},
    )
    await setup_integration(hass, config_entry, aioclient_mock)
    assert entity_registry.async_get("sensor.enyaq_charge_limit") is not None

    hass.config_entries.async_update_entry(config_entry, options={})
    await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()

    for gone in (
        "sensor.enyaq_charge_limit",
        "sensor.enyaq_charge_mode",
        "sensor.enyaq_target_temperature",
    ):
        assert entity_registry.async_get(gone) is None, gone
    assert _state(hass, "number.enyaq_charge_limit") == "80"
    assert hass.states.get("climate.enyaq_air_conditioning") is not None


async def test_incomplete_profile_keeps_entities(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    entity_registry: er.EntityRegistry,
) -> None:
    """A profile reported without its lists does not lose timer entities."""
    await setup_integration(hass, config_entry, aioclient_mock)
    reloads = AsyncMock()
    hass.config_entries.async_schedule_reload = reloads

    payload = load_fixture("enyaq")
    profile = payload["vehicle"]["chargingProfiles"]["profiles"][0]
    del profile["timers"]
    del profile["preferredChargingTimes"]
    mock_vehicle(aioclient_mock, payload)
    for _ in range(3):
        await _poll(hass, freezer)
    await hass.async_block_till_done()

    assert entity_registry.async_get("switch.enyaq_home_timer_1") is not None
    assert entity_registry.async_get("switch.enyaq_home_timer_2") is not None
    reloads.assert_not_called()


def _plugged_in() -> dict:
    """Return the sample vehicle plugged in, done charging."""
    payload = load_fixture("enyaq")
    payload["vehicle"]["charging"]["status"]["state"] = "READY_FOR_CHARGING"
    return payload


async def test_faster_polling_while_active(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Charging and climate poll at the shorter interval, the rest normally."""
    await setup_integration(hass, config_entry, aioclient_mock)
    coordinator = config_entry.runtime_data
    assert coordinator.update_interval == timedelta(minutes=5)
    interval = hass.states.get("sensor.enyaq_current_polling_interval")
    assert interval.state == "5"
    assert interval.attributes["mode"] == "active"

    mock_vehicle(aioclient_mock, _plugged_in())
    await _poll(hass, freezer)
    assert coordinator.update_interval == timedelta(minutes=10)
    interval = hass.states.get("sensor.enyaq_current_polling_interval")
    assert interval.state == "10"
    assert interval.attributes["mode"] == "normal"

    # Running air conditioning counts as active too.
    payload = _plugged_in()
    payload["vehicle"]["airConditioning"]["state"] = "HEATING"
    mock_vehicle(aioclient_mock, payload)
    await _poll(hass, freezer)
    assert coordinator.update_interval == timedelta(minutes=5)


async def test_polling_settings_apply_without_reload(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The polling controls store options and take effect at once."""
    await setup_integration(hass, config_entry, aioclient_mock, _plugged_in())
    coordinator = config_entry.runtime_data
    reloads = AsyncMock()
    hass.config_entries.async_schedule_reload = reloads
    assert coordinator.update_interval == timedelta(minutes=10)

    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": "switch.enyaq_fast_polling_while_plugged_in"},
        blocking=True,
    )
    assert config_entry.options[CONF_FAST_POLL_WHEN_PLUGGED] is True
    assert coordinator.update_interval == timedelta(minutes=5)
    assert _state(hass, "switch.enyaq_fast_polling_while_plugged_in") == "on"
    assert _state(hass, "sensor.enyaq_current_polling_interval") == "5"

    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": "switch.enyaq_fast_polling_while_plugged_in"},
        blocking=True,
    )
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.enyaq_polling_interval", "value": 30},
        blocking=True,
    )
    assert config_entry.options[CONF_POLL_INTERVAL] == 30
    assert coordinator.update_interval == timedelta(minutes=30)
    assert _state(hass, "number.enyaq_polling_interval") == "30"

    # The new interval counts from the change: no poll after 10 or 20 minutes.
    aioclient_mock.mock_calls.clear()
    for _ in range(2):
        freezer.tick(timedelta(minutes=10))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
    assert len(aioclient_mock.mock_calls) == 0
    freezer.tick(timedelta(minutes=10, seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(aioclient_mock.mock_calls) == 1

    # Nothing was reloaded: the same coordinator kept running.
    reloads.assert_not_called()
    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.runtime_data is coordinator


async def test_connection_sensors(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The connection sensors tell how the last update went, also on failure."""
    freezer.move_to("2026-11-01T12:00:00+00:00")
    await setup_integration(hass, config_entry, aioclient_mock)
    assert _state(hass, "sensor.enyaq_api_status") == "ok"
    assert _state(hass, "sensor.enyaq_last_poll") == "2026-11-01T12:00:00+00:00"
    assert _state(hass, "sensor.enyaq_waiting_for_quota_until") == STATE_UNKNOWN

    # Few requests left: the poll is skipped.
    mock_vehicle(
        aioclient_mock,
        headers={**HEADERS, "RateLimit-Remaining": "2", "RateLimit-Reset": "3000"},
    )
    await _poll(hass, freezer)
    await _poll(hass, freezer)
    assert _state(hass, "sensor.enyaq_api_status") == "skipped_quota"
    assert _state(hass, "sensor.enyaq_last_poll") == "2026-11-01T12:10:01+00:00"

    # A server error: the vehicle data goes, the connection sensors stay.
    freezer.tick(timedelta(hours=1))
    aioclient_mock.clear_requests()
    aioclient_mock.get(VEHICLE_URL, status=500, json={"type": "about:blank"})
    await _poll(hass, freezer)
    assert _state(hass, "sensor.enyaq_battery") == STATE_UNAVAILABLE
    assert _state(hass, "sensor.enyaq_api_status") == "error"
    assert _state(hass, "sensor.enyaq_last_poll") == "2026-11-01T12:10:01+00:00"
    assert _state(hass, "sensor.enyaq_current_polling_interval") == "5"

    # The quota is used up: the wait shows until it is over.
    aioclient_mock.clear_requests()
    aioclient_mock.get(
        VEHICLE_URL,
        status=429,
        json={"type": f"{PROBLEMS}/rate-limit-exceeded"},
        headers={"Retry-After": "1500", "RateLimit-Remaining": "0"},
    )
    await _poll(hass, freezer)
    assert _state(hass, "sensor.enyaq_api_status") == "rate_limited"
    until = dt_util.utcnow() + timedelta(seconds=1500)
    assert _state(hass, "sensor.enyaq_waiting_for_quota_until") == until.isoformat()

    mock_vehicle(aioclient_mock)
    freezer.tick(timedelta(minutes=25))
    await _poll(hass, freezer)
    assert _state(hass, "sensor.enyaq_api_status") == "ok"
    assert _state(hass, "sensor.enyaq_waiting_for_quota_until") == STATE_UNKNOWN

    aioclient_mock.clear_requests()
    aioclient_mock.get(
        VEHICLE_URL, status=401, json={"type": f"{PROBLEMS}/api-key-expired"}
    )
    await _poll(hass, freezer)
    assert _state(hass, "sensor.enyaq_api_status") == "auth_failed"


async def test_parked_unsecured(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A parked car that is open or unlocked is flagged, with the reasons."""
    await setup_integration(hass, config_entry, aioclient_mock)
    secured = hass.states.get("binary_sensor.enyaq_parked_unsecured")
    assert secured.state == "off"
    assert secured.attributes["reasons"] == []
    assert secured.attributes["device_class"] == "safety"

    payload = load_fixture("enyaq")
    status = payload["vehicle"]["status"]
    status["overall"]["doors"] = "OPEN"
    status["overall"]["locked"] = "NO"
    # A vehicle without window reports leaves the windows out.
    status["overall"]["windows"] = "UNSUPPORTED"
    # An unknown state is no reassurance.
    status["detail"]["trunk"] = "SOMETHING_NEW"
    mock_vehicle(aioclient_mock, payload)
    await _poll(hass, freezer)
    unsecured = hass.states.get("binary_sensor.enyaq_parked_unsecured")
    assert unsecured.state == "on"
    assert unsecured.attributes["reasons"] == ["doors_open", "trunk_open", "unlocked"]
    assert unsecured.attributes["reported_at"] == datetime(
        2026, 6, 29, 8, 0, tzinfo=UTC
    )

    # On the move the car is not parked.
    payload["vehicle"]["parkingPosition"]["state"] = "IN_MOTION"
    mock_vehicle(aioclient_mock, payload)
    await _poll(hass, freezer)
    assert _state(hass, "binary_sensor.enyaq_parked_unsecured") == "off"

    # Without a status there is nothing to tell.
    mock_vehicle(aioclient_mock, "partial")
    await _poll(hass, freezer)
    assert _state(hass, "binary_sensor.enyaq_parked_unsecured") == STATE_UNKNOWN


async def test_combustion_vehicle_on_the_move_is_not_flagged(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """An open, unlocked car that drives is no parking alert."""
    await setup_integration(hass, config_entry, aioclient_mock, "superb")
    assert _state(hass, "binary_sensor.superb_parked_unsecured") == "off"
    # Without the charge mode command there is nothing to wake with.
    assert hass.states.get("button.superb_wake_vehicle") is None


async def test_stored_response_fills_a_missing_part_after_restart(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    hass_storage: dict,
) -> None:
    """After a restart the kept response stands in for a part the API lacks."""
    config_entry.add_to_hass(hass)
    hass_storage[f"{DOMAIN}.{config_entry.entry_id}"] = {
        "version": 1,
        "minor_version": 1,
        "key": f"{DOMAIN}.{config_entry.entry_id}",
        "data": {"payload": {"vehicle": load_fixture("enyaq")["vehicle"]}},
    }
    await setup_integration(hass, config_entry, aioclient_mock, "partial")

    # Charging could not be retrieved at start; the kept values fill in.
    assert _state(hass, "sensor.enyaq_battery") == "64"


async def test_removing_the_vehicle_deletes_the_stored_response(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    hass_storage: dict,
) -> None:
    """Nothing about a removed vehicle stays on disk."""
    await setup_integration(hass, config_entry, aioclient_mock)
    key = f"{DOMAIN}.{config_entry.entry_id}"
    hass_storage[key] = {"version": 1, "key": key, "data": {"payload": {}}}

    await hass.config_entries.async_remove(config_entry.entry_id)
    await hass.async_block_till_done()

    assert key not in hass_storage


async def test_hybrid_battery_without_charging_data(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A hybrid that reports its level only in the fuel status gets a sensor."""
    payload = load_fixture("phev")
    del payload["vehicle"]["charging"]["status"]["battery"]
    await setup_integration(hass, config_entry, aioclient_mock, payload)

    assert _state(hass, "sensor.octavia_iv_hybrid_battery") == "70"


async def test_stale_parts_are_not_stored(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    hass_storage: dict,
) -> None:
    """A part shown from an earlier response is not kept as if it were new."""
    await setup_integration(hass, config_entry, aioclient_mock)
    mock_vehicle(aioclient_mock, "partial")
    await _poll(hass, freezer)
    hass.bus.async_fire("homeassistant_final_write")
    await hass.async_block_till_done()

    stored = hass_storage[f"{DOMAIN}.{config_entry.entry_id}"]["data"]["payload"]
    assert "charging" not in stored["vehicle"]


async def test_quota_entities_follow_the_refill(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """When the quota refills, the entities show it without a request."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Enyaq",
        unique_id=VIN,
        data=config_entry.data,
        options={CONF_POLL_INTERVAL: 60, CONF_ACTIVE_POLL_INTERVAL: 60},
    )
    # The sample response says the quota refills in 30 minutes.
    await setup_integration(hass, config_entry, aioclient_mock)
    assert _state(hass, "sensor.enyaq_api_requests_remaining") == "17"
    assert _state(hass, "sensor.enyaq_api_quota_refills") != STATE_UNKNOWN
    requests = len(aioclient_mock.mock_calls)

    freezer.tick(timedelta(seconds=1802))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert len(aioclient_mock.mock_calls) == requests
    assert _state(hass, "sensor.enyaq_api_requests_remaining") == "20"
    assert _state(hass, "sensor.enyaq_api_quota_refills") == STATE_UNKNOWN
