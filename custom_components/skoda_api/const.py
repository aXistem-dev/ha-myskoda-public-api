"""Constants for the MyŠkoda Public API integration."""

from typing import Final

DOMAIN: Final = "skoda_api"
MANUFACTURER: Final = "Škoda"

API_BASE_URL: Final = "https://public.api.connect.skoda-auto.cz"
API_KEYS_URL: Final = "https://go.skoda.eu/api-keys"

CONF_VIN: Final = "vin"
CONF_BASE_URL: Final = "base_url"
CONF_POLL_INTERVAL: Final = "poll_interval"
CONF_SPIN: Final = "spin"
CONF_READONLY: Final = "readonly"
CONF_ACTIVE_POLL_INTERVAL: Final = "active_poll_interval"
CONF_FAST_POLL_WHEN_PLUGGED: Final = "fast_poll_when_plugged"
CONF_AUTO_WAKE_MINUTES: Final = "auto_wake_minutes"

# Polling uses part of the hourly quota; the rest stays free for commands.
DEFAULT_POLL_INTERVAL: Final = 10
MIN_POLL_INTERVAL: Final = 5
MAX_POLL_INTERVAL: Final = 120

# Interval while the vehicle charges or runs its climate functions.
DEFAULT_ACTIVE_POLL_INTERVAL: Final = 5

# Automatic wake of a silent charging vehicle: 0 is off, otherwise this range.
MIN_AUTO_WAKE_MINUTES: Final = 10
MAX_AUTO_WAKE_MINUTES: Final = 120
# An automatic wake is only sent while at least this many requests remain.
AUTO_WAKE_MIN_REMAINING: Final = 6

# Outcome of the last scheduled or forced update, for the API status sensor.
API_STATUS_OK: Final = "ok"
API_STATUS_SKIPPED_QUOTA: Final = "skipped_quota"
API_STATUS_RATE_LIMITED: Final = "rate_limited"
API_STATUS_AUTH_FAILED: Final = "auth_failed"
API_STATUS_ERROR: Final = "error"
API_STATUSES: Final = (
    API_STATUS_OK,
    API_STATUS_SKIPPED_QUOTA,
    API_STATUS_RATE_LIMITED,
    API_STATUS_AUTH_FAILED,
    API_STATUS_ERROR,
)

# Polling settings on the device; they send nothing, so they stay in read only.
SETTING_KEYS: Final = (
    CONF_POLL_INTERVAL,
    CONF_ACTIVE_POLL_INTERVAL,
    CONF_FAST_POLL_WHEN_PLUGGED,
)

# Scheduled polls pause while fewer than this many requests remain, so a
# command can still be sent.
COMMAND_RESERVE: Final = 2

# Seconds an entity shows a requested value the vehicle has not confirmed.
OPTIMISTIC_TIMEOUT: Final = 180

# Refreshes after a command (seconds); the second is skipped once confirmed.
FOLLOW_UP_DELAYS: Final = (30, 120)

# How many polls a part that could not be retrieved keeps its last value.
STALE_SECTION_POLLS: Final = 3

# Fallback wait when a rate-limited response carries no Retry-After header.
DEFAULT_RETRY_AFTER: Final = 300

KEY_EXPIRY_WARNING_DAYS: Final = 14

REQUEST_TIMEOUT: Final = 45

# One action per operation of the API.
SERVICE_START_CHARGING: Final = "start_charging"
SERVICE_STOP_CHARGING: Final = "stop_charging"
SERVICE_SET_CHARGING_LIMIT: Final = "set_charging_limit"
SERVICE_SET_CHARGE_MODE: Final = "set_charge_mode"
SERVICE_UPDATE_CHARGING_PROFILE: Final = "update_charging_profile"
SERVICE_START_AIR_CONDITIONING: Final = "start_air_conditioning"
SERVICE_STOP_AIR_CONDITIONING: Final = "stop_air_conditioning"
SERVICE_START_AUXILIARY_HEATING: Final = "start_auxiliary_heating"
SERVICE_STOP_AUXILIARY_HEATING: Final = "stop_auxiliary_heating"
SERVICE_START_ACTIVE_VENTILATION: Final = "start_active_ventilation"
SERVICE_STOP_ACTIVE_VENTILATION: Final = "stop_active_ventilation"

