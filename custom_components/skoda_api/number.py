"""Number entities of the MyŠkoda Public API integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import commands
from .const import (
    OP_SET_CHARGING_LIMIT,
    SECTION_CHARGING,
    SECTION_CHARGING_PROFILES,
)
from .coordinator import SkodaApiConfigEntry
from .entity import (
    ChargingProfileEntity,
    SkodaApiDescription,
    SkodaApiEntity,
    async_add_when_available,
    described_candidates,
    profile_candidates,
)

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class SkodaApiNumberDescription(SkodaApiDescription, NumberEntityDescription):
    """Describe a number."""


CHARGE_LIMIT = SkodaApiNumberDescription(
    key=commands.KEY_CHARGE_LIMIT,
    translation_key="charge_limit",
    section=SECTION_CHARGING,
    operations=(OP_SET_CHARGING_LIMIT,),
    device_class=NumberDeviceClass.BATTERY,
    native_unit_of_measurement=PERCENTAGE,
    # Vehicles typically accept 50 to 100 in steps of 10 and reject the rest.
    native_min_value=50,
    native_max_value=100,
    native_step=10,
    mode=NumberMode.SLIDER,
)


@dataclass(frozen=True, kw_only=True)
class ProfileNumberDescription(SkodaApiDescription, NumberEntityDescription):
    """Describe a number of a charging profile."""

    path: tuple[str, ...]


PROFILE_NUMBERS: tuple[ProfileNumberDescription, ...] = (
    ProfileNumberDescription(
        key="target",
        translation_key="charging_profile_target",
        section=SECTION_CHARGING_PROFILES,
        entity_category=EntityCategory.CONFIG,
        device_class=NumberDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=50,
        native_max_value=100,
        native_step=10,
        mode=NumberMode.SLIDER,
        path=("targetStateOfChargeInPercent",),
    ),
    ProfileNumberDescription(
        key="min_battery",
        translation_key="charging_profile_min_battery",
        section=SECTION_CHARGING_PROFILES,
        entity_category=EntityCategory.CONFIG,
        device_class=NumberDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=0,
        native_max_value=100,
        native_step=5,
        mode=NumberMode.SLIDER,
        path=("minBatteryStateOfCharge", "minimumBatteryStateOfChargeInPercent"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SkodaApiConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the numbers of a vehicle."""
    coordinator = entry.runtime_data
    async_add_when_available(
        entry,
        async_add_entities,
        described_candidates(coordinator, (CHARGE_LIMIT,), ChargeLimit),
        profile_candidates(coordinator, PROFILE_NUMBERS, ChargingProfileNumber),
    )


class ChargeLimit(SkodaApiEntity, NumberEntity):
    """The state of charge at which the vehicle stops charging."""

    entity_description: SkodaApiNumberDescription

    @property
    def native_value(self) -> float | None:
        """Return the limit; a pending change shows its expected result."""
        return self.pending(
            self.vehicle.number(
                SECTION_CHARGING, "settings", "targetStateOfChargeInPercent"
            )
        )

    async def async_set_native_value(self, value: float) -> None:
        """Send the new limit to the vehicle."""
        await commands.async_set_charge_limit(self.coordinator, round(value))


class ChargingProfileNumber(ChargingProfileEntity, NumberEntity):
    """A percentage setting of a charging profile."""

    entity_description: ProfileNumberDescription

    @property
    def native_value(self) -> float | None:
        """Return the setting; a pending change shows its expected result."""
        value = self.setting(*self.entity_description.path)
        if isinstance(value, bool) or not isinstance(value, int | float):
            value = None
        return self.pending(value)

    async def async_set_native_value(self, value: float) -> None:
        """Send the profile with the new value."""
        changes: object = round(value)
        for key in reversed(self.entity_description.path):
            changes = {key: changes}
        await self.async_update_settings(changes, round(value))  # type: ignore[arg-type]
