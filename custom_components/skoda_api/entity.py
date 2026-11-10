"""Base entity of the MyŠkoda Public API integration."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    FIELD_TIMERS,
    FIELD_TIMES,
    MANUFACTURER,
    OP_UPDATE_CHARGING_PROFILE,
    SECTION_CHARGING_PROFILES,
)
from .coordinator import UNSET, SkodaApiConfigEntry, SkodaApiCoordinator
from .data import VehicleData
from .profiles import async_send_profile

# A candidate entity: its key, and how to build it once the vehicle has it.
type Candidate = tuple[str, Callable[[], Entity]]


@dataclass(frozen=True, kw_only=True)
class SkodaApiDescription(EntityDescription):
    """What every entity description of this integration adds.

    `section` is the part of the data the entity needs, `exists_fn` a further
    check, and `operations` the remote operations a control needs.
    """

    section: str | None = None
    exists_fn: Callable[[VehicleData], bool] | None = None
    operations: tuple[str, ...] = ()

    def exists(self, data: VehicleData) -> bool:
        """Return True when the vehicle provides this entity."""
        if self.section is not None and not data.has(self.section):
            return False
        if self.operations and not data.controllable(*self.operations):
            return False
        return self.exists_fn is None or self.exists_fn(data)


class SkodaApiEntity(CoordinatorEntity[SkodaApiCoordinator]):
    """An entity of one vehicle."""

    _attr_has_entity_name = True
    entity_description: SkodaApiDescription

    def __init__(
        self, coordinator: SkodaApiCoordinator, description: SkodaApiDescription
    ) -> None:
        """Bind the entity to its vehicle."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.vin}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.vin)},
            manufacturer=MANUFACTURER,
            name=coordinator.data.name or coordinator.config_entry.title,
            serial_number=coordinator.vin,
        )

    @property
    def vehicle(self) -> VehicleData:
        """Return the latest data of the vehicle."""
        return self.coordinator.data

    @property
    def available(self) -> bool:
        """Return False while the part this entity reads is missing."""
        section = self.entity_description.section
        return super().available and (section is None or self.vehicle.has(section))

    def pending(self, default: Any) -> Any:
        """Return the value a pending command asked for, else `default`."""
        value = self.coordinator.optimistic(self.entity_description.key)
        return default if value is UNSET else value


class ChargingProfileEntity(SkodaApiEntity):
    """An entity of one charging profile (saved charging location)."""

    def __init__(
        self,
        coordinator: SkodaApiCoordinator,
        description: SkodaApiDescription,
        profile_id: int,
    ) -> None:
        """Bind the entity to a profile of the vehicle."""
        super().__init__(coordinator, description)
        self.profile_id = profile_id
        self._key = profile_key(profile_id, description.key)
        self._attr_unique_id = f"{coordinator.vin}_{self._key}"
        self._attr_translation_placeholders = {
            "profile": self._profile_name or str(profile_id)
        }

    @property
    def profile(self) -> dict[str, Any] | None:
        """Return the profile as the vehicle reports it."""
        return self.vehicle.profile(self.profile_id)

    @property
    def _profile_name(self) -> str | None:
        profile = self.vehicle.profile(self.profile_id)
        name = profile.get("name") if profile else None
        return name if isinstance(name, str) and name else None

    @property
    def available(self) -> bool:
        """Return False once the profile is gone."""
        return super().available and self.profile is not None

    def setting(self, *path: str) -> Any:
        """Return a value of the profile settings."""
        node: Any = (self.profile or {}).get("settings")
        for key in path:
            if not isinstance(node, dict):
                return None
            node = node.get(key)
        return node

    def pending(self, default: Any) -> Any:
        """Return the value a pending command asked for, else `default`."""
        value = self.coordinator.optimistic(self._key)
        return default if value is UNSET else value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Tell which profile the entity belongs to."""
        return {"profile_id": self.profile_id, "profile_name": self._profile_name}

    async def async_update_settings(self, changes: dict[str, Any], shown: Any) -> None:
        """Send the profile with changed settings; the vehicle wants it whole."""
        await async_send_profile(
            self.coordinator,
            self.profile_id,
            settings=changes,
            optimistic={self._key: shown},
        )


class ChargingProfileItemEntity(ChargingProfileEntity):
    """An entity of one timer or preferred charging time of a profile."""

    def __init__(
        self,
        coordinator: SkodaApiCoordinator,
        description: ProfileItemDescription,
        profile_id: int,
        item_id: int,
    ) -> None:
        """Bind the entity to an entry of a list in a profile."""
        super().__init__(coordinator, description, profile_id)
        self.field = description.field
        self.item_id = item_id
        self._key = profile_item_key(profile_id, description, item_id)
        self._attr_unique_id = f"{coordinator.vin}_{self._key}"
        self._attr_translation_placeholders = {
            "profile": self._profile_name or str(profile_id),
            "number": str(item_id),
        }

    @property
    def item(self) -> dict[str, Any] | None:
        """Return the timer or charging time as the vehicle reports it."""
        for entry in (self.profile or {}).get(self.field) or []:
            if isinstance(entry, dict) and entry.get("id") == self.item_id:
                return entry
        return None

    @property
    def available(self) -> bool:
        """Return False once the entry is gone."""
        return super().available and self.item is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Tell which profile and which entry the entity belongs to."""
        return {**super().extra_state_attributes, "item_id": self.item_id}

    async def async_update_item(self, changes: dict[str, Any], shown: Any) -> None:
        """Send the profile with this entry changed."""
        change = [{"id": self.item_id, **changes}]
        await async_send_profile(
            self.coordinator,
            self.profile_id,
            timers=change if self.field == FIELD_TIMERS else None,
            preferred_charging_times=change if self.field == FIELD_TIMES else None,
            optimistic={self._key: shown},
        )


