"""Select entities of the MyŠkoda Public API integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import commands
from .const import (
    CHARGE_MODES,
    OP_SET_CHARGE_MODE,
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
class SkodaApiSelectDescription(SkodaApiDescription, SelectEntityDescription):
    """Describe a select."""


CHARGE_MODE = SkodaApiSelectDescription(
    key=commands.KEY_CHARGE_MODE,
    translation_key="charge_mode",
    section=SECTION_CHARGING,
    operations=(OP_SET_CHARGE_MODE,),
)

PROFILE_MAX_CURRENT = SkodaApiSelectDescription(
    key="max_current",
    translation_key="charging_profile_max_current",
    section=SECTION_CHARGING_PROFILES,
    entity_category=EntityCategory.CONFIG,
    options=["maximum", "reduced"],
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SkodaApiConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the selects of a vehicle."""
    coordinator = entry.runtime_data
    async_add_when_available(
        entry,
        async_add_entities,
        described_candidates(coordinator, (CHARGE_MODE,), ChargeMode),
        profile_candidates(
            coordinator, (PROFILE_MAX_CURRENT,), ChargingProfileMaxCurrent
        ),
    )


class ChargeMode(SkodaApiEntity, SelectEntity):
    """How the vehicle decides when to charge."""

    entity_description: SkodaApiSelectDescription

    @property
    def options(self) -> list[str]:
        """Return the modes this vehicle offers."""
        available = self.vehicle.get(
            SECTION_CHARGING, "settings", "availableChargeModes"
        )
        modes = [
            mode.lower()
            for mode in (available if isinstance(available, list) else [])
            if isinstance(mode, str) and mode.lower() in CHARGE_MODES
        ]
        current = self.current_option
        if current is not None and current not in modes:
            modes.append(current)
        return modes

    @property
    def current_option(self) -> str | None:
        """Return the mode; a pending change shows its expected result."""
        mode = self.pending(
            self.vehicle.text(SECTION_CHARGING, "settings", "preferredChargeMode")
        )
        # The API may add modes over time; an unknown one is no state.
        return mode if mode in CHARGE_MODES else None

    async def async_select_option(self, option: str) -> None:
        """Send the new mode to the vehicle."""
        await commands.async_set_charge_mode(self.coordinator, option)


class ChargingProfileMaxCurrent(ChargingProfileEntity, SelectEntity):
    """The charging current of a charging profile."""

    entity_description: SkodaApiSelectDescription

    @property
    def current_option(self) -> str | None:
        """Return the setting; a pending change shows its expected result."""
        value = self.setting("maxChargingCurrent")
        value = self.pending(value.lower() if isinstance(value, str) else None)
        return value if value in (self.entity_description.options or ()) else None

    async def async_select_option(self, option: str) -> None:
        """Send the profile with the new current."""
        await self.async_update_settings({"maxChargingCurrent": option.upper()}, option)
