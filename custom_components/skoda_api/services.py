"""Actions of the MyŠkoda Public API integration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr
import voluptuous as vol

from . import commands
from .const import (
    CHARGE_MODES,
    DOMAIN,
    FIELD_TIMERS,
    FIELD_TIMES,
    OP_SET_CHARGE_MODE,
    OP_SET_CHARGING_LIMIT,
    OP_START_ACTIVE_VENTILATION,
    OP_START_AIR_CONDITIONING,
    OP_START_AUXILIARY_HEATING,
    OP_START_CHARGING,
    OP_STOP_ACTIVE_VENTILATION,
    OP_STOP_AIR_CONDITIONING,
    OP_STOP_AUXILIARY_HEATING,
    OP_STOP_CHARGING,
    OP_UPDATE_CHARGING_PROFILE,
    SERVICE_SET_CHARGE_MODE,
    SERVICE_SET_CHARGING_LIMIT,
    SERVICE_START_ACTIVE_VENTILATION,
    SERVICE_START_AIR_CONDITIONING,
    SERVICE_START_AUXILIARY_HEATING,
    SERVICE_START_CHARGING,
    SERVICE_STOP_ACTIVE_VENTILATION,
    SERVICE_STOP_AIR_CONDITIONING,
    SERVICE_STOP_AUXILIARY_HEATING,
    SERVICE_STOP_CHARGING,
    SERVICE_UPDATE_CHARGING_PROFILE,
    WEEKDAYS,
)
from .coordinator import SkodaApiCoordinator
from .profiles import async_send_profile, find_profile

ATTR_TEMPERATURE = "temperature"
ATTR_WITHOUT_EXTERNAL_POWER = "without_external_power"
ATTR_DURATION = "duration"
ATTR_START_MODE = "start_mode"
ATTR_SPIN = "spin"
ATTR_PROFILE = "profile"
ATTR_NAME = "name"
ATTR_CHARGE_MODE = "charge_mode"
ATTR_TARGET = "target_state_of_charge"
ATTR_MAX_CURRENT = "max_charging_current"
ATTR_AUTO_UNLOCK = "auto_unlock_plug"
ATTR_MIN_BATTERY_ENABLED = "min_battery_enabled"
ATTR_MIN_BATTERY = "min_battery_state_of_charge"
ATTR_TIMES = "preferred_charging_times"
ATTR_TIMERS = "timers"

_TEMPERATURE = vol.All(vol.Coerce(float), vol.Range(min=15.5, max=30))
_TIME = vol.All(cv.string, vol.Match(r"^([01]\d|2[0-3]):[0-5]\d$"))
_WEEKDAY = vol.All(cv.string, vol.Lower, vol.In(WEEKDAYS))
_DEVICE = {vol.Required(ATTR_DEVICE_ID): cv.string}

# A timer or charging time is named by its id or its position (from 1).
_ENTRY_REF = {
    vol.Exclusive("id", "entry"): cv.positive_int,
    vol.Exclusive("position", "entry"): vol.All(vol.Coerce(int), vol.Range(min=1)),
}


def _entry_schema(fields: dict[Any, Any]) -> vol.All:
    return vol.All(
        vol.Schema({**_ENTRY_REF, **fields}),
        cv.has_at_least_one_key("id", "position"),
    )


DEVICE_SCHEMA = vol.Schema(_DEVICE)

SET_CHARGING_LIMIT_SCHEMA = vol.Schema(
    {
        **_DEVICE,
        # The API takes 1 to 100; vehicles typically 50 to 100 in steps of 10.
        vol.Required(ATTR_TARGET): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
    }
)

SET_CHARGE_MODE_SCHEMA = vol.Schema(
    {
        **_DEVICE,
        vol.Required(ATTR_CHARGE_MODE): vol.All(
            cv.string, vol.Lower, vol.In(CHARGE_MODES)
        ),
    }
)

START_AIR_CONDITIONING_SCHEMA = vol.Schema(
    {
        **_DEVICE,
        vol.Optional(ATTR_TEMPERATURE): _TEMPERATURE,
        vol.Optional(ATTR_WITHOUT_EXTERNAL_POWER): cv.boolean,
    }
)

START_AUXILIARY_HEATING_SCHEMA = vol.Schema(
    {
        **_DEVICE,
        vol.Optional(ATTR_DURATION): vol.All(vol.Coerce(int), vol.Range(min=5, max=60)),
        vol.Optional(ATTR_START_MODE): vol.All(
            cv.string, vol.Lower, vol.In(("heating", "ventilation"))
        ),
        vol.Optional(ATTR_TEMPERATURE): _TEMPERATURE,
        vol.Optional(ATTR_SPIN): vol.All(cv.string, vol.Match(r"^\d{4}$")),
    }
)

UPDATE_CHARGING_PROFILE_SCHEMA = vol.Schema(
    {
        **_DEVICE,
        vol.Required(ATTR_PROFILE): vol.Any(cv.positive_int, cv.string),
        vol.Optional(ATTR_NAME): vol.All(cv.string, vol.Length(min=1)),
        vol.Optional(ATTR_TARGET): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
        vol.Optional(ATTR_MAX_CURRENT): vol.All(
            cv.string, vol.Lower, vol.In(("maximum", "reduced"))
        ),
        vol.Optional(ATTR_AUTO_UNLOCK): cv.boolean,
        vol.Optional(ATTR_MIN_BATTERY_ENABLED): cv.boolean,
        vol.Optional(ATTR_MIN_BATTERY): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=100)
        ),
        vol.Optional(ATTR_TIMES): vol.All(
            cv.ensure_list,
            [
                _entry_schema(
                    {
                        vol.Optional("enabled"): cv.boolean,
                        vol.Optional("start_time"): _TIME,
                        vol.Optional("end_time"): _TIME,
                    }
                )
            ],
        ),
        vol.Optional(ATTR_TIMERS): vol.All(
            cv.ensure_list,
            [
                _entry_schema(
                    {
                        vol.Optional("enabled"): cv.boolean,
                        vol.Optional("time"): _TIME,
                        vol.Optional("type"): vol.All(
                            cv.string, vol.Lower, vol.In(("one_off", "recurring"))
                        ),
                        vol.Optional("one_off_day"): _WEEKDAY,
                        vol.Optional("recurring_on"): vol.All(
                            cv.ensure_list, [_WEEKDAY]
                        ),
                    }
                )
            ],
        ),
    }
)

_TIME_FIELDS = {"enabled": "enabled", "start_time": "startTime", "end_time": "endTime"}
_TIMER_FIELDS = {
    "enabled": "enabled",
    "time": "time",
    "type": "type",
    "one_off_day": "oneOffDay",
    "recurring_on": "recurringOn",
}


def _to_api(entry: dict[str, Any], fields: dict[str, str]) -> dict[str, Any]:
    """Translate one schedule entry to the names and values of the API."""
    result: dict[str, Any] = {"id": entry["id"]}
    for key, api_key in fields.items():
        if key not in entry:
            continue
        value = entry[key]
        if key in ("type", "one_off_day"):
            value = value.upper()
        elif key == "recurring_on":
            value = [day.upper() for day in value]
        result[api_key] = value
    return result


def _resolve_positions(
    profile: dict[str, Any] | None,
    field: str,
    attribute: str,
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Replace positions in a profile's list by the ids of those entries."""
    reported = [
        e
        for e in ((profile or {}).get(field) or [])
        if isinstance(e, dict) and "id" in e
    ]
    resolved: list[dict[str, Any]] = []
    for entry in entries:
        if "position" not in entry:
            resolved.append(entry)
            continue
        position = entry["position"]
        if position > len(reported):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="profile_entry_position_not_found",
                translation_placeholders={
                    "field": attribute,
                    "position": str(position),
                    "count": str(len(reported)),
                },
            )
        changes = {k: v for k, v in entry.items() if k != "position"}
        resolved.append({**changes, "id": reported[position - 1]["id"]})
    return resolved


