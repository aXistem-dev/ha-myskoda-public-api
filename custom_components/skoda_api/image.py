"""Vehicle picture of the MyŠkoda Public API integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.image import ImageEntity, ImageEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import SkodaApiConfigEntry, SkodaApiCoordinator
from .entity import (
    SkodaApiDescription,
    SkodaApiEntity,
    async_add_when_available,
    described_candidates,
)

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class SkodaApiImageDescription(SkodaApiDescription, ImageEntityDescription):
    """Describe an image."""


RENDER = SkodaApiImageDescription(
    key="render",
    translation_key="render",
    exists_fn=lambda d: d.render_url is not None,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SkodaApiConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the picture of a vehicle."""
    async_add_when_available(
        entry,
        async_add_entities,
        described_candidates(
            entry.runtime_data, (RENDER,), lambda c, d: VehicleRender(hass, c, d)
        ),
    )


class VehicleRender(SkodaApiEntity, ImageEntity):
    """The picture of the vehicle as shown in the MyŠkoda app."""

    entity_description: SkodaApiImageDescription

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: SkodaApiCoordinator,
        description: SkodaApiImageDescription,
    ) -> None:
        """Point the image at the address the API gives."""
        SkodaApiEntity.__init__(self, coordinator, description)
        ImageEntity.__init__(self, hass)
        self._attr_image_url = coordinator.data.render_url
        self._attr_image_last_updated = dt_util.utcnow()

    @callback
    def _handle_coordinator_update(self) -> None:
        url = self.vehicle.render_url
        if url is not None and url != self._attr_image_url:
            self._attr_image_url = url
            self._cached_image = None
            self._attr_image_last_updated = dt_util.utcnow()
        super()._handle_coordinator_update()
