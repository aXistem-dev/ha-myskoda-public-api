"""Data update coordinator of the MyŠkoda Public API integration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
import re
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.helpers.event import async_call_later, async_track_point_in_utc_time
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    PROBLEM_KEY_EXPIRED,
    PROBLEM_KEY_NOT_AUTHORIZED,
    PROBLEM_OPERATION_DISABLED,
    SkodaApiAuthError,
    SkodaApiClient,
    SkodaApiConnectionError,
    SkodaApiError,
    SkodaApiForbiddenError,
    SkodaApiNotFoundError,
    SkodaApiRateLimitError,
    SkodaApiServerError,
    SkodaApiUnsupportedError,
)
from .const import (
    API_KEYS_URL,
    API_STATUS_AUTH_FAILED,
    API_STATUS_ERROR,
    API_STATUS_OK,
    API_STATUS_RATE_LIMITED,
    API_STATUS_SKIPPED_QUOTA,
    AUTO_WAKE_MAX_UNANSWERED,
    AUTO_WAKE_MIN_REMAINING,
    COMMAND_RESERVE,
    CONF_ACTIVE_POLL_INTERVAL,
    CONF_AUTO_WAKE_MINUTES,
    CONF_FAST_POLL_WHEN_PLUGGED,
    CONF_POLL_INTERVAL,
    CONF_READONLY,
    CONF_SPIN,
    CONF_VIN,
    DEFAULT_ACTIVE_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_RETRY_AFTER,
    DOMAIN,
    FOLLOW_UP_DELAYS,
    KEY_EXPIRY_WARNING_DAYS,
    OP_SET_CHARGE_MODE,
    OPTIMISTIC_TIMEOUT,
    PROFILE_ITEM_FIELDS,
    SECTION_ACTIVE_VENTILATION,
    SECTION_AIR_CONDITIONING,
    SECTION_AUXILIARY_HEATING,
    SECTION_CHARGING_PROFILES,
    SECTIONS,
    STALE_SECTION_POLLS,
    STORE_SAVE_DELAY,
)
from .data import ProfileLayout, VehicleData

_LOGGER = logging.getLogger(__name__)

type SkodaApiConfigEntry = ConfigEntry[SkodaApiCoordinator]

UNSET: Any = object()

POLL_MODE_NORMAL = "normal"
POLL_MODE_ACTIVE = "active"


@dataclass(slots=True)
class _Pending:
    """A command the vehicle has not confirmed yet."""

    values: dict[str, Any]
    confirmed: Callable[[VehicleData], bool]
    expires: datetime


# End of a rate limit hit during setup, per entry; keeps retries off the API.
_RATE_LIMITED_UNTIL: dict[str, datetime] = {}


def store_key(entry_id: str) -> str:
    """Return the storage key of a vehicle's last response."""
    return f"{DOMAIN}.{entry_id}"


def rate_limited_until(entry_id: str) -> datetime | None:
    """Return until when setup should not ask the API, if it was told to wait."""
    until = _RATE_LIMITED_UNTIL.get(entry_id)
    if until is not None and until <= dt_util.utcnow():
        del _RATE_LIMITED_UNTIL[entry_id]
        return None
    return until


