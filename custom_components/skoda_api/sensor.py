"""Sensors of the MyŠkoda Public API integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfLength,
    UnitOfPower,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from .const import (
    API_STATUSES,
    CHARGE_MODES,
    COMBUSTION_ENGINE_TYPES,
    FIELD_TIMERS,
    FIELD_TIMES,
    OP_SET_CHARGE_MODE,
    OP_SET_CHARGING_LIMIT,
    OP_START_AIR_CONDITIONING,
    OP_STOP_AIR_CONDITIONING,
    SECTION_ACTIVE_VENTILATION,
    SECTION_AIR_CONDITIONING,
    SECTION_AUXILIARY_HEATING,
    SECTION_CHARGING,
    SECTION_CHARGING_PROFILES,
    SECTION_FUEL,
    SECTION_ODOMETER,
    SECTION_PARKING,
    SECTION_STATUS,
)
from .coordinator import SkodaApiConfigEntry, SkodaApiCoordinator
from .data import VehicleData
from .entity import (
    ChargingProfileEntity,
    SkodaApiDescription,
    SkodaApiEntity,
    async_add_when_available,
    described_candidates,
    profile_candidates,
)

PARALLEL_UPDATES = 0

type SensorValue = StateType | datetime


@dataclass(frozen=True, kw_only=True)
class SkodaApiSensorDescription(SkodaApiDescription, SensorEntityDescription):
    """Describe a sensor."""

    value_fn: Callable[[VehicleData], SensorValue] | None = None
    # Operations that replace this sensor with a control.
    replaced_by: tuple[str, ...] = ()
    coordinator_fn: Callable[[SkodaApiCoordinator], SensorValue] | None = None
    attributes_fn: Callable[[VehicleData], dict[str, Any]] | None = None
    coordinator_attributes_fn: (
        Callable[[SkodaApiCoordinator], dict[str, Any]] | None
    ) = None
    # Connection sensors stay available when an update fails.
    always_available: bool = False

    def exists(self, data: VehicleData) -> bool:
        """Return True when the vehicle provides this sensor."""
        if self.replaced_by and not data.shown_read_only(*self.replaced_by):
            return False
        return super().exists(data)


def _minutes(seconds: float | None) -> float | None:
    return None if seconds is None else round(seconds / 60)


def _engine(engine_type: str, field: str) -> Callable[[VehicleData], SensorValue]:
    def _value(data: VehicleData) -> SensorValue:
        engine = data.engine(engine_type)
        value = engine.get(field) if engine else None
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        return value

    return _value


def _hybrid_battery_exists(data: VehicleData) -> bool:
    """Exist for plug-in hybrids: a fuel engine plus a reported battery level."""
    return (
        bool(data.combustion_engine_types)
        and _engine("electric", "currentSoCInPercent")(data) is not None
        and data.number(SECTION_CHARGING, "status", "battery", "stateOfChargeInPercent")
        is None
    )


def _poll_minutes(coordinator: SkodaApiCoordinator) -> int | None:
    interval = coordinator.update_interval
    return None if interval is None else round(interval.total_seconds() / 60)


def _lock_state(data: VehicleData) -> str | None:
    return {"yes": "locked", "no": "unlocked"}.get(
        value := data.text(SECTION_STATUS, "overall", "doorsLocked") or "", value
    )


def _current_profile_attributes(data: VehicleData) -> dict[str, Any]:
    profile = data.get(SECTION_CHARGING_PROFILES, "currentVehiclePositionProfile")
    if not isinstance(profile, dict):
        return {}
    return {
        "profile_id": profile.get("id"),
        "target_state_of_charge": profile.get("targetStateOfChargeInPercent"),
        "next_charging_time": profile.get("nextChargingTime"),
    }


def _unavailable_data(data: VehicleData) -> dict[str, Any]:
    return {
        "issues": [
            {"type": e.get("type"), "description": e.get("description")}
            for e in data.errors
        ],
        "stale": sorted(data.stale),
    }


def _quota_reset(coordinator: SkodaApiCoordinator) -> datetime | None:
    """Return when the request quota refills, rounded to the minute."""
    limit = coordinator.client.rate_limit
    if limit is None or limit.reset_at is None or limit.refilled(dt_util.utcnow()):
        return None
    reset = limit.reset_at + timedelta(seconds=30)
    return reset.replace(second=0, microsecond=0)


def _requests_remaining(coordinator: SkodaApiCoordinator) -> int | None:
    """Return the requests left; once the quota has refilled, the full quota."""
    limit = coordinator.client.rate_limit
    return limit.left(dt_util.utcnow()) if limit is not None else None


SENSORS: tuple[SkodaApiSensorDescription, ...] = (
    # ---------------------------------------------------------------- range
    SkodaApiSensorDescription(
        key="range",
        translation_key="range",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        exists_fn=lambda d: d.has(SECTION_FUEL) or d.has(SECTION_CHARGING),
        value_fn=lambda d: d.total_range_km,
    ),
    SkodaApiSensorDescription(
        key="electric_range",
        translation_key="electric_range",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        # A battery-only vehicle has one range; this one is for hybrids.
        exists_fn=lambda d: d.has(SECTION_FUEL) and d.battery_range_km is not None,
        value_fn=lambda d: d.battery_range_km,
    ),
    *(
        SkodaApiSensorDescription(
            key=f"{engine_type}_range",
            translation_key=f"{engine_type}_range",
            section=SECTION_FUEL,
            device_class=SensorDeviceClass.DISTANCE,
            native_unit_of_measurement=UnitOfLength.KILOMETERS,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=0,
            exists_fn=lambda d, t=engine_type: d.engine(t) is not None,
            value_fn=_engine(engine_type, "remainingRangeInKm"),
        )
        for engine_type in COMBUSTION_ENGINE_TYPES
    ),
    *(
        SkodaApiSensorDescription(
            key=f"{engine_type}_level",
            translation_key=f"{engine_type}_level",
            section=SECTION_FUEL,
            native_unit_of_measurement=PERCENTAGE,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=0,
            exists_fn=lambda d, t=engine_type: d.engine(t) is not None,
            value_fn=_engine(engine_type, "currentFuelLevelInPercent"),
        )
        for engine_type in COMBUSTION_ENGINE_TYPES
    ),
    SkodaApiSensorDescription(
        key="adblue_range",
        translation_key="adblue_range",
        section=SECTION_FUEL,
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        exists_fn=lambda d: d.number(SECTION_FUEL, "adBlueRange") is not None,
        value_fn=lambda d: d.number(SECTION_FUEL, "adBlueRange"),
    ),
    SkodaApiSensorDescription(
        key="car_type",
        translation_key="car_type",
        section=SECTION_FUEL,
        device_class=SensorDeviceClass.ENUM,
        options=["hybrid", *COMBUSTION_ENGINE_TYPES],
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.text(SECTION_FUEL, "carType"),
    ),
    SkodaApiSensorDescription(
        key="mileage",
        translation_key="mileage",
        section=SECTION_ODOMETER,
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=0,
        value_fn=lambda d: d.number(SECTION_ODOMETER, "mileageInKm"),
    ),
    # ------------------------------------------------------------- charging
    SkodaApiSensorDescription(
        key="battery_percentage",
        translation_key="battery_percentage",
        section=SECTION_CHARGING,
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.number(
            SECTION_CHARGING, "status", "battery", "stateOfChargeInPercent"
        ),
    ),
    SkodaApiSensorDescription(
        key="hybrid_battery",
        translation_key="hybrid_battery",
        section=SECTION_FUEL,
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        exists_fn=_hybrid_battery_exists,
        value_fn=_engine("electric", "currentSoCInPercent"),
    ),
    SkodaApiSensorDescription(
        key="charging_state",
        translation_key="charging_state",
        section=SECTION_CHARGING,
        device_class=SensorDeviceClass.ENUM,
        options=[
            "connect_cable",
            "charging",
            "conserving",
            "ready_for_charging",
            "discharging",
            "charging_interrupted",
        ],
        value_fn=lambda d: d.text(SECTION_CHARGING, "status", "state"),
    ),
    SkodaApiSensorDescription(
        key="charge_type",
        translation_key="charge_type",
        section=SECTION_CHARGING,
        device_class=SensorDeviceClass.ENUM,
        options=["ac", "dc", "off"],
        value_fn=lambda d: d.text(SECTION_CHARGING, "status", "chargeType"),
    ),
    SkodaApiSensorDescription(
        key="charging_power",
        translation_key="charging_power",
        section=SECTION_CHARGING,
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.number(SECTION_CHARGING, "status", "chargePowerInKw"),
    ),
    SkodaApiSensorDescription(
        key="charging_rate",
        translation_key="charging_rate",
        section=SECTION_CHARGING,
        device_class=SensorDeviceClass.SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda d: d.number(
            SECTION_CHARGING, "status", "chargingRateInKilometersPerHour"
        ),
    ),
    SkodaApiSensorDescription(
        key="remaining_charging_time",
        translation_key="remaining_charging_time",
        section=SECTION_CHARGING,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.number(
            SECTION_CHARGING, "status", "remainingTimeToFullyChargedInMinutes"
        ),
    ),
    SkodaApiSensorDescription(
        key="fully_charged_at",
        translation_key="fully_charged_at",
        section=SECTION_CHARGING,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: d.timestamp(SECTION_CHARGING, "status", "fullyChargedAt"),
    ),
    SkodaApiSensorDescription(
        key="target_battery_percentage",
        translation_key="target_battery_percentage",
        section=SECTION_CHARGING,
        native_unit_of_measurement=PERCENTAGE,
        # Vehicles that accept a new limit get a number entity instead.
        replaced_by=(OP_SET_CHARGING_LIMIT,),
        value_fn=lambda d: d.number(
            SECTION_CHARGING, "settings", "targetStateOfChargeInPercent"
        ),
    ),
    SkodaApiSensorDescription(
        key="charge_mode",
        translation_key="charge_mode",
        section=SECTION_CHARGING,
        device_class=SensorDeviceClass.ENUM,
        options=list(CHARGE_MODES),
        # Vehicles that accept a new mode get a select entity instead.
        replaced_by=(OP_SET_CHARGE_MODE,),
        value_fn=lambda d: d.text(SECTION_CHARGING, "settings", "preferredChargeMode"),
    ),
    SkodaApiSensorDescription(
        key="battery_care_target",
        translation_key="battery_care_target",
        section=SECTION_CHARGING,
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        exists_fn=lambda d: (
            d.number(
                SECTION_CHARGING, "settings", "batteryCareModeTargetValueInPercent"
            )
            is not None
        ),
        value_fn=lambda d: d.number(
            SECTION_CHARGING, "settings", "batteryCareModeTargetValueInPercent"
        ),
    ),
    SkodaApiSensorDescription(
        key="max_charge_current",
        translation_key="max_charge_current",
        section=SECTION_CHARGING,
        device_class=SensorDeviceClass.ENUM,
        options=["maximum", "reduced"],
        exists_fn=lambda d: (
            d.text(SECTION_CHARGING, "settings", "maxChargeCurrentAc") is not None
        ),
        value_fn=lambda d: d.text(SECTION_CHARGING, "settings", "maxChargeCurrentAc"),
    ),
    SkodaApiSensorDescription(
        key="max_charge_current_ampere",
        translation_key="max_charge_current_ampere",
        section=SECTION_CHARGING,
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        exists_fn=lambda d: (
            d.number(SECTION_CHARGING, "settings", "maxChargeCurrentAcAmpere")
            is not None
        ),
        value_fn=lambda d: d.number(
            SECTION_CHARGING, "settings", "maxChargeCurrentAcAmpere"
        ),
    ),
    SkodaApiSensorDescription(
        key="charging_location",
        translation_key="charging_location",
        section=SECTION_CHARGING_PROFILES,
        value_fn=lambda d: d.get(
            SECTION_CHARGING_PROFILES, "currentVehiclePositionProfile", "name"
        ),
        attributes_fn=_current_profile_attributes,
    ),
    SkodaApiSensorDescription(
        key="next_charging_time",
        translation_key="next_charging_time",
        section=SECTION_CHARGING_PROFILES,
        value_fn=lambda d: d.get(
            SECTION_CHARGING_PROFILES,
            "currentVehiclePositionProfile",
            "nextChargingTime",
        ),
    ),
    # -------------------------------------------------------------- climate
    SkodaApiSensorDescription(
        key="air_conditioning_state",
        translation_key="air_conditioning_state",
        section=SECTION_AIR_CONDITIONING,
        device_class=SensorDeviceClass.ENUM,
        options=[
            "off",
            "cooling",
            "heating",
            "heating_auxiliary",
            "ventilation",
            "completed",
        ],
        value_fn=lambda d: d.text(SECTION_AIR_CONDITIONING, "state"),
    ),
    SkodaApiSensorDescription(
        key="target_temperature",
        translation_key="target_temperature",
        section=SECTION_AIR_CONDITIONING,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        # Vehicles that can be started get a climate entity instead.
        replaced_by=(OP_START_AIR_CONDITIONING, OP_STOP_AIR_CONDITIONING),
        exists_fn=lambda d: d.target_temperature is not None,
        value_fn=lambda d: d.target_temperature,
    ),
    SkodaApiSensorDescription(
        key="target_temperature_reached_at",
        translation_key="target_temperature_reached_at",
        section=SECTION_AIR_CONDITIONING,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: d.timestamp(
            SECTION_AIR_CONDITIONING, "estimatedReachOfTargetTemperatureAt"
        ),
    ),
    SkodaApiSensorDescription(
        key="auxiliary_heating_state",
        translation_key="auxiliary_heating_state",
        section=SECTION_AUXILIARY_HEATING,
        device_class=SensorDeviceClass.ENUM,
        options=["off", "preheating", "heating_auxiliary", "ventilation"],
        value_fn=lambda d: d.text(SECTION_AUXILIARY_HEATING, "state"),
    ),
    SkodaApiSensorDescription(
        key="auxiliary_heating_duration",
        translation_key="auxiliary_heating_duration",
        section=SECTION_AUXILIARY_HEATING,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        entity_category=EntityCategory.DIAGNOSTIC,
        exists_fn=lambda d: (
            d.number(SECTION_AUXILIARY_HEATING, "durationInSeconds") is not None
        ),
        value_fn=lambda d: _minutes(
            d.number(SECTION_AUXILIARY_HEATING, "durationInSeconds")
        ),
    ),
    SkodaApiSensorDescription(
        key="auxiliary_heating_reached_at",
        translation_key="auxiliary_heating_reached_at",
        section=SECTION_AUXILIARY_HEATING,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: d.timestamp(
            SECTION_AUXILIARY_HEATING, "estimatedReachOfTargetTemperatureAt"
        ),
    ),
    SkodaApiSensorDescription(
        key="active_ventilation_state",
        translation_key="active_ventilation_state",
        section=SECTION_ACTIVE_VENTILATION,
        device_class=SensorDeviceClass.ENUM,
        options=["off", "preheating", "ventilation"],
        value_fn=lambda d: d.text(SECTION_ACTIVE_VENTILATION, "state"),
    ),
    SkodaApiSensorDescription(
        key="active_ventilation_duration",
        translation_key="active_ventilation_duration",
        section=SECTION_ACTIVE_VENTILATION,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        entity_category=EntityCategory.DIAGNOSTIC,
        exists_fn=lambda d: (
            d.number(SECTION_ACTIVE_VENTILATION, "durationInSeconds") is not None
        ),
        value_fn=lambda d: _minutes(
            d.number(SECTION_ACTIVE_VENTILATION, "durationInSeconds")
        ),
    ),
    # --------------------------------------------------------------- status
    SkodaApiSensorDescription(
        key="lock_state",
        translation_key="lock_state",
        section=SECTION_STATUS,
        device_class=SensorDeviceClass.ENUM,
        options=["locked", "unlocked", "opened", "trunk_opened"],
        value_fn=_lock_state,
    ),
    SkodaApiSensorDescription(
        key="parking_address",
        translation_key="parking_address",
        section=SECTION_PARKING,
        value_fn=lambda d: d.get(SECTION_PARKING, "formattedAddress"),
    ),
    # ---------------------------------------------------------- diagnostics
    SkodaApiSensorDescription(
        key="last_updated",
        translation_key="last_updated",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.last_captured,
    ),
    SkodaApiSensorDescription(
        key="license_plate",
        translation_key="license_plate",
        entity_category=EntityCategory.DIAGNOSTIC,
        exists_fn=lambda d: d.license_plate is not None,
        value_fn=lambda d: d.license_plate,
    ),
    SkodaApiSensorDescription(
        key="unavailable_data",
        translation_key="unavailable_data",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: len(d.errors),
        attributes_fn=_unavailable_data,
    ),
    SkodaApiSensorDescription(
        key="api_key_expiry",
        translation_key="api_key_expiry",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        coordinator_fn=lambda c: c.client.key_expires_at,
    ),
    SkodaApiSensorDescription(
        key="api_quota_reset",
        translation_key="api_quota_reset",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        coordinator_fn=_quota_reset,
    ),
    SkodaApiSensorDescription(
        key="api_requests_remaining",
        translation_key="api_requests_remaining",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        coordinator_fn=_requests_remaining,
    ),
    SkodaApiSensorDescription(
        key="last_poll",
        translation_key="last_poll",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        always_available=True,
        coordinator_fn=lambda c: c.last_poll,
    ),
    SkodaApiSensorDescription(
        key="api_status",
        translation_key="api_status",
        device_class=SensorDeviceClass.ENUM,
        options=list(API_STATUSES),
        entity_category=EntityCategory.DIAGNOSTIC,
        always_available=True,
        coordinator_fn=lambda c: c.api_status,
    ),
    SkodaApiSensorDescription(
        key="quota_wait_until",
        translation_key="quota_wait_until",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        always_available=True,
        coordinator_fn=lambda c: c.blocked_until,
    ),
    SkodaApiSensorDescription(
        key="current_poll_interval",
        translation_key="current_poll_interval",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        entity_category=EntityCategory.DIAGNOSTIC,
        always_available=True,
        coordinator_fn=_poll_minutes,
        coordinator_attributes_fn=lambda c: {"mode": c.poll_mode},
    ),
)


def _schedule_count(profile: dict[str, Any]) -> int:
    return sum(
        1
        for field in (FIELD_TIMES, FIELD_TIMERS)
        for entry in profile.get(field) or []
        if isinstance(entry, dict) and entry.get("enabled")
    )


PROFILE_SENSOR = SkodaApiSensorDescription(
    key="schedule",
    translation_key="charging_profile_schedule",
    section=SECTION_CHARGING_PROFILES,
    entity_category=EntityCategory.DIAGNOSTIC,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SkodaApiConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors of a vehicle."""
    coordinator = entry.runtime_data
    async_add_when_available(
        entry,
        async_add_entities,
        described_candidates(coordinator, SENSORS, SkodaApiSensor),
        profile_candidates(
            coordinator, (PROFILE_SENSOR,), ChargingProfileSchedule, writable=False
        ),
    )


