"""Serve the dashboard strategy to the Home Assistant frontend."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import DOMAIN

URL_BASE = f"/{DOMAIN}"
STRATEGY_FILE = "skoda-api-strategy.js"


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Make the strategy module available and have the frontend load it."""
    if hass.http is None or "frontend" not in hass.config.components:
        return
    integration = await async_get_integration(hass, DOMAIN)
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                URL_BASE, str(Path(__file__).parent / "frontend"), cache_headers=False
            )
        ]
    )
    # The version in the address makes browsers fetch a new release.
    add_extra_js_url(hass, f"{URL_BASE}/{STRATEGY_FILE}?v={integration.version}")
