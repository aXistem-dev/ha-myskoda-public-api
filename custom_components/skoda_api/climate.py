"""Climate entity of the MyŠkoda Public API integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityDescription,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import (
    ATTR_TEMPERATURE,
    MAJOR_VERSION,
    MINOR_VERSION,
    PRECISION_HALVES,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import commands
from .const import (
    OP_START_AIR_CONDITIONING,
    OP_STOP_AIR_CONDITIONING,
    SECTION_AIR_CONDITIONING,
)
from .coordinator import SkodaApiConfigEntry
from .entity import (
    SkodaApiDescription,
    SkodaApiEntity,
    async_add_when_available,
    described_candidates,
)

PARALLEL_UPDATES = 1

# Home Assistant 2026.11 renamed the climate unit and target temperature.
_NATIVE_NAMES = (MAJOR_VERSION, MINOR_VERSION) >= (2026, 11)

_ACTIONS = {
    "off": HVACAction.OFF,
    "cooling": HVACAction.COOLING,
    "heating": HVACAction.HEATING,
    "heating_auxiliary": HVACAction.HEATING,
    "ventilation": HVACAction.FAN,
    "completed": HVACAction.IDLE,
}


@dataclass(frozen=True, kw_only=True)
class SkodaApiClimateDescription(SkodaApiDescription, ClimateEntityDescription):
    """Describe a climate entity."""


AIR_CONDITIONING = SkodaApiClimateDescription(
    key=commands.KEY_CLIMATE,
    translation_key="climate",
    section=SECTION_AIR_CONDITIONING,
    operations=(OP_START_AIR_CONDITIONING, OP_STOP_AIR_CONDITIONING),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SkodaApiConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the air conditioning of a vehicle."""
    async_add_when_available(
        entry,
        async_add_entities,
        described_candidates(entry.runtime_data, (AIR_CONDITIONING,), AirConditioning),
    )


class AirConditioning(SkodaApiEntity, ClimateEntity):
    """Pre-heat or pre-cool the cabin towards a target temperature."""

    entity_description: SkodaApiClimateDescription

    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT_COOL]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    if _NATIVE_NAMES:
        _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    else:
        _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_precision = PRECISION_HALVES
    _attr_target_temperature_step = 0.5
    _attr_min_temp = 15.5
    _attr_max_temp = 30

    # The API takes a temperature only with a start; kept until then.
    _chosen_temperature: float | None = None

    @property
    def _state(self) -> str | None:
        return self.vehicle.text(SECTION_AIR_CONDITIONING, "state")

    @property
    def _running(self) -> bool | None:
        return self.pending(self.vehicle.running(SECTION_AIR_CONDITIONING))

    @callback
    def _handle_coordinator_update(self) -> None:
        if self.vehicle.running(SECTION_AIR_CONDITIONING):
            # It runs, however it was started: the vehicle's target counts.
            self._chosen_temperature = None
        super()._handle_coordinator_update()

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return whether the air conditioning runs."""
        running = self._running
        if running is None:
            return None
        return HVACMode.HEAT_COOL if running else HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return what the air conditioning is doing right now."""
        running = self._running
        if running is False:
            return HVACAction.OFF
        action = _ACTIONS.get(self._state or "")
        if running and action in (HVACAction.OFF, HVACAction.IDLE):
            # Started, but the vehicle has not reported what it does yet.
            return None
        return action

    def _target_temperature(self) -> float | None:
        """Return the target temperature."""
        value = self.coordinator.optimistic(commands.KEY_CLIMATE_TEMPERATURE)
        if isinstance(value, int | float):
            return value
        if self._chosen_temperature is not None and not self._running:
            return self._chosen_temperature
        return self.vehicle.target_temperature

    if _NATIVE_NAMES:
        native_target_temperature = property(_target_temperature)
    else:
        target_temperature = property(_target_temperature)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the target temperature; applied at once while running."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        if self._running:
            self._chosen_temperature = None
            await commands.async_start_air_conditioning(
                self.coordinator, temperature=temperature
            )
        else:
            self._chosen_temperature = temperature
            self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Start or stop the air conditioning."""
        if hvac_mode == HVACMode.OFF:
            await commands.async_stop_air_conditioning(self.coordinator)
            return
        temperature, self._chosen_temperature = self._chosen_temperature, None
        await commands.async_start_air_conditioning(
            self.coordinator, temperature=temperature
        )

    async def async_turn_on(self) -> None:
        """Start the air conditioning."""
        await self.async_set_hvac_mode(HVACMode.HEAT_COOL)

    async def async_turn_off(self) -> None:
        """Stop the air conditioning."""
        await self.async_set_hvac_mode(HVACMode.OFF)