class SkodaApiSensor(SkodaApiEntity, SensorEntity):
    """A sensor of a vehicle."""

    entity_description: SkodaApiSensorDescription

    @property
    def available(self) -> bool:
        """Keep the connection sensors when an update fails."""
        return self.entity_description.always_available or super().available

    @property
    def native_value(self) -> SensorValue:
        """Return the value, or None while the vehicle does not report it."""
        description = self.entity_description
        if description.coordinator_fn is not None:
            value = description.coordinator_fn(self.coordinator)
        elif description.value_fn is not None:
            value = description.value_fn(self.vehicle)
        else:
            value = None
        if description.options is not None and value not in description.options:
            # The API may add values over time; an unknown one is no state.
            return None
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the extra details of sensors that have some."""
        description = self.entity_description
        if description.coordinator_attributes_fn is not None:
            return description.coordinator_attributes_fn(self.coordinator)
        if description.attributes_fn is None:
            return None
        return description.attributes_fn(self.vehicle)


class ChargingProfileSchedule(ChargingProfileEntity, SensorEntity):
    """The timers and preferred charging times of a charging profile."""

    @property
    def native_value(self) -> int | None:
        """Return how many timers and charging times are switched on."""
        profile = self.profile
        return None if profile is None else _schedule_count(profile)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the full schedule of the profile."""
        profile = self.profile or {}
        return {
            **super().extra_state_attributes,
            "preferred_charging_times": [
                {
                    "id": e.get("id"),
                    "enabled": e.get("enabled"),
                    "start_time": e.get("startTime"),
                    "end_time": e.get("endTime"),
                }
                for e in profile.get(FIELD_TIMES) or []
                if isinstance(e, dict)
            ],
            "timers": [
                {
                    "id": e.get("id"),
                    "enabled": e.get("enabled"),
                    "time": e.get("time"),
                    "type": str(e.get("type") or "").lower() or None,
                    "one_off_day": str(e.get("oneOffDay") or "").lower() or None,
                    "recurring_on": [
                        str(day).lower() for day in e.get("recurringOn") or []
                    ],
                }
                for e in profile.get(FIELD_TIMERS) or []
                if isinstance(e, dict)
            ],
        }
