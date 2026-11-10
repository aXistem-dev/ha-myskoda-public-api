"""Remote commands shared by entities and actions."""

from __future__ import annotations

from homeassistant.exceptions import ServiceValidationError

from .const import (
    DOMAIN,
    SECTION_ACTIVE_VENTILATION,
    SECTION_AIR_CONDITIONING,
    SECTION_AUXILIARY_HEATING,
    SECTION_CHARGING,
)
from .coordinator import SkodaApiCoordinator

KEY_CHARGING = "charging_switch"
KEY_CHARGE_LIMIT = "charge_limit"
KEY_CHARGE_MODE = "charge_mode"
KEY_CLIMATE = "climate"
KEY_CLIMATE_TEMPERATURE = "climate_temperature"
KEY_AUXILIARY_HEATING = "auxiliary_heating"
KEY_ACTIVE_VENTILATION = "active_ventilation"


async def async_set_charging(coordinator: SkodaApiCoordinator, on: bool) -> None:
    """Start or stop charging."""
    if on and coordinator.data.plug_connected is False:
        # Without a cable the request would only cost quota.
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="cable_not_connected"
        )
    client, vin = coordinator.client, coordinator.vin
    await coordinator.async_command(
        (lambda: client.start_charging(vin))
        if on
        else (lambda: client.stop_charging(vin)),
        confirmed=lambda data: data.is_charging is on,
        optimistic={KEY_CHARGING: on},
    )


async def async_set_charge_limit(
    coordinator: SkodaApiCoordinator, percent: int
) -> None:
    """Set the target state of charge."""
    await coordinator.async_command(
        lambda: coordinator.client.set_charging_limit(coordinator.vin, percent),
        confirmed=lambda data: (
            data.number(SECTION_CHARGING, "settings", "targetStateOfChargeInPercent")
            == percent
        ),
        optimistic={KEY_CHARGE_LIMIT: percent},
    )


async def async_set_charge_mode(coordinator: SkodaApiCoordinator, mode: str) -> None:
    """Change the charge mode (lower-case value)."""
    await coordinator.async_command(
        lambda: coordinator.client.set_charge_mode(coordinator.vin, mode.upper()),
        confirmed=lambda data: (
            data.text(SECTION_CHARGING, "settings", "preferredChargeMode") == mode
        ),
        optimistic={KEY_CHARGE_MODE: mode},
    )


async def async_start_air_conditioning(
    coordinator: SkodaApiCoordinator,
    *,
    temperature: float | None = None,
    without_external_power: bool | None = None,
) -> None:
    """Start the air conditioning, optionally towards a temperature."""
    optimistic: dict[str, object] = {KEY_CLIMATE: True}
    if temperature is not None:
        optimistic[KEY_CLIMATE_TEMPERATURE] = temperature
    await coordinator.async_command(
        lambda: coordinator.client.start_air_conditioning(
            coordinator.vin,
            temperature=temperature,
            without_external_power=without_external_power,
        ),
        confirmed=lambda data: (
            data.running(SECTION_AIR_CONDITIONING) is True
            and (temperature is None or data.target_temperature == temperature)
        ),
        optimistic=optimistic,
    )


async def async_stop_air_conditioning(coordinator: SkodaApiCoordinator) -> None:
    """Stop the air conditioning."""
    await coordinator.async_command(
        lambda: coordinator.client.stop_air_conditioning(coordinator.vin),
        confirmed=lambda data: data.running(SECTION_AIR_CONDITIONING) is False,
        optimistic={KEY_CLIMATE: False},
    )


async def async_start_auxiliary_heating(
    coordinator: SkodaApiCoordinator,
    *,
    spin: str | None = None,
    duration_minutes: float | None = None,
    start_mode: str | None = None,
    temperature: float | None = None,
) -> None:
    """Start the auxiliary heater; uses the stored S-PIN unless one is given."""
    spin = spin or coordinator.spin
    if not spin:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="spin_required"
        )
    if duration_minutes is None:
        seconds = coordinator.data.number(
            SECTION_AUXILIARY_HEATING, "durationInSeconds"
        )
    else:
        seconds = duration_minutes * 60
    await coordinator.async_command(
        lambda: coordinator.client.start_auxiliary_heating(
            coordinator.vin,
            spin=spin,
            duration_seconds=int(seconds) if seconds else None,
            start_mode=start_mode.upper() if start_mode else None,
            temperature=temperature,
        ),
        confirmed=lambda data: data.running(SECTION_AUXILIARY_HEATING) is True,
        optimistic={KEY_AUXILIARY_HEATING: True},
    )


async def async_stop_auxiliary_heating(coordinator: SkodaApiCoordinator) -> None:
    """Stop the auxiliary heater."""
    await coordinator.async_command(
        lambda: coordinator.client.stop_auxiliary_heating(coordinator.vin),
        confirmed=lambda data: data.running(SECTION_AUXILIARY_HEATING) is False,
        optimistic={KEY_AUXILIARY_HEATING: False},
    )


async def async_set_active_ventilation(
    coordinator: SkodaApiCoordinator, on: bool
) -> None:
    """Start or stop the active ventilation."""
    client, vin = coordinator.client, coordinator.vin
    await coordinator.async_command(
        (lambda: client.start_active_ventilation(vin))
        if on
        else (lambda: client.stop_active_ventilation(vin)),
        confirmed=lambda data: data.running(SECTION_ACTIVE_VENTILATION) is on,
        optimistic={KEY_ACTIVE_VENTILATION: on},
    )
