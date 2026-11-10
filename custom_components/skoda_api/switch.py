"""Switches of the MyŠkoda Public API integration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import commands
from .const import (
    CONF_FAST_POLL_WHEN_PLUGGED,
    OP_START_ACTIVE_VENTILATION,
    OP_START_AUXILIARY_HEATING,
    OP_START_CHARGING,
    OP_STOP_ACTIVE_VENTILATION,
    OP_STOP_AUXILIARY_HEATING,
    OP_STOP_CHARGING,
    SECTION_ACTIVE_VENTILATION,
    SECTION_AUXILIARY_HEATING,
    SECTION_CHARGING,
    SECTION_CHARGING_PROFILES,
)
from .coordinator import SkodaApiConfigEntry, SkodaApiCoordinator
from .data import VehicleData
from .entity import (
    FIELD_TIMERS,
    FIELD_TIMES,
    ChargingProfileEntity,
    ChargingProfileItemEntity,
    ProfileItemDescription,
    SkodaApiDescription,
    SkodaApiEntity,
    async_add_when_available,
    described_candidates,
    profile_candidates,
    profile_item_candidates,
)

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class SkodaApiSwitchDescription(SkodaApiDescription, SwitchEntityDescription):
    """Describe a switch."""

    is_on_fn: Callable[[VehicleData], bool | None]
    turn_on_fn: Callable[[SkodaApiCoordinator], Awaitable[None]]
    turn_off_fn: Callable[[SkodaApiCoordinator], Awaitable[None]]
    attributes_fn: Callable[[VehicleData], dict[str, Any]] | None = None


def _auxiliary_heating_attributes(data: VehicleData) -> dict[str, Any]:
    seconds = data.number(SECTION_AUXILIARY_HEATING, "durationInSeconds")
    return {
        "start_mode": data.text(SECTION_AUXILIARY_HEATING, "startMode"),
        "duration": None if seconds is None else round(seconds / 60),
        "target_temperature": data.section_celsius(SECTION_AUXILIARY_HEATING),
    }


SWITCHES: tuple[SkodaApiSwitchDescription, ...] = (
    SkodaApiSwitchDescription(
        key=commands.KEY_CHARGING,
        translation_key="charging",
        section=SECTION_CHARGING,
        operations=(OP_START_CHARGING, OP_STOP_CHARGING),
        is_on_fn=lambda d: d.is_charging,
        turn_on_fn=lambda c: commands.async_set_charging(c, True),
        turn_off_fn=lambda c: commands.async_set_charging(c, False),
    ),
    SkodaApiSwitchDescription(
        key=commands.KEY_ACTIVE_VENTILATION,
        translation_key="active_ventilation",
        section=SECTION_ACTIVE_VENTILATION,
        operations=(OP_START_ACTIVE_VENTILATION, OP_STOP_ACTIVE_VENTILATION),
        is_on_fn=lambda d: d.running(SECTION_ACTIVE_VENTILATION),
        turn_on_fn=lambda c: commands.async_set_active_ventilation(c, True),
        turn_off_fn=lambda c: commands.async_set_active_ventilation(c, False),
    ),
    SkodaApiSwitchDescription(
        key=commands.KEY_AUXILIARY_HEATING,
        translation_key="auxiliary_heating",
        section=SECTION_AUXILIARY_HEATING,
        operations=(OP_START_AUXILIARY_HEATING, OP_STOP_AUXILIARY_HEATING),
        is_on_fn=lambda d: d.running(SECTION_AUXILIARY_HEATING),
        turn_on_fn=commands.async_start_auxiliary_heating,
        turn_off_fn=commands.async_stop_auxiliary_heating,
        attributes_fn=_auxiliary_heating_attributes,
    ),
)


@dataclass(frozen=True, kw_only=True)
class SettingSwitchDescription(SkodaApiDescription, SwitchEntityDescription):
    """Describe a switch that changes an option of the integration."""


FAST_POLL_WHEN_PLUGGED = SettingSwitchDescription(
    key=CONF_FAST_POLL_WHEN_PLUGGED,
    translation_key="fast_poll_when_plugged",
    entity_category=EntityCategory.CONFIG,
    # Only vehicles with a charging cable have something to plug in.
    exists_fn=lambda d: d.has(SECTION_CHARGING),
)


@dataclass(frozen=True, kw_only=True)
class ProfileSwitchDescription(SkodaApiDescription, SwitchEntityDescription):
    """Describe a switch of a charging profile."""

    path: tuple[str, ...]
    on_value: Any = True
    off_value: Any = False


PROFILE_SWITCHES: tuple[ProfileSwitchDescription, ...] = (
    ProfileSwitchDescription(
        key="auto_unlock_plug",
        translation_key="charging_profile_auto_unlock_plug",
        section=SECTION_CHARGING_PROFILES,
        entity_category=EntityCategory.CONFIG,
        path=("autoUnlockPlugWhenCharged",),
        on_value="PERMANENT",
        off_value="OFF",
    ),
    ProfileSwitchDescription(
        key="min_battery_enabled",
        translation_key="charging_profile_min_battery_enabled",
        section=SECTION_CHARGING_PROFILES,
        entity_category=EntityCategory.CONFIG,
        path=("minBatteryStateOfCharge", "enabled"),
    ),
)


@dataclass(frozen=True, kw_only=True)
class ProfileItemSwitchDescription(ProfileItemDescription, SwitchEntityDescription):
    """Describe the on/off switch of a timer or a preferred charging time."""


PROFILE_ITEM_SWITCHES: tuple[ProfileItemSwitchDescription, ...] = (
    ProfileItemSwitchDescription(
        key="enabled",
        translation_key="charging_profile_timer",
        section=SECTION_CHARGING_PROFILES,
        entity_category=EntityCategory.CONFIG,
        field=FIELD_TIMERS,
        kind="timer",
        value_key="enabled",
    ),
    ProfileItemSwitchDescription(
        key="enabled",
        translation_key="charging_profile_time",
        section=SECTION_CHARGING_PROFILES,
        entity_category=EntityCategory.CONFIG,
        field=FIELD_TIMES,
        kind="time",
        value_key="enabled",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SkodaApiConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the switches of a vehicle."""
    coordinator = entry.runtime_data
    async_add_when_available(
        entry,
        async_add_entities,
        described_candidates(coordinator, SWITCHES, SkodaApiSwitch),
        described_candidates(coordinator, (FAST_POLL_WHEN_PLUGGED,), SettingSwitch),
        profile_candidates(coordinator, PROFILE_SWITCHES, ChargingProfileSwitch),
        profile_item_candidates(
            coordinator, PROFILE_ITEM_SWITCHES, ChargingProfileItemSwitch
        ),
    )


