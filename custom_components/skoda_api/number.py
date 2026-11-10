"""Number entities of the MyŠkoda Public API integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import commands
from .const import (
    CONF_ACTIVE_POLL_INTERVAL,
    CONF_AUTO_WAKE_MINUTES,
    CONF_POLL_INTERVAL,
    DEFAULT_ACTIVE_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    MAX_AUTO_WAKE_MINUTES,
    MAX_POLL_INTERVAL,
    MIN_AUTO_WAKE_MINUTES,
    MIN_POLL_INTERVAL,
    OP_SET_CHARGE_MODE,
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
class SettingNumberDescription(SkodaApiNumberDescription):
    """Describe a number that changes an option of the integration."""

    default: int


_MINUTES = {
    "entity_category": EntityCategory.CONFIG,
    "native_unit_of_measurement": UnitOfTime.MINUTES,
    "native_step": 1,
    "mode": NumberMode.BOX,
}

SETTING_NUMBERS: tuple[SettingNumberDescription, ...] = (
    SettingNumberDescription(
        key=CONF_POLL_INTERVAL,
        translation_key="poll_interval",
        native_min_value=MIN_POLL_INTERVAL,
        native_max_value=MAX_POLL_INTERVAL,
        default=DEFAULT_POLL_INTERVAL,
        **_MINUTES,
    ),
    SettingNumberDescription(
        key=CONF_ACTIVE_POLL_INTERVAL,
        translation_key="active_poll_interval",
        native_min_value=MIN_POLL_INTERVAL,
        native_max_value=MAX_POLL_INTERVAL,
        default=DEFAULT_ACTIVE_POLL_INTERVAL,
        **_MINUTES,
    ),
    SettingNumberDescription(
        key=CONF_AUTO_WAKE_MINUTES,
        translation_key="auto_wake_minutes",
        section=SECTION_CHARGING,
        # A wake re-sends the charge mode.
        operations=(OP_SET_CHARGE_MODE,),
        exists_fn=lambda d: d.charge_mode_setting is not None,
        # 0 switches the automatic wake off.
        native_min_value=0,
        native_max_value=MAX_AUTO_WAKE_MINUTES,
        default=0,
        **_MINUTES,
    ),
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
        described_candidates(coordinator, SETTING_NUMBERS, SettingNumber),
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


class SettingNumber(SkodaApiEntity, NumberEntity):
    """An option of the integration, changed from the device page."""

    entity_description: SettingNumberDescription

    @property
    def available(self) -> bool:
        """Stay usable after a failed update; the option is local."""
        return True

    @property
    def native_value(self) -> float:
        """Return the stored option."""
        description = self.entity_description
        return self.coordinator.config_entry.options.get(
            description.key, description.default
        )

    async def async_set_native_value(self, value: float) -> None:
        """Store the option."""
        minutes = round(value)
        if self.entity_description.key == CONF_AUTO_WAKE_MINUTES and (
            0 < minutes < MIN_AUTO_WAKE_MINUTES
        ):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="auto_wake_range",
                translation_placeholders={
                    "min": str(MIN_AUTO_WAKE_MINUTES),
                    "max": str(MAX_AUTO_WAKE_MINUTES),
                },
            )
        self.coordinator.async_set_option(self.entity_description.key, minutes)


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
