"""Config flow of the MyŠkoda Public API integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
import re
from typing import Any

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_API_KEY
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
import voluptuous as vol

from .api import (
    PROBLEM_KEY_NOT_AUTHORIZED,
    SkodaApiAuthError,
    SkodaApiClient,
    SkodaApiConnectionError,
    SkodaApiError,
    SkodaApiNotFoundError,
    SkodaApiRateLimitError,
    SkodaApiServerError,
)
from .const import (
    API_BASE_URL,
    API_KEYS_URL,
    CONF_ACTIVE_POLL_INTERVAL,
    CONF_AUTO_WAKE_MINUTES,
    CONF_BASE_URL,
    CONF_FAST_POLL_WHEN_PLUGGED,
    CONF_POLL_INTERVAL,
    CONF_READONLY,
    CONF_SPIN,
    CONF_VIN,
    DEFAULT_ACTIVE_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    MAX_AUTO_WAKE_MINUTES,
    MAX_POLL_INTERVAL,
    MIN_AUTO_WAKE_MINUTES,
    MIN_POLL_INTERVAL,
)
from .coordinator import SkodaApiConfigEntry

_LOGGER = logging.getLogger(__name__)

_VIN = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
_SPIN = re.compile(r"^\d{4}$")

_SECRET = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
_URL = TextSelector(TextSelectorConfig(type=TextSelectorType.URL))
_PLACEHOLDERS = {"api_keys_url": API_KEYS_URL}

SECTION_ADVANCED = "advanced"


def _minutes(minimum: int, maximum: int) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=1,
            unit_of_measurement="min",
            mode=NumberSelectorMode.BOX,
        )
    )


class SkodaApiConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a vehicle with its VIN and an API key from the MyŠkoda app."""

    VERSION = 1

    async def _async_validate(
        self, vin: str, api_key: str, base_url: str
    ) -> tuple[str | None, str | None]:
        """Ask the API for the vehicle; return (vehicle name, error key)."""
        client = SkodaApiClient(async_get_clientsession(self.hass), api_key, base_url)
        try:
            payload = await client.get_vehicle(vin, include=["info"])
        except SkodaApiAuthError as err:
            if err.problem == PROBLEM_KEY_NOT_AUTHORIZED or err.status == 403:
                return None, "key_not_authorized"
            return None, "invalid_auth"
        except SkodaApiNotFoundError:
            return None, "vehicle_not_found"
        except SkodaApiRateLimitError:
            return None, "rate_limited"
        except (SkodaApiConnectionError, SkodaApiServerError):
            return None, "cannot_connect"
        except SkodaApiError:
            _LOGGER.exception("Unexpected answer from the API")
            return None, "unknown"
        name = payload["vehicle"].get("name")
        return (name if isinstance(name, str) and name else None), None

    @staticmethod
    def _user_schema(defaults: Mapping[str, Any]) -> vol.Schema:
        advanced = defaults.get(SECTION_ADVANCED) or {}
        return vol.Schema(
            {
                vol.Required(
                    CONF_VIN, default=defaults.get(CONF_VIN, vol.UNDEFINED)
                ): str,
                vol.Required(CONF_API_KEY): _SECRET,
                vol.Required(SECTION_ADVANCED): section(
                    vol.Schema(
                        {
                            vol.Required(
                                CONF_BASE_URL,
                                default=advanced.get(CONF_BASE_URL, API_BASE_URL),
                            ): _URL
                        }
                    ),
                    {"collapsed": True},
                ),
            }
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the VIN and the API key."""
        errors: dict[str, str] = {}
        if user_input is not None:
            vin = user_input[CONF_VIN].strip().upper()
            api_key = user_input[CONF_API_KEY].strip()
            advanced = user_input.get(SECTION_ADVANCED) or {}
            base_url = advanced.get(CONF_BASE_URL, API_BASE_URL).strip().rstrip("/")
            if not _VIN.match(vin):
                errors[CONF_VIN] = "invalid_vin"
            else:
                await self.async_set_unique_id(vin)
                self._abort_if_unique_id_configured()
                name, error = await self._async_validate(vin, api_key, base_url)
                if error is None:
                    data = {CONF_VIN: vin, CONF_API_KEY: api_key}
                    if base_url != API_BASE_URL:
                        data[CONF_BASE_URL] = base_url
                    return self.async_create_entry(title=name or vin, data=data)
                errors["base"] = error

        return self.async_show_form(
            step_id="user",
            data_schema=self._user_schema(user_input or {}),
            errors=errors,
            description_placeholders=_PLACEHOLDERS,
        )

    async def _async_step_new_key(
        self,
        step_id: str,
        entry: SkodaApiConfigEntry,
        user_input: dict[str, Any] | None,
    ) -> ConfigFlowResult:
        """Ask for a new API key for a vehicle that is already set up."""
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            _, error = await self._async_validate(
                entry.data[CONF_VIN],
                api_key,
                entry.data.get(CONF_BASE_URL, API_BASE_URL),
            )
            if error is None:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_API_KEY: api_key}
                )
            errors["base"] = error

        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): _SECRET}),
            errors=errors,
            description_placeholders={**_PLACEHOLDERS, "name": entry.title},
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start over with a new key after the API refused the stored one."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the new API key."""
        return await self._async_step_new_key(
            "reauth_confirm", self._get_reauth_entry(), user_input
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Replace the API key before it expires."""
        return await self._async_step_new_key(
            "reconfigure", self._get_reconfigure_entry(), user_input
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: SkodaApiConfigEntry,
    ) -> SkodaApiOptionsFlow:
        """Return the options flow."""
        return SkodaApiOptionsFlow()


class SkodaApiOptionsFlow(OptionsFlowWithReload):
    """Change how often the vehicle is polled and how commands are sent."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options."""
        errors: dict[str, str] = {}
        options = self.config_entry.options
        if user_input is not None:
            spin = (user_input.get(CONF_SPIN) or "").strip()
            auto_wake = int(user_input.get(CONF_AUTO_WAKE_MINUTES, 0))
            if spin and not _SPIN.match(spin):
                errors[CONF_SPIN] = "invalid_spin"
            elif 0 < auto_wake < MIN_AUTO_WAKE_MINUTES:
                errors[CONF_AUTO_WAKE_MINUTES] = "invalid_auto_wake"
            else:
                data: dict[str, Any] = {
                    CONF_POLL_INTERVAL: int(user_input[CONF_POLL_INTERVAL]),
                    CONF_ACTIVE_POLL_INTERVAL: int(
                        user_input[CONF_ACTIVE_POLL_INTERVAL]
                    ),
                    CONF_FAST_POLL_WHEN_PLUGGED: user_input[
                        CONF_FAST_POLL_WHEN_PLUGGED
                    ],
                    CONF_AUTO_WAKE_MINUTES: auto_wake,
                    CONF_READONLY: user_input[CONF_READONLY],
                }
                if spin:
                    data[CONF_SPIN] = spin
                return self.async_create_entry(data=data)

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_POLL_INTERVAL,
                    default=options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
                ): _minutes(MIN_POLL_INTERVAL, MAX_POLL_INTERVAL),
                vol.Required(
                    CONF_ACTIVE_POLL_INTERVAL,
                    default=options.get(
                        CONF_ACTIVE_POLL_INTERVAL, DEFAULT_ACTIVE_POLL_INTERVAL
                    ),
                ): _minutes(MIN_POLL_INTERVAL, MAX_POLL_INTERVAL),
                vol.Required(
                    CONF_FAST_POLL_WHEN_PLUGGED,
                    default=options.get(CONF_FAST_POLL_WHEN_PLUGGED, False),
                ): BooleanSelector(),
                vol.Required(
                    CONF_AUTO_WAKE_MINUTES,
                    default=options.get(CONF_AUTO_WAKE_MINUTES, 0),
                ): _minutes(0, MAX_AUTO_WAKE_MINUTES),
                vol.Optional(
                    CONF_SPIN,
                    description={"suggested_value": options.get(CONF_SPIN, "")},
                ): _SECRET,
                vol.Required(
                    CONF_READONLY, default=options.get(CONF_READONLY, False)
                ): BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
