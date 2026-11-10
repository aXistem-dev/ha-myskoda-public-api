"""Shared fixtures for the MyŠkoda Public API tests."""

from __future__ import annotations

from collections.abc import Generator
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.skoda_api.const import API_BASE_URL, CONF_VIN, DOMAIN

VIN = "TMBJB9NY5RF999999"
API_KEY = "test-api-key"
VEHICLE_URL = f"{API_BASE_URL}/api/v1/vehicles/{VIN}"
HEADERS = {
    "X-API-Key-Expires-At": "2099-01-01T00:00:00Z",
    "RateLimit-Limit": "20",
    "RateLimit-Remaining": "17",
    "RateLimit-Reset": "1800",
}


def load_fixture(name: str) -> dict[str, Any]:
    """Return a sample response of the vehicle endpoint."""
    path = Path(__file__).parent / "fixtures" / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load the integration under test."""


@pytest.fixture(autouse=True)
def mock_frontend() -> Generator[AsyncMock]:
    """Skip serving the dashboard strategy; there is no web server in tests."""
    with patch(
        "custom_components.skoda_api.async_register_frontend", AsyncMock()
    ) as mock:
        yield mock


def mock_vehicle(
    aioclient_mock: AiohttpClientMocker,
    fixture: str | dict[str, Any] = "enyaq",
    *,
    headers: dict[str, str] | None = None,
    status: int = 200,
) -> None:
    """Make the vehicle endpoint answer with a sample response."""
    aioclient_mock.clear_requests()
    payload = load_fixture(fixture) if isinstance(fixture, str) else fixture
    aioclient_mock.get(
        VEHICLE_URL, json=payload, status=status, headers=headers or HEADERS
    )


def mock_command(
    aioclient_mock: AiohttpClientMocker,
    method: str,
    path: str,
    *,
    status: int = 202,
    json: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> None:
    """Make a command endpoint answer."""
    getattr(aioclient_mock, method)(
        f"{VEHICLE_URL}/{path}", status=status, json=json, headers=headers or HEADERS
    )


def calls(aioclient_mock: AiohttpClientMocker, method: str, path: str = "") -> list:
    """Return the request bodies sent to an endpoint."""
    url = f"{VEHICLE_URL}/{path}" if path else VEHICLE_URL
    return [
        call[2]
        for call in aioclient_mock.mock_calls
        if call[0].lower() == method and str(call[1]).split("?")[0] == url
    ]


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Return a config entry for the sample vehicle."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Enyaq",
        unique_id=VIN,
        data={CONF_VIN: VIN, CONF_API_KEY: API_KEY},
    )


async def setup_integration(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    fixture: str | dict[str, Any] = "enyaq",
) -> MockConfigEntry:
    """Set the integration up against a sample response."""
    mock_vehicle(aioclient_mock, fixture)
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry
