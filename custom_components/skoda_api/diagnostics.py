"""Diagnostics of the MyŠkoda Public API integration."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant

from .const import CONF_SPIN, CONF_VIN, SECTION_CHARGING_PROFILES
from .coordinator import SkodaApiConfigEntry

REDACTED = "**REDACTED**"
TO_REDACT = {
    CONF_API_KEY,
    CONF_SPIN,
    CONF_VIN,
    "vin",
    "licensePlate",
    "renderUrl",
    "gpsCoordinates",
    "formattedAddress",
    "latitude",
    "longitude",
    "title",
    "unique_id",
}


def _vehicle(raw: dict[str, Any]) -> dict[str, Any]:
    """Return the vehicle data without what identifies the car or its places."""
    vehicle = async_redact_data(deepcopy(raw), TO_REDACT)
    if "name" in vehicle:
        vehicle["name"] = REDACTED
    profiles = vehicle.get(SECTION_CHARGING_PROFILES)
    if isinstance(profiles, dict):
        named = [profiles.get("currentVehiclePositionProfile")]
        if isinstance(profiles.get("profiles"), list):
            named.extend(profiles["profiles"])
        for profile in named:
            if isinstance(profile, dict) and "name" in profile:
                profile["name"] = REDACTED
    return vehicle


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SkodaApiConfigEntry
) -> dict[str, Any]:
    """Return what the API sent last, without anything that identifies the car."""
    coordinator = entry.runtime_data
    client = coordinator.client
    limit = client.rate_limit
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "vehicle": _vehicle(coordinator.data.raw),
        "errors": coordinator.data.errors,
        "stale": sorted(coordinator.data.stale),
        "api": {
            "key_expires_at": (
                client.key_expires_at.isoformat() if client.key_expires_at else None
            ),
            "rate_limit": limit.limit if limit else None,
            "rate_limit_remaining": limit.remaining if limit else None,
            "rate_limit_reset_at": (
                limit.reset_at.isoformat() if limit and limit.reset_at else None
            ),
        },
        "last_update_success": coordinator.last_update_success,
        "poll_interval": str(coordinator.update_interval),
    }
