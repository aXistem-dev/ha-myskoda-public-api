"""Read access to the vehicle data returned by the API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, NamedTuple

from homeassistant.util import dt as dt_util

from .const import (
    COMBUSTION_ENGINE_TYPES,
    PROFILE_ITEM_FIELDS,
    SECTION_AIR_CONDITIONING,
    SECTION_CHARGING,
    SECTION_CHARGING_PROFILES,
    SECTION_ERROR_PREFIX,
    SECTION_FUEL,
    SECTIONS,
)

_RUNNING_STATES = (
    "cooling",
    "heating",
    "heating_auxiliary",
    "preheating",
    "ventilation",
)
_IDLE_STATES = ("off", "completed")


class ProfileLayout(NamedTuple):
    """What a charging profile holds, to notice renames and deletions."""

    name: Any
    items: frozenset[str]
    kinds: frozenset[str]


class VehicleData:
    """One response of the vehicle endpoint; missing fields read as None."""

    def __init__(self, vin: str, payload: dict[str, Any]) -> None:
        """Wrap the response body of `GET /api/v1/vehicles/{vin}`."""
        self.vin = vin
        vehicle = payload.get("vehicle")
        self.raw: dict[str, Any] = vehicle if isinstance(vehicle, dict) else {}
        errors = payload.get("errors")
        self.errors: list[dict[str, Any]] = (
            [e for e in errors if isinstance(e, dict)]
            if isinstance(errors, list)
            else []
        )
        # Parts shown from an earlier response because the current one lacks them.
        self.stale: set[str] = set()
        # Set by the coordinator: the vehicle is shown without controls.
        self.readonly = False

    # ------------------------------------------------------------ primitives

    def get(self, *path: str) -> Any:
        """Return the value at a path of keys, or None."""
        node: Any = self.raw
        for key in path:
            if not isinstance(node, dict):
                return None
            node = node.get(key)
        return node

    def has(self, section: str) -> bool:
        """Return True when a part of the data is present."""
        return isinstance(self.raw.get(section), dict)

    def text(self, *path: str) -> str | None:
        """Return an enumerated API value in lower case."""
        value = self.get(*path)
        return value.lower() if isinstance(value, str) and value else None

    def flag(self, *path: str, on: str, off: str) -> bool | None:
        """Map an enumerated value onto a boolean; anything else is unknown."""
        value = self.text(*path)
        if value == on:
            return True
        if value == off:
            return False
        return None

    def number(self, *path: str) -> float | int | None:
        """Return a numeric value; booleans and text do not count."""
        value = self.get(*path)
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        return value

    def boolean(self, *path: str) -> bool | None:
        """Return a boolean value."""
        value = self.get(*path)
        return value if isinstance(value, bool) else None

    def timestamp(self, *path: str) -> datetime | None:
        """Return a timestamp value."""
        value = self.get(*path)
        if not isinstance(value, str):
            return None
        parsed = dt_util.parse_datetime(value)
        if parsed is not None and parsed.tzinfo is None:
            # Home Assistant refuses a timestamp without a zone.
            parsed = parsed.replace(tzinfo=dt_util.UTC)
        return parsed

    def controllable(self, *operations: str) -> bool:
        """Return True when the vehicle offers operations as controls."""
        return not self.readonly and self.supports(*operations)

    def shown_read_only(self, *operations: str) -> bool:
        """Return True when a setting has no control and needs a sensor."""
        if self.readonly:
            return True
        return self.operations is not None and not self.supports(*operations)

    # --------------------------------------------------------------- vehicle

    @property
    def name(self) -> str | None:
        """Return the name the owner gave the vehicle, or its model."""
        value = self.raw.get("name")
        return value if isinstance(value, str) and value else None

    @property
    def license_plate(self) -> str | None:
        """Return the licence plate."""
        value = self.raw.get("licensePlate")
        return value if isinstance(value, str) and value else None

    @property
    def render_url(self) -> str | None:
        """Return the address of the vehicle picture."""
        value = self.raw.get("renderUrl")
        return value if isinstance(value, str) and value else None

    @property
    def operations(self) -> frozenset[str] | None:
        """Return the supported remote operations, or None when unknown."""
        operations = self.raw.get("operations")
        if not isinstance(operations, list):
            return None
        return frozenset(
            op["name"]
            for op in operations
            if isinstance(op, dict) and isinstance(op.get("name"), str)
        )

    def supports(self, *operations: str) -> bool:
        """Return True when the vehicle lists every given operation."""
        supported = self.operations
        return supported is not None and all(op in supported for op in operations)

    @property
    def error_types(self) -> list[str]:
        """Return the error types of the response, in lower case."""
        return [
            e["type"].lower() for e in self.errors if isinstance(e.get("type"), str)
        ]

    def section_unavailable(self, section: str) -> bool:
        """Return True when a part could not be retrieved this time."""
        return f"{SECTION_ERROR_PREFIX[section]}_UNAVAILABLE".lower() in (
            self.error_types
        )

    def section_timestamp(self, section: str) -> datetime | None:
        """Return when the vehicle captured a part of the data."""
        return self.timestamp(section, "carCapturedTimestamp")

    @property
    def last_captured(self) -> datetime | None:
        """Return the most recent capture time over all parts."""
        stamps = [
            stamp
            for section in SECTIONS
            if (stamp := self.section_timestamp(section)) is not None
        ]
        return max(stamps) if stamps else None

    # ---------------------------------------------------------------- range

    def engines(self) -> list[dict[str, Any]]:
        """Return the engines of the fuel status, primary first."""
        return [
            engine
            for key in ("primaryEngineRange", "secondaryEngineRange")
            if isinstance(engine := self.get(SECTION_FUEL, key), dict)
        ]

    def engine(self, engine_type: str) -> dict[str, Any] | None:
        """Return the engine of a type (lower case), if the vehicle has one."""
        for engine in self.engines():
            value = engine.get("engineType")
            if isinstance(value, str) and value.lower() == engine_type:
                return engine
        return None

    @property
    def combustion_engine_types(self) -> list[str]:
        """Return the fuel types of the combustion engines."""
        return [t for t in COMBUSTION_ENGINE_TYPES if self.engine(t) is not None]

    @property
    def battery_range_km(self) -> float | None:
        """Return the range on the high-voltage battery in kilometres."""
        metres = self.number(
            SECTION_CHARGING, "status", "battery", "remainingCruisingRangeInMeters"
        )
        if metres is not None:
            return round(metres / 1000, 1)
        if (engine := self.engine("electric")) is not None:
            value = engine.get("remainingRangeInKm")
            if isinstance(value, int | float) and not isinstance(value, bool):
                return value
        return None

    @property
    def total_range_km(self) -> float | None:
        """Return the total range in kilometres."""
        total = self.number(SECTION_FUEL, "totalRangeInKm")
        return total if total is not None else self.battery_range_km

    # ------------------------------------------------------------- charging

    @property
    def is_charging(self) -> bool | None:
        """Return True while the battery is being charged."""
        state = self.text(SECTION_CHARGING, "status", "state")
        if state is None:
            # The API omits the state for combinations it has no name for.
            if self.plug_connected is False:
                return False
            return None
        return state == "charging"

    @property
    def plug_connected(self) -> bool | None:
        """Return True while a charging cable is plugged in."""
        connected = self.flag(
            SECTION_CHARGING,
            "status",
            "plugConnectionState",
            on="connected",
            off="disconnected",
        )
        if connected is not None:
            return connected
        state = self.text(SECTION_CHARGING, "status", "state")
        if state is None:
            return None
        return state != "connect_cable"

    @property
    def charge_mode_setting(self) -> str | None:
        """Return the charge mode in use, exactly as the API names it."""
        value = self.get(SECTION_CHARGING, "settings", "preferredChargeMode")
        return value if isinstance(value, str) and value else None

    # ------------------------------------------------------ charging profiles

    @property
    def profiles(self) -> list[dict[str, Any]]:
        """Return the charging profiles (saved charging locations)."""
        profiles = self.get(SECTION_CHARGING_PROFILES, "profiles")
        if not isinstance(profiles, list):
            return []
        return [p for p in profiles if isinstance(p, dict) and "id" in p]

    def profile_layout(self) -> dict[str, ProfileLayout]:
        """Return each profile's name and its timers and charging times.

        Entries are named `timer_<id>` and `time_<id>`; `kinds` tells which
        of the two lists the response held.
        """
        layout: dict[str, ProfileLayout] = {}
        for profile in self.profiles:
            kinds = frozenset(
                kind
                for kind, field in PROFILE_ITEM_FIELDS.items()
                if isinstance(profile.get(field), list)
            )
            items = frozenset(
                f"{kind}_{entry['id']}"
                for kind in kinds
                for entry in profile[PROFILE_ITEM_FIELDS[kind]]
                if isinstance(entry, dict) and "id" in entry
            )
            layout[str(profile["id"])] = ProfileLayout(
                profile.get("name"), items, kinds
            )
        return layout

    def profile(self, profile_id: int) -> dict[str, Any] | None:
        """Return one charging profile by its id."""
        for profile in self.profiles:
            if profile.get("id") == profile_id:
                return profile
        return None

    # -------------------------------------------------------------- climate

    @property
    def target_temperature(self) -> float | None:
        """Return the target cabin temperature in degrees Celsius."""
        return self._celsius(SECTION_AIR_CONDITIONING, "targetTemperature")

    def _celsius(self, *path: str) -> float | None:
        value = self.number(*path, "value")
        if value is None:
            return None
        if self.text(*path, "unit") == "fahrenheit":
            return round((value - 32) * 5 / 9, 1)
        return value

    def running(self, section: str) -> bool | None:
        """Return whether a climate function runs; None for an unknown state."""
        state = self.text(section, "state")
        if state in _RUNNING_STATES:
            return True
        if state in _IDLE_STATES:
            return False
        return None

    def section_celsius(self, section: str) -> float | None:
        """Return the target temperature of a part in degrees Celsius."""
        return self._celsius(section, "targetTemperature")