@dataclass(frozen=True, kw_only=True)
class ProfileItemDescription(SkodaApiDescription):
    """Describe an entity of a timer or a preferred charging time."""

    field: str
    kind: str
    value_key: str


def profile_item_key(
    profile_id: int, description: ProfileItemDescription, item_id: int
) -> str:
    """Return the entity key of an entity of a timer or charging time."""
    return profile_key(profile_id, f"{description.kind}_{item_id}_{description.key}")


def profile_item_candidates[DescriptionT: ProfileItemDescription](
    coordinator: SkodaApiCoordinator,
    descriptions: Iterable[DescriptionT],
    build: Callable[[SkodaApiCoordinator, DescriptionT, int, int], Entity],
) -> Callable[[], Iterable[Candidate]]:
    """Return a candidate source: one entity per timer or charging time."""
    descriptions = tuple(descriptions)

    def _candidates() -> Iterable[Candidate]:
        data = coordinator.data
        if not data.has(SECTION_CHARGING_PROFILES) or not data.controllable(
            OP_UPDATE_CHARGING_PROFILE
        ):
            return
        for profile in data.profiles:
            profile_id = profile["id"]
            for description in descriptions:
                for entry in profile.get(description.field) or []:
                    if not isinstance(entry, dict) or "id" not in entry:
                        continue
                    yield (
                        profile_item_key(profile_id, description, entry["id"]),
                        lambda d=description, p=profile_id, i=entry["id"]: build(
                            coordinator, d, p, i
                        ),
                    )

    return _candidates


def profile_key(profile_id: int, key: str) -> str:
    """Return the entity key of a per-profile entity."""
    return f"charging_profile_{profile_id}_{key}"


def profile_candidates[DescriptionT: SkodaApiDescription](
    coordinator: SkodaApiCoordinator,
    descriptions: Iterable[DescriptionT],
    build: Callable[[SkodaApiCoordinator, DescriptionT, int], Entity],
    *,
    writable: bool = True,
) -> Callable[[], Iterable[Candidate]]:
    """Return a candidate source yielding one entity per charging profile."""
    descriptions = tuple(descriptions)

    def _candidates() -> Iterable[Candidate]:
        data = coordinator.data
        if not data.has(SECTION_CHARGING_PROFILES):
            return
        if writable and not data.controllable(OP_UPDATE_CHARGING_PROFILE):
            return
        for profile in data.profiles:
            profile_id = profile["id"]
            for description in descriptions:
                yield (
                    profile_key(profile_id, description.key),
                    lambda d=description, p=profile_id: build(coordinator, d, p),
                )

    return _candidates


def described_candidates[DescriptionT: SkodaApiDescription](
    coordinator: SkodaApiCoordinator,
    descriptions: Iterable[DescriptionT],
    build: Callable[[SkodaApiCoordinator, DescriptionT], Entity],
) -> Callable[[], Iterable[Candidate]]:
    """Return a candidate source for a list of entity descriptions."""
    descriptions = tuple(descriptions)

    def _candidates() -> Iterable[Candidate]:
        for description in descriptions:
            if description.exists(coordinator.data):
                yield description.key, lambda d=description: build(coordinator, d)

    return _candidates


@callback
def async_add_when_available(
    entry: SkodaApiConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    *sources: Callable[[], Iterable[Candidate]],
) -> None:
    """Add entities now and whenever the vehicle starts reporting more."""
    coordinator = entry.runtime_data
    added: set[str] = set()

    @callback
    def _add_new() -> None:
        new: list[Entity] = []
        for source in sources:
            for key, build in source():
                if key not in added:
                    added.add(key)
                    new.append(build())
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))
