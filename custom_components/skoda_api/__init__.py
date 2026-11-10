"""The MyŠkoda Public API integration."""

from __future__ import annotations

from homeassistant.const import CONF_API_KEY, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import (
    config_validation as cv,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .api import SkodaApiClient
from .button import WAKE
from .const import (
    API_BASE_URL,
    CONF_BASE_URL,
    DOMAIN,
    SETTING_KEYS,
)
from .coordinator import (
    SkodaApiConfigEntry,
    SkodaApiCoordinator,
    rate_limited_until,
    store_key,
)
from .frontend import async_register_frontend
from .sensor import SENSORS
from .services import async_setup_services

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.DEVICE_TRACKER,
    Platform.IMAGE,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TIME,
]

# Platforms that only hold controls, removed in read-only mode.
CONTROL_DOMAINS = {
    Platform.CLIMATE,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.TIME,
}

# A bare `skoda_api:` in YAML loads the integration, also without a vehicle.
CONFIG_SCHEMA = cv.empty_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions and the dashboard strategy."""
    async_setup_services(hass)
    await async_register_frontend(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SkodaApiConfigEntry) -> bool:
    """Set up a vehicle from a config entry."""
    client = SkodaApiClient(
        async_get_clientsession(hass),
        entry.data[CONF_API_KEY],
        entry.data.get(CONF_BASE_URL, API_BASE_URL),
    )
    if rate_limited_until(entry.entry_id) is not None:
        # The API said how long to wait; asking sooner would only use quota.
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN, translation_key="rate_limited"
        )
    coordinator = SkodaApiCoordinator(hass, entry, client)
    await coordinator.async_load_stored()
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        coordinator.close()
        raise
    entry.runtime_data = coordinator
    _async_remove_obsolete_entities(hass, entry, coordinator)
    entry.async_on_unload(coordinator.close)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


@callback
def _async_remove_obsolete_entities(
    hass: HomeAssistant, entry: SkodaApiConfigEntry, coordinator: SkodaApiCoordinator
) -> None:
    """Remove controls in read-only mode and sensors replaced by controls."""
    data = coordinator.data
    registry = er.async_get(hass)
    stand_ins = {
        f"{coordinator.vin}_{description.key}"
        for description in SENSORS
        if description.replaced_by and data.controllable(*description.replaced_by)
    }
    settings = {f"{coordinator.vin}_{key}" for key in SETTING_KEYS}
    wake = f"{coordinator.vin}_{WAKE.key}"
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.unique_id in settings:
            continue
        if (
            coordinator.readonly
            and (entity.domain in CONTROL_DOMAINS or entity.unique_id == wake)
        ) or (entity.domain == Platform.SENSOR and entity.unique_id in stand_ins):
            registry.async_remove(entity.entity_id)


async def async_remove_entry(hass: HomeAssistant, entry: SkodaApiConfigEntry) -> None:
    """Delete the response kept on disk for a removed vehicle."""
    coordinator = getattr(entry, "runtime_data", None)
    if isinstance(coordinator, SkodaApiCoordinator):
        await coordinator.async_remove_stored()
    else:
        await Store(hass, 1, store_key(entry.entry_id)).async_remove()


async def async_unload_entry(hass: HomeAssistant, entry: SkodaApiConfigEntry) -> bool:
    """Unload a vehicle."""
    ir.async_delete_issue(hass, DOMAIN, f"api_key_expiring_{entry.entry_id}")
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
