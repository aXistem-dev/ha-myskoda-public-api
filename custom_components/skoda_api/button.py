"""Buttons of the MyŠkoda Public API integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import OP_SET_CHARGE_MODE, SECTION_CHARGING
from .coordinator import SkodaApiConfigEntry
from .entity import (
    SkodaApiDescription,
    SkodaApiEntity,
    async_add_when_available,
    described_candidates,
)

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class SkodaApiButtonDescription(SkodaApiDescription, ButtonEntityDescription):
    """Describe a button."""


REFRESH = SkodaApiButtonDescription(
    key="refresh",
    translation_key="refresh",
    entity_category=EntityCategory.DIAGNOSTIC,
)

WAKE = SkodaApiButtonDescription(
    key="wake",
    translation_key="wake",
    section=SECTION_CHARGING,
    # The wake re-sends the current charge mode.
    operations=(OP_SET_CHARGE_MODE,),
    exists_fn=lambda d: d.charge_mode_setting is not None,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SkodaApiConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the buttons of a vehicle."""
    async_add_when_available(
        entry,
        async_add_entities,
        described_candidates(entry.runtime_data, (REFRESH,), RefreshButton),
        described_candidates(entry.runtime_data, (WAKE,), WakeButton),
    )


class RefreshButton(SkodaApiEntity, ButtonEntity):
    """Fetch the vehicle data now instead of at the next poll."""

    entity_description: SkodaApiButtonDescription

    @property
    def available(self) -> bool:
        """Stay usable after a failed update, to try again."""
        return True

    async def async_press(self) -> None:
        """Fetch the data; this uses one request of the hourly quota."""
        await self.coordinator.async_force_refresh()


class WakeButton(SkodaApiEntity, ButtonEntity):
    """Make the vehicle report fresh data."""

    entity_description: SkodaApiButtonDescription

    async def async_press(self) -> None:
        """Send the current charge mode again; a command of the hourly quota."""
        await self.coordinator.async_wake()
