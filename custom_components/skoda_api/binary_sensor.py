"""Binary sensors of the MyŠkoda Public API integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    SECTION_AIR_CONDITIONING,
    SECTION_CHARGING,
    SECTION_PARKING,
    SECTION_STATUS,
)
from .coordinator import SkodaApiConfigEntry
from .data import VehicleData
from .entity import (
    SkodaApiDescription,
    SkodaApiEntity,
    async_add_when_available,
    described_candidates,
)

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class SkodaApiBinarySensorDescription(
    SkodaApiDescription, BinarySensorEntityDescription
):
    """Describe a binary sensor."""

    is_on_fn: Callable[[VehicleData], bool | None]
    attributes_fn: Callable[[VehicleData], dict[str, Any]] | None = None


def _open(*path: str) -> Callable[[VehicleData], bool | None]:
    return lambda d: d.flag(SECTION_STATUS, *path, on="open", off="closed")


def _reports(*path: str) -> Callable[[VehicleData], bool]:
    """Exist unless the vehicle says it has no such part."""
    return lambda d: d.text(SECTION_STATUS, *path) not in (None, "unsupported")


def _unlocked(data: VehicleData) -> bool | None:
    locked = data.flag(SECTION_STATUS, "overall", "locked", on="yes", off="no")
    if locked is None:
        locked = data.flag(
            SECTION_STATUS,
            "overall",
            "reliableLockStatus",
            on="locked",
            off="unlocked",
        )
    return None if locked is None else not locked


def _lock_reported(data: VehicleData) -> bool:
    return _reports("overall", "locked")(data) or _reports(
        "overall", "reliableLockStatus"
    )(data)


def _in_motion(data: VehicleData) -> bool | None:
    return data.flag(SECTION_PARKING, "state", on="in_motion", off="parked")


# Reason, whether the part is open, and whether the vehicle reports it.
_SECURITY_CHECKS: tuple[
    tuple[str, Callable[[VehicleData], bool | None], Callable[[VehicleData], bool]],
    ...,
] = (
    ("doors_open", _open("overall", "doors"), _reports("overall", "doors")),
    ("unlocked", _unlocked, _lock_reported),
    ("windows_open", _open("overall", "windows"), _reports("overall", "windows")),
    ("trunk_open", _open("detail", "trunk"), _reports("detail", "trunk")),
    ("bonnet_open", _open("detail", "bonnet"), _reports("detail", "bonnet")),
)


def unsecured_reasons(data: VehicleData) -> list[str] | None:
    """Return why a parked vehicle is not secured; None without a status.

    A reported state other than closed or locked counts as not secured.
    """
    if not data.has(SECTION_STATUS):
        return None
    if _in_motion(data) is True:
        return []
    return sorted(
        reason
        for reason, is_open, reported in _SECURITY_CHECKS
        if reported(data) and is_open(data) is not False
    )


def _parked_unsecured(data: VehicleData) -> bool | None:
    reasons = unsecured_reasons(data)
    return None if reasons is None else bool(reasons)


def _parked_unsecured_attributes(data: VehicleData) -> dict[str, Any]:
    return {
        "reasons": unsecured_reasons(data) or [],
        "reported_at": data.section_timestamp(SECTION_STATUS),
    }


def _plug_unlocked(data: VehicleData) -> bool | None:
    locked = data.flag(
        SECTION_CHARGING, "status", "plugLockState", on="locked", off="unlocked"
    )
    return None if locked is None else not locked


BINARY_SENSORS: tuple[SkodaApiBinarySensorDescription, ...] = (
    # --------------------------------------------------------------- status
    SkodaApiBinarySensorDescription(
        key="vehicle_lock",
        translation_key="vehicle_lock",
        section=SECTION_STATUS,
        device_class=BinarySensorDeviceClass.LOCK,
        is_on_fn=_unlocked,
    ),
    SkodaApiBinarySensorDescription(
        key="doors_open",
        translation_key="doors_open",
        section=SECTION_STATUS,
        device_class=BinarySensorDeviceClass.DOOR,
        is_on_fn=_open("overall", "doors"),
    ),
    SkodaApiBinarySensorDescription(
        key="windows_open",
        translation_key="windows_open",
        section=SECTION_STATUS,
        device_class=BinarySensorDeviceClass.WINDOW,
        exists_fn=_reports("overall", "windows"),
        is_on_fn=_open("overall", "windows"),
    ),
    SkodaApiBinarySensorDescription(
        key="trunk_open",
        translation_key="trunk_open",
        section=SECTION_STATUS,
        device_class=BinarySensorDeviceClass.OPENING,
        is_on_fn=_open("detail", "trunk"),
    ),
    SkodaApiBinarySensorDescription(
        key="bonnet_open",
        translation_key="bonnet_open",
        section=SECTION_STATUS,
        device_class=BinarySensorDeviceClass.OPENING,
        is_on_fn=_open("detail", "bonnet"),
    ),
    SkodaApiBinarySensorDescription(
        key="sunroof_open",
        translation_key="sunroof_open",
        section=SECTION_STATUS,
        device_class=BinarySensorDeviceClass.OPENING,
        exists_fn=_reports("detail", "sunroof"),
        is_on_fn=_open("detail", "sunroof"),
    ),
    SkodaApiBinarySensorDescription(
        key="lights_on",
        translation_key="lights_on",
        section=SECTION_STATUS,
        is_on_fn=lambda d: d.flag(
            SECTION_STATUS, "overall", "lights", on="on", off="off"
        ),
    ),
    SkodaApiBinarySensorDescription(
        key="vehicle_in_motion",
        translation_key="vehicle_in_motion",
        section=SECTION_PARKING,
        device_class=BinarySensorDeviceClass.MOVING,
        is_on_fn=_in_motion,
    ),
    SkodaApiBinarySensorDescription(
        key="parked_unsecured",
        translation_key="parked_unsecured",
        device_class=BinarySensorDeviceClass.SAFETY,
        # Not tied to the status part: without it the state is unknown.
        exists_fn=lambda d: d.has(SECTION_STATUS),
        is_on_fn=_parked_unsecured,
        attributes_fn=_parked_unsecured_attributes,
    ),
    # ------------------------------------------------------------- charging
    SkodaApiBinarySensorDescription(
        key="charging",
        translation_key="charging",
        section=SECTION_CHARGING,
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        is_on_fn=lambda d: d.is_charging,
    ),
    SkodaApiBinarySensorDescription(
        key="charger_connected",
        translation_key="charger_connected",
        section=SECTION_CHARGING,
        device_class=BinarySensorDeviceClass.PLUG,
        is_on_fn=lambda d: d.plug_connected,
    ),
    SkodaApiBinarySensorDescription(
        key="charger_lock",
        translation_key="charger_lock",
        section=SECTION_CHARGING,
        device_class=BinarySensorDeviceClass.LOCK,
        exists_fn=lambda d: (
            d.text(SECTION_CHARGING, "status", "plugLockState") is not None
        ),
        is_on_fn=_plug_unlocked,
    ),
    SkodaApiBinarySensorDescription(
        key="in_saved_location",
        translation_key="in_saved_location",
        section=SECTION_CHARGING,
        is_on_fn=lambda d: d.boolean(SECTION_CHARGING, "isVehicleInSavedLocation"),
    ),
    SkodaApiBinarySensorDescription(
        key="battery_care_mode",
        translation_key="battery_care_mode",
        section=SECTION_CHARGING,
        entity_category=EntityCategory.DIAGNOSTIC,
        exists_fn=lambda d: (
            d.text(SECTION_CHARGING, "settings", "chargingCareMode") is not None
        ),
        is_on_fn=lambda d: d.flag(
            SECTION_CHARGING,
            "settings",
            "chargingCareMode",
            on="activated",
            off="deactivated",
        ),
    ),
    SkodaApiBinarySensorDescription(
        key="auto_unlock_plug",
        translation_key="auto_unlock_plug",
        section=SECTION_CHARGING,
        entity_category=EntityCategory.DIAGNOSTIC,
        exists_fn=lambda d: (
            d.text(SECTION_CHARGING, "settings", "autoUnlockPlugWhenCharged")
            is not None
        ),
        is_on_fn=lambda d: d.flag(
            SECTION_CHARGING,
            "settings",
            "autoUnlockPlugWhenCharged",
            on="permanent",
            off="off",
        ),
    ),
    # -------------------------------------------------------------- climate
    SkodaApiBinarySensorDescription(
        key="window_heating_front",
        translation_key="window_heating_front",
        section=SECTION_AIR_CONDITIONING,
        exists_fn=lambda d: (
            d.flag(
                SECTION_AIR_CONDITIONING, "windowHeating", "front", on="on", off="off"
            )
            is not None
        ),
        is_on_fn=lambda d: d.flag(
            SECTION_AIR_CONDITIONING, "windowHeating", "front", on="on", off="off"
        ),
    ),
    SkodaApiBinarySensorDescription(
        key="window_heating_rear",
        translation_key="window_heating_rear",
        section=SECTION_AIR_CONDITIONING,
        exists_fn=lambda d: (
            d.flag(
                SECTION_AIR_CONDITIONING, "windowHeating", "rear", on="on", off="off"
            )
            is not None
        ),
        is_on_fn=lambda d: d.flag(
            SECTION_AIR_CONDITIONING, "windowHeating", "rear", on="on", off="off"
        ),
    ),
    SkodaApiBinarySensorDescription(
        key="window_heating_enabled",
        translation_key="window_heating_enabled",
        section=SECTION_AIR_CONDITIONING,
        entity_category=EntityCategory.DIAGNOSTIC,
        exists_fn=lambda d: (
            d.boolean(SECTION_AIR_CONDITIONING, "windowHeating", "enabled") is not None
        ),
        is_on_fn=lambda d: d.boolean(
            SECTION_AIR_CONDITIONING, "windowHeating", "enabled"
        ),
    ),
    SkodaApiBinarySensorDescription(
        key="ac_at_unlock",
        translation_key="ac_at_unlock",
        section=SECTION_AIR_CONDITIONING,
        entity_category=EntityCategory.DIAGNOSTIC,
        exists_fn=lambda d: (
            d.boolean(SECTION_AIR_CONDITIONING, "airConditioningAtUnlock") is not None
        ),
        is_on_fn=lambda d: d.boolean(
            SECTION_AIR_CONDITIONING, "airConditioningAtUnlock"
        ),
    ),
    SkodaApiBinarySensorDescription(
        key="ac_without_external_power",
        translation_key="ac_without_external_power",
        section=SECTION_AIR_CONDITIONING,
        entity_category=EntityCategory.DIAGNOSTIC,
        exists_fn=lambda d: (
            d.boolean(SECTION_AIR_CONDITIONING, "airConditioningWithoutExternalPower")
            is not None
        ),
        is_on_fn=lambda d: d.boolean(
            SECTION_AIR_CONDITIONING, "airConditioningWithoutExternalPower"
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SkodaApiConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensors of a vehicle."""
    async_add_when_available(
        entry,
        async_add_entities,
        described_candidates(entry.runtime_data, BINARY_SENSORS, SkodaApiBinarySensor),
    )


class SkodaApiBinarySensor(SkodaApiEntity, BinarySensorEntity):
    """A binary sensor of a vehicle."""

    entity_description: SkodaApiBinarySensorDescription

    @property
    def is_on(self) -> bool | None:
        """Return the state, or None while the vehicle does not report it."""
        return self.entity_description.is_on_fn(self.vehicle)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the extra details of binary sensors that have some."""
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.vehicle)
