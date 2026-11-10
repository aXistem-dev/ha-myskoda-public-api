"""Device tracker of the MyŠkoda Public API integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.device_tracker import (
    TrackerEntity,
    TrackerEntityDescription,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import SECTION_PARKING
from .coordinator import SkodaApiConfigEntry, SkodaApiCoordinator
from .entity import (
    SkodaApiDescription,
    SkodaApiEntity,
    async_add_when_available,
    described_candidates,
)

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class SkodaApiTrackerDescription(SkodaApiDescription, TrackerEntityDescription):
    """Describe a device tracker."""


PARKING_POSITION = SkodaApiTrackerDescription(
    key="parking_position",
    translation_key="parking_position",
    section=SECTION_PARKING,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SkodaApiConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the parking position of a vehicle."""
    async_add_when_available(
        entry,
        async_add_entities,
        described_candidates(entry.runtime_data, (PARKING_POSITION,), ParkingPosition),
    )


class ParkingPosition(SkodaApiEntity, TrackerEntity):
    """Where the vehicle was parked last."""

    entity_description: SkodaApiTrackerDescription
    _attr_name = None

    def __init__(
        self, coordinator: SkodaApiCoordinator, description: SkodaApiTrackerDescription
    ) -> None:
        """Remember the position while the vehicle is on the move."""
        super().__init__(coordinator, description)
        self._position: tuple[float, float] | None = None
        self._read_position()

    def _read_position(self) -> None:
        # The API reports coordinates only while the vehicle is parked.
        latitude = self.vehicle.number(SECTION_PARKING, "gpsCoordinates", "latitude")
        longitude = self.vehicle.number(SECTION_PARKING, "gpsCoordinates", "longitude")
        if latitude is not None and longitude is not None:
            self._position = (latitude, longitude)

    @callback
    def _handle_coordinator_update(self) -> None:
        self._read_position()
        super()._handle_coordinator_update()

    @property
    def latitude(self) -> float | None:
        """Return the latitude of the last parking position."""
        return self._position[0] if self._position else None

    @property
    def longitude(self) -> float | None:
        """Return the longitude of the last parking position."""
        return self._position[1] if self._position else None

    @property
    def entity_picture(self) -> str | None:
        """Show the vehicle picture on the map."""
        return self.vehicle.render_url

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the address and whether the vehicle is on the move."""
        return {
            "address": self.vehicle.get(SECTION_PARKING, "formattedAddress"),
            "in_motion": self.vehicle.flag(
                SECTION_PARKING, "state", on="in_motion", off="parked"
            ),
        }
