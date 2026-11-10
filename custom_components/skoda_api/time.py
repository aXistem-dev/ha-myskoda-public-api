"""Time entities of the MyŠkoda Public API integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time

from homeassistant.components.time import TimeEntity, TimeEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import SECTION_CHARGING_PROFILES
from .coordinator import SkodaApiConfigEntry
from .entity import (
    FIELD_TIMERS,
    FIELD_TIMES,
    ChargingProfileItemEntity,
    ProfileItemDescription,
    async_add_when_available,
    profile_item_candidates,
)

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class ProfileItemTimeDescription(ProfileItemDescription, TimeEntityDescription):
    """Describe a time of a timer or a preferred charging time."""


PROFILE_ITEM_TIMES: tuple[ProfileItemTimeDescription, ...] = (
    ProfileItemTimeDescription(
        key="time",
        translation_key="charging_profile_timer_time",
        section=SECTION_CHARGING_PROFILES,
        entity_category=EntityCategory.CONFIG,
        field=FIELD_TIMERS,
        kind="timer",
        value_key="time",
    ),
    ProfileItemTimeDescription(
        key="start",
        translation_key="charging_profile_time_start",
        section=SECTION_CHARGING_PROFILES,
        entity_category=EntityCategory.CONFIG,
        field=FIELD_TIMES,
        kind="time",
        value_key="startTime",
    ),
    ProfileItemTimeDescription(
        key="end",
        translation_key="charging_profile_time_end",
        section=SECTION_CHARGING_PROFILES,
        entity_category=EntityCategory.CONFIG,
        field=FIELD_TIMES,
        kind="time",
        value_key="endTime",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SkodaApiConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the times of the charging profiles of a vehicle."""
    async_add_when_available(
        entry,
        async_add_entities,
        profile_item_candidates(
            entry.runtime_data, PROFILE_ITEM_TIMES, ChargingProfileItemTime
        ),
    )


def _parse(value: object) -> time | None:
    """Read a time of day as the API writes it (HH:mm)."""
    if not isinstance(value, str):
        return None
    try:
        return time.fromisoformat(value)
    except ValueError:
        return None


class ChargingProfileItemTime(ChargingProfileItemEntity, TimeEntity):
    """A time of a timer or charging time, in the vehicle's local time."""

    entity_description: ProfileItemTimeDescription

    @property
    def native_value(self) -> time | None:
        """Return the time; a pending change shows its expected result."""
        value = (self.item or {}).get(self.entity_description.value_key)
        return self.pending(_parse(value))

    async def async_set_value(self, value: time) -> None:
        """Send the profile with the new time."""
        shown = value.replace(second=0, microsecond=0)
        await self.async_update_item(
            {self.entity_description.value_key: shown.strftime("%H:%M")}, shown
        )
