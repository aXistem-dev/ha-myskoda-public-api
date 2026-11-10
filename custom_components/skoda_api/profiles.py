"""Changing charging profiles (saved charging locations)."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from homeassistant.exceptions import ServiceValidationError

from .const import DOMAIN, FIELD_TIMERS, FIELD_TIMES
from .coordinator import UNSET, SkodaApiCoordinator


def _raw_key(profile_id: int) -> str:
    return f"charging_profile_{profile_id}_raw"


def _merge(target: dict[str, Any], changes: dict[str, Any]) -> None:
    """Merge nested settings into a profile, in place."""
    for key, value in changes.items():
        if isinstance(value, dict):
            node = target.get(key)
            if not isinstance(node, dict):
                node = target[key] = {}
            _merge(node, value)
        else:
            target[key] = value


def _patch_by_id(
    profile: dict[str, Any], field: str, changes: list[dict[str, Any]]
) -> None:
    """Apply changes to the entries of a list, matched by their id."""
    entries = profile.get(field)
    if not isinstance(entries, list):
        entries = profile[field] = []
    by_id = {e.get("id"): e for e in entries if isinstance(e, dict)}
    for change in changes:
        entry = by_id.get(change["id"])
        if entry is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="profile_entry_not_found",
                translation_placeholders={"field": field, "id": str(change["id"])},
            )
        entry.update(change)


def _contains(reported: Any, sent: Any) -> bool:
    """Return True when the reported profile carries every value sent."""
    if isinstance(sent, dict):
        return isinstance(reported, dict) and all(
            _contains(reported.get(key), value) for key, value in sent.items()
        )
    if isinstance(sent, list):
        return (
            isinstance(reported, list)
            and len(reported) == len(sent)
            and all(_contains(r, s) for r, s in zip(reported, sent, strict=True))
        )
    return reported == sent


def find_profile(coordinator: SkodaApiCoordinator, profile: int | str) -> int:
    """Return the id of a profile given by id or by name."""
    profiles = coordinator.data.profiles
    for candidate in profiles:
        if str(candidate["id"]) == str(profile).strip():
            return candidate["id"]
    wanted = str(profile).strip().casefold()
    for candidate in profiles:
        name = candidate.get("name")
        if isinstance(name, str) and name.casefold() == wanted:
            return candidate["id"]
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="profile_not_found",
        translation_placeholders={"profile": str(profile)},
    )


async def async_send_profile(
    coordinator: SkodaApiCoordinator,
    profile_id: int,
    *,
    settings: dict[str, Any] | None = None,
    preferred_charging_times: list[dict[str, Any]] | None = None,
    timers: list[dict[str, Any]] | None = None,
    name: str | None = None,
    optimistic: dict[str, Any] | None = None,
) -> None:
    """Send a whole charging profile with some of its values changed.

    Changes build on the last profile sent while it is unconfirmed.
    """
    base = coordinator.optimistic(_raw_key(profile_id))
    if base is UNSET:
        base = coordinator.data.profile(profile_id)
    if base is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="profile_not_found",
            translation_placeholders={"profile": str(profile_id)},
        )
    profile = deepcopy(base)
    # The API wants both lists in a profile, also when they are empty.
    for field in (FIELD_TIMES, FIELD_TIMERS):
        if not isinstance(profile.get(field), list):
            profile[field] = []
    if name:
        profile["name"] = name
    if settings:
        node = profile.get("settings")
        if not isinstance(node, dict):
            node = profile["settings"] = {}
        _merge(node, settings)
    if preferred_charging_times:
        _patch_by_id(profile, FIELD_TIMES, preferred_charging_times)
    if timers:
        _patch_by_id(profile, FIELD_TIMERS, timers)

    values = dict(optimistic or {})
    values[_raw_key(profile_id)] = profile
    await coordinator.async_command(
        lambda: coordinator.client.update_charging_profile(coordinator.vin, profile),
        confirmed=lambda data: _contains(data.profile(profile_id), profile),
        optimistic=values,
    )