class SkodaApiSwitch(SkodaApiEntity, SwitchEntity):
    """A switch that starts and stops something in the vehicle."""

    entity_description: SkodaApiSwitchDescription

    @property
    def is_on(self) -> bool | None:
        """Return the state; a pending command shows its expected result."""
        return self.pending(self.entity_description.is_on_fn(self.vehicle))

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the extra details of switches that have some."""
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.vehicle)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Send the start command."""
        await self.entity_description.turn_on_fn(self.coordinator)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Send the stop command."""
        await self.entity_description.turn_off_fn(self.coordinator)


class SettingSwitch(SkodaApiEntity, SwitchEntity):
    """An on/off option of the integration, changed from the device page."""

    entity_description: SettingSwitchDescription

    @property
    def available(self) -> bool:
        """Stay usable after a failed update; the option is local."""
        return True

    @property
    def is_on(self) -> bool:
        """Return the stored option."""
        return bool(
            self.coordinator.config_entry.options.get(
                self.entity_description.key, False
            )
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Switch the option on."""
        self.coordinator.async_set_option(self.entity_description.key, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Switch the option off."""
        self.coordinator.async_set_option(self.entity_description.key, False)


class ChargingProfileSwitch(ChargingProfileEntity, SwitchEntity):
    """An on/off setting of a charging profile."""

    entity_description: ProfileSwitchDescription

    @property
    def is_on(self) -> bool | None:
        """Return the setting; a pending change shows its expected result."""
        description = self.entity_description
        value = self.setting(*description.path)
        if isinstance(value, str):
            value = value.upper()
        if value == description.on_value:
            reported: bool | None = True
        elif value == description.off_value:
            reported = False
        else:
            reported = None
        return self.pending(reported)

    async def _async_set(self, on: bool) -> None:
        description = self.entity_description
        changes: Any = description.on_value if on else description.off_value
        for key in reversed(description.path):
            changes = {key: changes}
        await self.async_update_settings(changes, on)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Switch the setting on."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Switch the setting off."""
        await self._async_set(False)


class ChargingProfileItemSwitch(ChargingProfileItemEntity, SwitchEntity):
    """Whether a timer or a preferred charging time of a profile is in use."""

    entity_description: ProfileItemSwitchDescription

    @property
    def is_on(self) -> bool | None:
        """Return the state; a pending change shows its expected result."""
        value = (self.item or {}).get("enabled")
        return self.pending(value if isinstance(value, bool) else None)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return when the timer or charging time applies."""
        item = self.item or {}
        attributes = super().extra_state_attributes
        if self.field == FIELD_TIMERS:
            attributes |= {
                "time": item.get("time"),
                "type": str(item.get("type") or "").lower() or None,
                "one_off_day": str(item.get("oneOffDay") or "").lower() or None,
                "recurring_on": [
                    str(day).lower() for day in item.get("recurringOn") or []
                ],
            }
        else:
            attributes |= {
                "start_time": item.get("startTime"),
                "end_time": item.get("endTime"),
            }
        return attributes

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Put the timer or charging time to use."""
        await self.async_update_item({"enabled": True}, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Take the timer or charging time out of use."""
        await self.async_update_item({"enabled": False}, False)