# Operation names as listed in the vehicle's `operations`.
OP_START_CHARGING: Final = "startCharging"
OP_STOP_CHARGING: Final = "stopCharging"
OP_SET_CHARGING_LIMIT: Final = "setChargingLimit"
OP_SET_CHARGE_MODE: Final = "setChargeMode"
OP_UPDATE_CHARGING_PROFILE: Final = "updateChargingProfile"
OP_START_AIR_CONDITIONING: Final = "startAirConditioning"
OP_STOP_AIR_CONDITIONING: Final = "stopAirConditioning"
OP_START_AUXILIARY_HEATING: Final = "startAuxiliaryHeating"
OP_STOP_AUXILIARY_HEATING: Final = "stopAuxiliaryHeating"
OP_START_ACTIVE_VENTILATION: Final = "startActiveVentilation"
OP_STOP_ACTIVE_VENTILATION: Final = "stopActiveVentilation"

# Parts of the vehicle data, named as in the API response.
SECTION_STATUS: Final = "status"
SECTION_FUEL: Final = "fuelStatus"
SECTION_ODOMETER: Final = "odometer"
SECTION_PARKING: Final = "parkingPosition"
SECTION_AIR_CONDITIONING: Final = "airConditioning"
SECTION_AUXILIARY_HEATING: Final = "auxiliaryHeating"
SECTION_ACTIVE_VENTILATION: Final = "activeVentilation"
SECTION_CHARGING: Final = "charging"
SECTION_CHARGING_PROFILES: Final = "chargingProfiles"

SECTIONS: Final = (
    SECTION_STATUS,
    SECTION_FUEL,
    SECTION_ODOMETER,
    SECTION_PARKING,
    SECTION_AIR_CONDITIONING,
    SECTION_AUXILIARY_HEATING,
    SECTION_ACTIVE_VENTILATION,
    SECTION_CHARGING,
    SECTION_CHARGING_PROFILES,
)

# Error-type prefix the API uses for each part (e.g. CHARGING_UNAVAILABLE).
SECTION_ERROR_PREFIX: Final = {
    SECTION_STATUS: "VEHICLE_STATUS",
    SECTION_FUEL: "FUEL_STATUS",
    SECTION_ODOMETER: "ODOMETER",
    SECTION_PARKING: "PARKING_POSITION",
    SECTION_AIR_CONDITIONING: "AIR_CONDITIONING",
    SECTION_AUXILIARY_HEATING: "AUXILIARY_HEATING",
    SECTION_ACTIVE_VENTILATION: "ACTIVE_VENTILATION",
    SECTION_CHARGING: "CHARGING",
    SECTION_CHARGING_PROFILES: "CHARGING_PROFILES",
}

CHARGE_MODES: Final = (
    "manual",
    "timer",
    "timer_charging_with_climatisation",
    "preferred_charging_times",
    "only_own_current",
    "immediate_discharging",
    "home_storage_charging",
)
COMBUSTION_ENGINE_TYPES: Final = ("gasoline", "diesel", "cng", "lpg")
WEEKDAYS: Final = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

# Lists of timers and preferred charging times, by their short entity name.
FIELD_TIMERS: Final = "timers"
FIELD_TIMES: Final = "preferredChargingTimes"
PROFILE_ITEM_FIELDS: Final = {"timer": FIELD_TIMERS, "time": FIELD_TIMES}

# Automatic wakes in a row without a new report from the vehicle, after which
# it stops until the vehicle reports again.
AUTO_WAKE_MAX_UNANSWERED: Final = 3

# Seconds before the last response is written to disk; longer than any poll
# interval, so in practice it is written at shutdown.
STORE_SAVE_DELAY: Final = (MAX_POLL_INTERVAL + 10) * 60