def _coordinator(
    hass: HomeAssistant, call: ServiceCall, operation: str
) -> SkodaApiCoordinator:
    """Return the coordinator of the vehicle an action is aimed at."""
    device = dr.async_get(hass).async_get(call.data[ATTR_DEVICE_ID])
    if device is not None:
        for entry_id in device.config_entries:
            entry = hass.config_entries.async_get_entry(entry_id)
            if (
                entry is not None
                and entry.domain == DOMAIN
                and entry.state is ConfigEntryState.LOADED
            ):
                coordinator: SkodaApiCoordinator = entry.runtime_data
                if not coordinator.data.supports(operation):
                    raise ServiceValidationError(
                        translation_domain=DOMAIN,
                        translation_key="command_not_supported",
                    )
                return coordinator
    raise ServiceValidationError(
        translation_domain=DOMAIN, translation_key="vehicle_not_loaded"
    )


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the actions."""

    async def start_air_conditioning(call: ServiceCall) -> None:
        await commands.async_start_air_conditioning(
            _coordinator(hass, call, OP_START_AIR_CONDITIONING),
            temperature=call.data.get(ATTR_TEMPERATURE),
            without_external_power=call.data.get(ATTR_WITHOUT_EXTERNAL_POWER),
        )

    async def start_auxiliary_heating(call: ServiceCall) -> None:
        await commands.async_start_auxiliary_heating(
            _coordinator(hass, call, OP_START_AUXILIARY_HEATING),
            spin=call.data.get(ATTR_SPIN),
            duration_minutes=call.data.get(ATTR_DURATION),
            start_mode=call.data.get(ATTR_START_MODE),
            temperature=call.data.get(ATTR_TEMPERATURE),
        )

    async def update_charging_profile(call: ServiceCall) -> None:
        coordinator = _coordinator(hass, call, OP_UPDATE_CHARGING_PROFILE)
        data = call.data
        settings: dict[str, Any] = {}
        if ATTR_TARGET in data:
            settings["targetStateOfChargeInPercent"] = data[ATTR_TARGET]
        if ATTR_MAX_CURRENT in data:
            settings["maxChargingCurrent"] = data[ATTR_MAX_CURRENT].upper()
        if ATTR_AUTO_UNLOCK in data:
            settings["autoUnlockPlugWhenCharged"] = (
                "PERMANENT" if data[ATTR_AUTO_UNLOCK] else "OFF"
            )
        min_battery: dict[str, Any] = {}
        if ATTR_MIN_BATTERY_ENABLED in data:
            min_battery["enabled"] = data[ATTR_MIN_BATTERY_ENABLED]
        if ATTR_MIN_BATTERY in data:
            min_battery["minimumBatteryStateOfChargeInPercent"] = data[ATTR_MIN_BATTERY]
        if min_battery:
            settings["minBatteryStateOfCharge"] = min_battery
        profile_id = find_profile(coordinator, data[ATTR_PROFILE])
        profile = coordinator.data.profile(profile_id)
        times = [
            _to_api(e, _TIME_FIELDS)
            for e in _resolve_positions(
                profile, FIELD_TIMES, ATTR_TIMES, data.get(ATTR_TIMES, [])
            )
        ]
        timers = [
            _to_api(e, _TIMER_FIELDS)
            for e in _resolve_positions(
                profile, FIELD_TIMERS, ATTR_TIMERS, data.get(ATTR_TIMERS, [])
            )
        ]
        name = data.get(ATTR_NAME)
        if not (settings or times or timers or name):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="nothing_to_change"
            )
        await async_send_profile(
            coordinator,
            profile_id,
            settings=settings,
            preferred_charging_times=times,
            timers=timers,
            name=name,
        )

    def simple(
        operation: str,
        command: Callable[[SkodaApiCoordinator], Awaitable[None]],
    ) -> Callable[[ServiceCall], Awaitable[None]]:
        """Return the handler of an action that takes only the vehicle."""

        async def handler(call: ServiceCall) -> None:
            await command(_coordinator(hass, call, operation))

        return handler

    async def set_charging_limit(call: ServiceCall) -> None:
        await commands.async_set_charge_limit(
            _coordinator(hass, call, OP_SET_CHARGING_LIMIT), call.data[ATTR_TARGET]
        )

    async def set_charge_mode(call: ServiceCall) -> None:
        await commands.async_set_charge_mode(
            _coordinator(hass, call, OP_SET_CHARGE_MODE), call.data[ATTR_CHARGE_MODE]
        )

    for service, operation, command in (
        (
            SERVICE_START_CHARGING,
            OP_START_CHARGING,
            lambda c: commands.async_set_charging(c, True),
        ),
        (
            SERVICE_STOP_CHARGING,
            OP_STOP_CHARGING,
            lambda c: commands.async_set_charging(c, False),
        ),
        (
            SERVICE_STOP_AIR_CONDITIONING,
            OP_STOP_AIR_CONDITIONING,
            commands.async_stop_air_conditioning,
        ),
        (
            SERVICE_STOP_AUXILIARY_HEATING,
            OP_STOP_AUXILIARY_HEATING,
            commands.async_stop_auxiliary_heating,
        ),
        (
            SERVICE_START_ACTIVE_VENTILATION,
            OP_START_ACTIVE_VENTILATION,
            lambda c: commands.async_set_active_ventilation(c, True),
        ),
        (
            SERVICE_STOP_ACTIVE_VENTILATION,
            OP_STOP_ACTIVE_VENTILATION,
            lambda c: commands.async_set_active_ventilation(c, False),
        ),
    ):
        hass.services.async_register(
            DOMAIN, service, simple(operation, command), schema=DEVICE_SCHEMA
        )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_CHARGING_LIMIT,
        set_charging_limit,
        schema=SET_CHARGING_LIMIT_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_CHARGE_MODE, set_charge_mode, schema=SET_CHARGE_MODE_SCHEMA
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_START_AIR_CONDITIONING,
        start_air_conditioning,
        schema=START_AIR_CONDITIONING_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_START_AUXILIARY_HEATING,
        start_auxiliary_heating,
        schema=START_AUXILIARY_HEATING_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE_CHARGING_PROFILE,
        update_charging_profile,
        schema=UPDATE_CHARGING_PROFILE_SCHEMA,
    )