class SkodaApiCoordinator(DataUpdateCoordinator[VehicleData]):
    """Fetch the state of one vehicle and send commands to it."""

    config_entry: SkodaApiConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: SkodaApiConfigEntry,
        client: SkodaApiClient,
    ) -> None:
        """Set up polling for the vehicle of a config entry."""
        self.client = client
        self.vin: str = entry.data[CONF_VIN]
        self._blocked_until: datetime | None = None
        self._force = False
        self._missing_polls: dict[str, int] = {}
        self._pending: list[_Pending] = []
        self._follow_ups: list[CALLBACK_TYPE] = []
        self._profile_names: dict[str, Any] | None = None
        # Profile entities missing from the last response.
        self._vanished: set[str] = set()
        # Last response on disk; fills in missing parts after a restart.
        self._store: Store[dict[str, Any]] = Store(hass, 1, store_key(entry.entry_id))
        self._stored: VehicleData | None = None
        # When the API last answered with the vehicle data.
        self.last_poll: datetime | None = None
        # How the last scheduled or forced update ended (API_STATUS_*).
        self.api_status: str | None = None
        self.poll_mode = POLL_MODE_NORMAL
        self._last_auto_wake: datetime | None = None
        # Automatic wakes since the vehicle last reported; capped.
        self._unanswered_wakes = 0
        # Updates the quota entities when a wait ends or the quota refills.
        self._quota_timer: CALLBACK_TYPE | None = None
        self._quota_timer_at: datetime | None = None
        self._closed = False
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{self.vin}",
            update_interval=timedelta(
                minutes=entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
            ),
        )

    async def async_remove_stored(self) -> None:
        """Delete the kept response, including a save still waiting."""
        await self._store.async_remove()

    async def async_load_stored(self) -> None:
        """Read the response kept from before the last restart."""
        stored = await self._store.async_load()
        if isinstance(stored, dict) and isinstance(stored.get("payload"), dict):
            self._stored = VehicleData(self.vin, stored["payload"])

    # --------------------------------------------------------------- options

    @property
    def readonly(self) -> bool:
        """Return True when commands are switched off for this vehicle."""
        return bool(self.config_entry.options.get(CONF_READONLY, False))

    @property
    def spin(self) -> str | None:
        """Return the stored S-PIN, if any."""
        return self.config_entry.options.get(CONF_SPIN) or None

    @property
    def poll_interval(self) -> int:
        """Return the normal polling interval in minutes."""
        return int(
            self.config_entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
        )

    @property
    def active_poll_interval(self) -> int:
        """Return the polling interval in minutes while the vehicle is active."""
        return int(
            self.config_entry.options.get(
                CONF_ACTIVE_POLL_INTERVAL, DEFAULT_ACTIVE_POLL_INTERVAL
            )
        )

    @property
    def fast_poll_when_plugged(self) -> bool:
        """Return True when a plugged-in cable alone counts as active."""
        return bool(self.config_entry.options.get(CONF_FAST_POLL_WHEN_PLUGGED, False))

    @property
    def auto_wake_minutes(self) -> int:
        """Return after how many silent minutes a charging vehicle is woken."""
        return int(self.config_entry.options.get(CONF_AUTO_WAKE_MINUTES, 0))

    @callback
    def async_set_option(self, key: str, value: Any) -> None:
        """Store one option and apply it at once, without a reload."""
        self.hass.config_entries.async_update_entry(
            self.config_entry, options={**self.config_entry.options, key: value}
        )
        if self.data is not None:
            self._apply_poll_interval(self.data)
        if self._listeners:
            # The new interval counts from now.
            self._schedule_refresh()
        self.async_update_listeners()

    # --------------------------------------------------------------- polling

    async def _async_update_data(self) -> VehicleData:
        try:
            data = await self._async_fetch()
        finally:
            self._schedule_quota_update()
        data.readonly = self.readonly
        self._prune_pending(data)
        self._apply_poll_interval(data)
        if self.api_status == API_STATUS_OK:
            self._maybe_auto_wake(data, dt_util.utcnow())
        return data

    def _active(self, data: VehicleData) -> bool:
        """Return True while the vehicle is doing something worth following."""
        if data.is_charging is True:
            return True
        if any(
            data.running(section) is True
            for section in (
                SECTION_AIR_CONDITIONING,
                SECTION_AUXILIARY_HEATING,
                SECTION_ACTIVE_VENTILATION,
            )
        ):
            return True
        return self.fast_poll_when_plugged and data.plug_connected is True

    def _apply_poll_interval(self, data: VehicleData) -> None:
        """Poll faster while the vehicle is active, at the normal pace otherwise."""
        minutes = self.poll_interval
        self.poll_mode = POLL_MODE_NORMAL
        if self._active(data):
            # Active polling is never slower than normal polling.
            minutes = min(minutes, self.active_poll_interval)
            self.poll_mode = POLL_MODE_ACTIVE
        self.update_interval = timedelta(minutes=minutes)

    async def _async_fetch(self) -> VehicleData:
        force, self._force = self._force, False
        now = dt_util.utcnow()
        previous: VehicleData | None = self.data

        if previous is not None:
            if self.blocked(now):
                _LOGGER.debug(
                    "Rate limited until %s; keeping data", self._blocked_until
                )
                self.api_status = API_STATUS_RATE_LIMITED
                return previous
            if not force and self._quota_low(now):
                _LOGGER.debug("Few API requests left; skipping this poll")
                self.api_status = API_STATUS_SKIPPED_QUOTA
                return previous

        try:
            payload = await self.client.get_vehicle(self.vin)
        except SkodaApiAuthError as err:
            self.api_status = API_STATUS_AUTH_FAILED
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="auth_failed",
            ) from err
        except SkodaApiRateLimitError as err:
            self.api_status = API_STATUS_RATE_LIMITED
            until = self._block(err)
            retry_after = max(1, round((until - now).total_seconds()))
            if previous is not None:
                _LOGGER.debug("Rate limited for %s s; keeping data", retry_after)
                return previous
            _RATE_LIMITED_UNTIL[self.config_entry.entry_id] = until
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="rate_limited",
                retry_after=retry_after,
            ) from err
        except SkodaApiError as err:
            self.api_status = API_STATUS_ERROR
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err

        self._blocked_until = None
        self.api_status = API_STATUS_OK
        self.last_poll = now
        data = VehicleData(self.vin, payload)
        self._carry_over(previous or self._stored, data)
        self._stored = None
        if previous is None or _newer(data.last_captured, previous.last_captured):
            self._unanswered_wakes = 0
        fresh = {k: v for k, v in data.raw.items() if k not in data.stale}
        # Needed only after a restart: written on shutdown, or after a long quiet.
        self._store.async_delay_save(
            lambda: {"payload": {"vehicle": fresh}}, STORE_SAVE_DELAY
        )
        self._check_key_expiry(data, now)
        self._check_profile_layout(data)
        return data

    def _check_profile_layout(self, data: VehicleData) -> None:
        """Reload on a renamed profile; remove deleted profile entities.

        Entities are removed only once two responses in a row lack them.
        """
        if not data.has(SECTION_CHARGING_PROFILES) or (
            SECTION_CHARGING_PROFILES in data.stale
        ):
            return
        layout = data.profile_layout()
        self._remove_vanished(layout)
        names = {profile_id: profile.name for profile_id, profile in layout.items()}
        known, self._profile_names = self._profile_names, names
        if known is not None and any(
            known[profile_id] != name
            for profile_id, name in names.items()
            if profile_id in known
        ):
            self.hass.config_entries.async_schedule_reload(self.config_entry.entry_id)

    def _remove_vanished(self, layout: dict[str, ProfileLayout]) -> None:
        registry = er.async_get(self.hass)
        prefix = f"{self.vin}_charging_profile_"
        vanished: set[str] = set()
        for entity in er.async_entries_for_config_entry(
            registry, self.config_entry.entry_id
        ):
            if not entity.unique_id.startswith(prefix) or not _gone(
                entity.unique_id.removeprefix(prefix), layout
            ):
                continue
            if entity.unique_id in self._vanished:
                registry.async_remove(entity.entity_id)
            else:
                vanished.add(entity.unique_id)
        self._vanished = vanished

    def _quota_low(self, now: datetime) -> bool:
        limit = self.client.rate_limit
        left = limit.left(now) if limit is not None else None
        return left is not None and left <= COMMAND_RESERVE

    def _carry_over(self, previous: VehicleData | None, data: VehicleData) -> None:
        """Keep a part that could not be retrieved this time, for a while."""
        for section in SECTIONS:
            if data.has(section):
                self._missing_polls.pop(section, None)
                continue
            if (
                previous is None
                or not previous.has(section)
                or not data.section_unavailable(section)
            ):
                continue
            missed = self._missing_polls.get(section, 0) + 1
            self._missing_polls[section] = missed
            if missed <= STALE_SECTION_POLLS:
                data.raw[section] = previous.raw[section]
                data.stale.add(section)
        if previous is not None:
            for key in ("renderUrl", "name", "licensePlate", "operations"):
                if key not in data.raw and key in previous.raw:
                    data.raw[key] = previous.raw[key]

    def blocked(self, now: datetime) -> bool:
        """Return True while the API has asked to wait with requests."""
        return self._blocked_until is not None and now < self._blocked_until

    @property
    def blocked_until(self) -> datetime | None:
        """Return until when the API asked to wait, while that is ahead."""
        return self._blocked_until if self.blocked(dt_util.utcnow()) else None

    def _block(self, err: SkodaApiRateLimitError) -> datetime:
        """Wait with requests as long as a refusal for the quota says."""
        now = dt_util.utcnow()
        limit = self.client.rate_limit
        if err.retry_after is not None:
            until = now + timedelta(seconds=max(0, err.retry_after))
        elif limit is not None and limit.reset_at is not None and limit.reset_at > now:
            until = limit.reset_at
        else:
            until = now + timedelta(seconds=DEFAULT_RETRY_AFTER)
        self._blocked_until = until
        return until

    async def async_force_refresh(self) -> None:
        """Fetch now, even when few requests are left."""
        if (until := self._blocked_until) is not None and self.blocked(
            dt_util.utcnow()
        ):
            # The API said to wait; a request now would only be refused.
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="refresh_rate_limited",
                translation_placeholders={
                    "time": dt_util.as_local(until).strftime("%H:%M")
                },
            )
        self._force = True
        await self.async_refresh()

    # -------------------------------------------------------------- commands

    async def async_command(
        self,
        send: Callable[[], Awaitable[None]],
        *,
        confirmed: Callable[[VehicleData], bool],
        optimistic: dict[str, Any] | None = None,
    ) -> None:
        """Send a command and show its expected result until confirmed.

        `optimistic` maps entity keys to the value shown until `confirmed`
        returns True for the vehicle data.
        """
        if self.readonly:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="readonly"
            )
        try:
            await send()
        except SkodaApiError as err:
            if isinstance(err, SkodaApiRateLimitError) and not err.vehicle_declined:
                # The quota is used up: polls would be refused as well.
                self._block(err)
            self._schedule_quota_update()
            # The quota entities show the refusal at once.
            self.async_update_listeners()
            raise self._command_error(err) from err

        self._pending.append(
            _Pending(
                values=dict(optimistic or {}),
                confirmed=confirmed,
                expires=dt_util.utcnow() + timedelta(seconds=OPTIMISTIC_TIMEOUT),
            )
        )
        if self._closed:
            # Unloaded while the command was on its way.
            return
        self._schedule_quota_update()
        self._schedule_follow_ups()
        self.async_update_listeners()

    @property
    def _changes_pending(self) -> bool:
        """Return True while a command that changes a setting is unconfirmed."""
        now = dt_util.utcnow()
        return any(p.values and p.expires > now for p in self._pending)

    async def async_wake(self) -> None:
        """Make the vehicle report by re-sending its current charge mode.

        The public API has no wake-up call; this changes nothing in the car.
        """
        data = self.data
        mode = data.charge_mode_setting
        if mode is None or not data.supports(OP_SET_CHARGE_MODE):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="wake_not_possible"
            )
        if self._changes_pending:
            # A change still under way may be a new charge mode; re-sending
            # the old one would undo it.
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="wake_command_pending"
            )
        before = data.last_captured
        self._last_auto_wake = dt_util.utcnow()
        await self.async_command(
            lambda: self.client.set_charge_mode(self.vin, mode),
            confirmed=lambda new: _newer(new.last_captured, before),
        )

    def _maybe_auto_wake(self, data: VehicleData, now: datetime) -> None:
        """Wake a charging vehicle that has been silent for too long."""
        minutes = self.auto_wake_minutes
        if minutes <= 0 or self.readonly or data.is_charging is not True:
            return
        if self._changes_pending or self._unanswered_wakes >= AUTO_WAKE_MAX_UNANSWERED:
            return
        if data.charge_mode_setting is None or not data.supports(OP_SET_CHARGE_MODE):
            return
        if self.blocked(now):
            return
        limit = self.client.rate_limit
        left = limit.left(now) if limit is not None else None
        if left is not None and left < AUTO_WAKE_MIN_REMAINING:
            return
        wait = timedelta(minutes=minutes)
        captured = data.last_captured
        if captured is None or now - captured < wait:
            return
        if self._last_auto_wake is not None and now - self._last_auto_wake < wait:
            return
        # Set before sending, so a failing wake is not retried at every poll.
        self._last_auto_wake = now
        self._unanswered_wakes += 1
        _LOGGER.info(
            "%s has not reported for %s minutes while charging; waking it",
            self.config_entry.title,
            round((now - captured).total_seconds() / 60),
        )
        # Not awaited: the update this runs in should not wait for a command.
        self.config_entry.async_create_background_task(
            self.hass,
            self._async_auto_wake(),
            name=f"{self.name} auto wake",
            eager_start=False,
        )

    async def _async_auto_wake(self) -> None:
        try:
            await self.async_wake()
        except HomeAssistantError as err:
            _LOGGER.warning(
                "Waking %s failed: %s", self.config_entry.title, err or repr(err)
            )

    def optimistic(self, key: str) -> Any:
        """Return the value a pending command asked for, or UNSET."""
        now = dt_util.utcnow()
        for pending in reversed(self._pending):
            if key in pending.values and pending.expires > now:
                return pending.values[key]
        return UNSET

    def _prune_pending(self, data: VehicleData) -> None:
        """Drop commands the vehicle has confirmed, and those it never will."""
        now = dt_util.utcnow()
        self._pending = [
            pending
            for pending in self._pending
            if pending.expires > now and not pending.confirmed(data)
        ]

    def _schedule_follow_ups(self) -> None:
        self.cancel_follow_ups()
        for index, delay in enumerate(FOLLOW_UP_DELAYS):
            self._follow_ups.append(
                async_call_later(
                    self.hass, delay, self._follow_up_job(first=index == 0)
                )
            )
        # Show the reported values again once the requested ones expire.
        self._follow_ups.append(
            async_call_later(self.hass, OPTIMISTIC_TIMEOUT + 1, self._expire_pending)
        )

    @callback
    def _expire_pending(self, _now: datetime) -> None:
        if self.data is not None:
            self._prune_pending(self.data)
        self.async_update_listeners()

    def _follow_up_job(self, *, first: bool) -> Callable[[datetime], Awaitable[None]]:
        async def _refresh(_now: datetime) -> None:
            # Later follow-ups only matter while a command is unconfirmed.
            if not first and not self._pending:
                return
            self._force = True
            await self.async_request_refresh()

        return _refresh

    @callback
    def cancel_follow_ups(self) -> None:
        """Cancel the refreshes scheduled after a command."""
        while self._follow_ups:
            self._follow_ups.pop()()

    @callback
    def close(self) -> None:
        """Stop every timer; the vehicle is being unloaded."""
        self._closed = True
        self.cancel_follow_ups()
        if self._quota_timer is not None:
            self._quota_timer()
            self._quota_timer = None

    def _schedule_quota_update(self) -> None:
        """Update the quota entities when a wait ends or the quota refills.

        These moments pass between polls; the entities follow without a request.
        """
        if self._closed:
            return
        now = dt_util.utcnow()
        limit = self.client.rate_limit
        moments = [
            moment
            for moment in (
                self._blocked_until,
                limit.reset_at if limit is not None else None,
            )
            if moment is not None and moment > now
        ]
        at = min(moments) + timedelta(seconds=1) if moments else None
        if at == self._quota_timer_at and (at is None or self._quota_timer):
            return
        if self._quota_timer is not None:
            self._quota_timer()
            self._quota_timer = None
        self._quota_timer_at = at
        if at is not None:
            self._quota_timer = async_track_point_in_utc_time(
                self.hass, self._quota_moment, at
            )

    @callback
    def _quota_moment(self, _now: datetime) -> None:
        self._quota_timer = None
        self._quota_timer_at = None
        self.async_update_listeners()
        # The refill may still be ahead after a wait ended.
        self._schedule_quota_update()

    def _command_error(self, err: SkodaApiError) -> HomeAssistantError:
        key = "command_failed"
        placeholders: dict[str, str] = {"error": err.detail or str(err)}
        if isinstance(err, SkodaApiAuthError):
            if err.status == 401 or err.problem in (
                PROBLEM_KEY_EXPIRED,
                PROBLEM_KEY_NOT_AUTHORIZED,
            ):
                self.config_entry.async_start_reauth(self.hass)
                key = "auth_failed"
            else:
                key = "command_not_authorized"
        elif isinstance(err, SkodaApiForbiddenError):
            key = "command_not_authorized"
        elif isinstance(err, SkodaApiRateLimitError):
            key = "vehicle_declined" if err.vehicle_declined else "command_rate_limited"
            placeholders["minutes"] = str(
                max(1, round((err.retry_after or DEFAULT_RETRY_AFTER) / 60))
            )
        elif isinstance(err, SkodaApiUnsupportedError):
            key = (
                "command_disabled"
                if err.problem == PROBLEM_OPERATION_DISABLED
                else "command_not_supported"
            )
        elif isinstance(err, SkodaApiNotFoundError):
            key = "command_not_found"
        elif isinstance(err, SkodaApiServerError) and err.status == 504:
            key = "vehicle_timeout"
        elif isinstance(err, SkodaApiConnectionError):
            key = "cannot_connect"
        return HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key=key,
            translation_placeholders=placeholders,
        )

    # ------------------------------------------------------------- API key

    def _check_key_expiry(self, data: VehicleData, now: datetime) -> None:
        issue_id = f"api_key_expiring_{self.config_entry.entry_id}"
        expires = self.client.key_expires_at
        if expires is None or expires - now > timedelta(days=KEY_EXPIRY_WARNING_DAYS):
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
            return
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            learn_more_url=API_KEYS_URL,
            translation_key="api_key_expiring",
            translation_placeholders={
                "name": data.name or self.vin,
                "date": dt_util.as_local(expires).strftime("%Y-%m-%d"),
            },
        )


def _newer(stamp: datetime | None, before: datetime | None) -> bool:
    """Return True when a capture time is later than an earlier one."""
    if stamp is None:
        return False
    return before is None or stamp > before


_PROFILE_ITEM = re.compile(rf"({'|'.join(PROFILE_ITEM_FIELDS)})_(\d+)_")


def _gone(key: str, layout: dict[str, ProfileLayout]) -> bool:
    """Return True when the profile, timer or charging time of a key is gone.

    `key` is `<profile id>_<key>` or `<profile id>_<kind>_<item id>_<key>`;
    a list missing from the response says nothing about its entries.
    """
    profile_id, _, rest = key.partition("_")
    profile = layout.get(profile_id)
    if profile is None:
        return True
    match = _PROFILE_ITEM.match(rest)
    if match is None or match[1] not in profile.kinds:
        return False
    return f"{match[1]}_{match[2]}" not in profile.items
