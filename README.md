# MyŠkoda Public API (unofficial)

<img src="custom_components/skoda_api/brand/logo.png" alt="Škoda logo" width="170">

A Home Assistant integration for Škoda vehicles, built on Škoda's official
[MyŠkoda Public API](https://public.api.connect.skoda-auto.cz/docs) and an API
key from the MyŠkoda app.

[![Open your Home Assistant instance and open this repository in the Marketplace.](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=aXistem-dev&repository=ha-myskoda-public-api&category=integration)
[![Open your Home Assistant instance and start setting up MyŠkoda Public API.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=skoda_api)

> **Unofficial.** This integration is not made, endorsed or supported by
> Škoda Auto. It uses Škoda's official public API, under the terms Škoda sets
> for that API (personal use only). Škoda, MyŠkoda and the Škoda logo are
> trademarks of Škoda Auto a.s.

**Contents:** [What you get](#what-you-get) · [Quick start](#quick-start) · [Requirements](#requirements) · [Configuration](#configuration) · [Request quota](#request-quota) · [Entities](#entities) · [Actions](#actions) · [Dashboard](#dashboard) ·
[Waking the vehicle](#waking-the-vehicle) · [Parking alert](#parking-alert) · [Not available in the API](#not-available-in-the-api) · [Troubleshooting](#troubleshooting) · [Privacy](#privacy-and-data-handling) · [Contributing](#contributing) · [Development](#development) · [License](#license-and-credits)

## What you get

- Works for electric cars, plug-in hybrids and combustion cars. Each vehicle
  gets entities only for the data it reports.
- Status, range and fuel, charging, charging locations, air conditioning,
  auxiliary heating, active ventilation and the parking position.
- Every remote command of the API, as a control and as an action.
- No account password in Home Assistant: only the API key.
- Polling that stays within the hourly request quota and keeps a reserve for
  commands.
- A ready-made dashboard that builds itself from your vehicle.
- A blueprint that warns you when the car is parked open or unlocked.

## Quick start

1. **Get an API key.** In the MyŠkoda app open **Settings → Smart Home →
   API keys**, or open <https://go.skoda.eu/api-keys> on your phone. Create a
   key, select the vehicle and copy the key at once: it is shown only one
   time. Keys expire (the app shows the date); a vehicle can have up to five.
2. **Install.** Use the Marketplace button above, install
   **MyŠkoda Public API (unofficial)** and restart Home Assistant.

   <details><summary>Install without the button</summary>

   - **Marketplace:** open **Settings → Marketplace → ⋮ → Custom
     repositories**, add `https://github.com/aXistem-dev/ha-myskoda-public-api`
     with the type **Integration**, install it and restart. On Home Assistant
     before 2026.11 the same steps work in HACS.
   - **Manual:** copy `custom_components/skoda_api` into the
     `custom_components` folder of your configuration and restart.

   </details>
3. **Add the vehicle.** Use the Add integration button above (or **Settings →
   Devices & services → Add integration → MyŠkoda Public API**) and enter the
   17-character **VIN** and the **API key**. The key is checked before the
   vehicle is added. Add more cars the same way, each with its own VIN and key.
4. **Add the dashboard.** Create a new dashboard from scratch, open it,
   choose **Edit → ⋮ → Raw configuration editor** and enter:

   ```yaml
   strategy:
     type: custom:skoda-api
   ```

## Requirements

- Home Assistant 2026.10 or newer.
- MyŠkoda app 8.16 or newer.
- The vehicle in the garage of the MyŠkoda account that created the key.

## Configuration

Open the integration entry and choose **Configure**. Saving reloads the
vehicle, which fetches its data once.

| Option | Range | Default | What it does |
| --- | --- | --- | --- |
| Update interval | 5–120 min | 10 | How often the vehicle data is fetched. |
| Update interval while active | 5–120 min | 5 | Used while the vehicle charges or runs its air conditioning, auxiliary heating or ventilation. Never slower than the update interval. |
| Fast updates while plugged in | on / off | off | Also use the active interval while a cable is plugged in without charging. |
| Wake charging vehicle after | 0, or 10–120 min | 0 (off) | See [Waking the vehicle](#waking-the-vehicle). |
| S-PIN | 4 digits | empty | Only needed to start the auxiliary heating. Leave empty to remove it. |
| Read only | on / off | off | Show the vehicle without any controls; commands and actions are refused. |

The polling settings are also on the device page, where a change applies at
once, without a reload and without a request: **Polling interval**,
**Polling interval while active**, **Fast polling while plugged in** (vehicles
with a charging cable) and **Wake charging vehicle after** (vehicles that can
be woken). The first three stay in read-only mode; the wake setting does not.

**New API key.** When the key has expired or no longer covers the vehicle,
Home Assistant asks for a new one. To swap it earlier, use **Reconfigure** on
the integration entry. A repair notice appears 14 days before the key expires.

## Request quota

The API allows **20 requests per vehicle per hour**, commands included. Every
request for the vehicle counts, also those from scripts or other Home
Assistant instances. The integration plans around that limit:

- **Reserve.** When 2 or fewer requests of the hour are left, scheduled polls
  pause until the quota refills, so a command can still be sent.
- **Follow-ups.** After a command the data is fetched after 30 seconds, and
  again after 2 minutes only if the vehicle has not yet confirmed the result.
  Meanwhile the control shows the requested value, for 3 minutes at most.
- **Rate limit.** When the API refuses a request for the quota, nothing is
  fetched until the time the API gives (or until the quota refills, or
  5 minutes when it gives no time). Entities keep their last values.

| What | Requests |
| --- | --- |
| One poll, or **Refresh data** | 1 |
| An hour of polling every 10 / 5 / 30 min | 6 / 12 / 2 |
| A command (control or action), or **Wake vehicle** | 2 or 3 (the command, one follow-up, one more if the vehicle is slow) |
| Adding a vehicle (key check and first fetch) | 2 |
| Saving the options dialog | 1 |
| Changing a setting on the device page | 0 |

The diagnostic sensors **API requests remaining**, **API quota refills**,
**Waiting for quota until**, **API status**, **Last poll** and **Current
polling interval** show where you stand.

## Entities

Entities appear only for data the vehicle reports; a part that shows up later
is added then. **Charge limit**, **Charge mode** and **Target temperature**
are sensors when the vehicle cannot change them over the API or read-only mode
is on. Each saved charging location gets its own controls, named after it.

<details><summary>All entities</summary>

### Vehicle

| Entity | Type | Notes |
| --- | --- | --- |
| Lock | Binary sensor | On when unlocked |
| Lock state | Sensor | Locked, Unlocked, Door or bonnet open, Trunk open |
| Doors, Trunk, Bonnet, Lights, In motion | Binary sensor | |
| Windows, Sunroof | Binary sensor | Only when the vehicle reports them |
| Parked unsecured | Binary sensor | See [Parking alert](#parking-alert) |
| Mileage, Range | Sensor | Range is the total range |
| *(vehicle name)* | Device tracker | Last parking position, kept while driving; attributes `address`, `in_motion` |
| Parking address | Sensor | |
| Picture | Image | The vehicle as shown in the app |

### Charging

For electric cars and plug-in hybrids.

| Entity | Type | Notes |
| --- | --- | --- |
| Battery | Sensor | State of charge |
| Charging | Switch | Starting is refused while no cable is plugged in |
| Charging, Charging cable | Binary sensor | |
| Charging cable lock | Binary sensor | On when unlocked |
| Charging state | Sensor | Cable not connected, Charging, Conserving, Ready to charge, Discharging, Charging interrupted |
| Charge type | Sensor | AC, DC, Off |
| Charging power, Charging rate | Sensor | kW; km of range per hour |
| Remaining charging time, Fully charged | Sensor | Minutes; expected time |
| Charge limit | Number | 50–100 % in steps of 10 |
| Charge mode | Select | Manual, Timer, Timer with air conditioning, Preferred charging times, Own solar power only, Immediate discharging, Home storage charging, as far as the vehicle offers them |
| Charging current, Charging current limit | Sensor | Maximum or Reduced; amperes |
| Battery care mode, Unlock cable when charged | Binary sensor | |
| Battery care charge limit | Sensor | |
| Charging location, Next charging time | Sensor | The saved charging location the car stands at, and its next charging time |
| At saved charging location | Binary sensor | |
| Wake vehicle | Button | See [Waking the vehicle](#waking-the-vehicle) |

### Charging locations

Shown for a location called *Home*. *n* is the id the vehicle gives a timer or
charging time. Times are in the vehicle's local time.

| Entity | Type | Notes |
| --- | --- | --- |
| Home charge limit | Number | 50–100 % in steps of 10 |
| Home charging current | Select | Maximum or Reduced |
| Home unlock cable when charged | Switch | |
| Home minimum charge | Switch | Charge at once below the minimum level, whatever the schedule |
| Home minimum charge level | Number | 0–100 % in steps of 5 |
| Home timer *n* | Switch | Attributes `time`, `type`, `one_off_day`, `recurring_on` |
| Home timer *n* time | Time | |
| Home charging time *n* | Switch | Attributes `start_time`, `end_time` |
| Home charging time *n* start, end | Time | |
| Home schedules | Sensor | How many timers and charging times are on; attributes list them all |

The controls need a vehicle that accepts profile changes and are not there in
read-only mode; **schedules** is always there. A renamed location renames its
entities. Entities of a deleted location, timer or charging time are removed
once two updates in a row no longer report it. The days of a timer are set
with [`update_charging_profile`](#actions).

### Fuel

For combustion cars and plug-in hybrids.

| Entity | Type | Notes |
| --- | --- | --- |
| Gasoline / Diesel / CNG / LPG range | Sensor | One per fuel the vehicle uses |
| Gasoline / Diesel / CNG / LPG level | Sensor | % |
| AdBlue range | Sensor | When reported |
| Electric range | Sensor | Plug-in hybrids |
| Hybrid battery | Sensor | Plug-in hybrids without the Battery sensor |
| Drivetrain | Sensor | Hybrid, Gasoline, Diesel, CNG, LPG |

### Climate

| Entity | Type | Notes |
| --- | --- | --- |
| Air conditioning | Climate | Off or heat/cool; 15.5–30 °C in steps of 0.5 |
| Air conditioning state | Sensor | Off, Cooling, Heating, Auxiliary heating, Ventilating, Completed |
| Target temperature | Sensor | Only without the climate control |
| Target temperature reached | Sensor | Expected time |
| Front window heating, Rear window heating | Binary sensor | |
| Window heating with air conditioning, Air conditioning at unlock, Air conditioning without external power | Binary sensor | |
| Auxiliary heating | Switch | Starting needs the S-PIN |
| Auxiliary heating state | Sensor | Off, Preheating, Auxiliary heating, Ventilating |
| Auxiliary heating duration, Auxiliary heating target reached | Sensor | Minutes; expected time |
| Active ventilation | Switch | |
| Active ventilation state, Active ventilation duration | Sensor | Off, Preheating, Ventilating; minutes |

The API takes a temperature only with a start. A temperature set while the
air conditioning is off is kept for the next start; while it runs, a new
temperature is sent at once.

### Connection

| Entity | Type | Notes |
| --- | --- | --- |
| Last vehicle update | Sensor | When the vehicle last reported |
| Last poll | Sensor | When the data was last fetched |
| API status | Sensor | OK, Skipped to save quota, Rate limited, API key refused, Error |
| API requests remaining | Sensor | Left this hour; the full quota once it has refilled |
| API quota refills | Sensor | When the quota refills; empty once it has |
| Waiting for quota until | Sensor | Set while the API asks to wait |
| Current polling interval | Sensor | Attribute `mode`: Normal or Active |
| Unavailable data | Sensor | Parts the API could not deliver; attributes `issues`, `stale` |
| API key expiry, License plate | Sensor | |
| Refresh data | Button | Fetch now; also works after a failed update |
| Polling interval, Polling interval while active, Wake charging vehicle after | Number | See [Configuration](#configuration) |
| Fast polling while plugged in | Switch | See [Configuration](#configuration) |

**Last poll**, **API status**, **Waiting for quota until** and **Current
polling interval** stay available when an update fails.

</details>

## Actions

Each action takes the vehicle as `device_id`. It is refused before anything is
sent when the vehicle does not support the command, or in read-only mode.

| Action | What it does |
| --- | --- |
| `skoda_api.start_charging` | Start charging. Refused while no cable is plugged in. |
| `skoda_api.stop_charging` | Stop charging. |
| `skoda_api.set_charging_limit` | Set `target_state_of_charge`. Vehicles typically accept 50–100 in steps of 10. |
| `skoda_api.set_charge_mode` | Set `charge_mode` to one of the modes the vehicle offers. |
| `skoda_api.update_charging_profile` | Change a saved charging location. See below. |
| `skoda_api.start_air_conditioning` | Start; optional `temperature` (15.5–30 °C) and `without_external_power`. |
| `skoda_api.stop_air_conditioning` | Stop the air conditioning. |
| `skoda_api.start_auxiliary_heating` | Start; optional `duration` (5–60 min), `start_mode` (`heating` or `ventilation`), `temperature` and `spin` (else the S-PIN from the options). |
| `skoda_api.stop_auxiliary_heating` | Stop the auxiliary heating. |
| `skoda_api.start_active_ventilation` | Start the active ventilation. |
| `skoda_api.stop_active_ventilation` | Stop the active ventilation. |

Example: charge at home at night only, to 80 %.

```yaml
action: skoda_api.update_charging_profile
data:
  device_id: <your vehicle>
  profile: Home
  target_state_of_charge: 80
  preferred_charging_times:
    - position: 1
      enabled: true
      start_time: "22:00"
      end_time: "06:00"
```

<details><summary>Fields of update_charging_profile</summary>

`profile` is the name or id of the charging location. Only the fields you give
change.

| Field | Meaning |
| --- | --- |
| `name` | New name |
| `target_state_of_charge` | Charge limit at this location |
| `max_charging_current` | `maximum` or `reduced` |
| `auto_unlock_plug` | Unlock the cable when charged |
| `min_battery_enabled` | Charge at once below the minimum level |
| `min_battery_state_of_charge` | The minimum level, 0–100 |
| `preferred_charging_times` | List of changes: `enabled`, `start_time`, `end_time` (HH:MM) |
| `timers` | List of changes: `enabled`, `time` (HH:MM), `type` (`one_off` or `recurring`), `one_off_day`, `recurring_on` (list of weekdays, `monday` to `sunday`) |

Each list entry names an existing timer or charging time, either by `id` (the
number in its entity name, as in "Home timer 2") or by `position` (its place
in the list as the vehicle reports it, from 1). Timers and charging times can
be changed, not added or removed.

</details>

## Dashboard

The dashboard strategy comes with the integration. As a whole dashboard it
shows one tab per vehicle (see [Quick start](#quick-start)); to show one
vehicle as a view inside another dashboard:

```yaml
views:
  - title: Car
    strategy:
      type: custom:skoda-api
      device_id: <id of the vehicle>   # optional with one vehicle
```

| Option | Default | What it does |
| --- | --- | --- |
| `device_id` | all vehicles | Show one vehicle only |
| `show_map` | `true` | Map with the parking position |
| `show_charging_locations` | `true` | The saved charging locations and their settings |
| `show_connection` | `true` | Last update, refresh, wake, quota, key expiry and polling |

The layout follows the vehicle: a diesel shows fuel, an electric car shows
charging. The texts are in English or Dutch, following the user's language.
To have the dashboard explain the setup before a vehicle is added, add
`skoda_api:` on a line of its own to `configuration.yaml`.

## Waking the vehicle

The public API has no wake-up command, and a charging car can stay quiet for a
long time. **Wake vehicle** sends the charge mode the vehicle already uses.
That changes nothing in the car, but makes it send a fresh report. A wake is a
command: 2 or 3 requests. The button exists for vehicles that report a charge
mode and accept a new one, and not in read-only mode.

With **Wake charging vehicle after** set (10–120 minutes; 0 is off), this
happens on its own: when a poll finds the vehicle charging and its last report
at least that old, one wake is sent, and no other within that time. It holds
back while the API asks to wait or fewer than 6 requests of the hour are left,
and stops after 3 wakes in a row without a new report until the vehicle
reports again.

## Parking alert

**Parked unsecured** is on while the vehicle is parked and not secured. Its
`reasons` attribute lists why: `doors_open`, `unlocked`, `windows_open`,
`trunk_open`, `bonnet_open`. Parts the vehicle does not report, or reports as
unsupported, are left out. While the vehicle is in motion the sensor is off.
`reported_at` is the time of the vehicle report.

The integration itself sends no notifications. The blueprint
**Škoda parked unsecured** does:

[![Import the blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FaXistem-dev%2Fha-myskoda-public-api%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fskoda_api%2Fparked_unsecured.yaml)

Give it the Parked unsecured sensor and a notify action such as
`notify.mobile_app_my_phone`. It notifies once the sensor has been on for a
delay (0–120 minutes, default 5), naming the vehicle and the reasons, and can
send a critical notification that sounds also on silent or do not disturb.
The data arrives with each poll, so the alert comes one polling interval after
the car was left at the earliest.

## Not available in the API

Lock and unlock · honk and flash · a real wake-up · trips and trip statistics ·
service intervals · warning lights · software version and updates · departure
timers · seat or window heating commands · outside temperature.

The parking position appears only when the vehicle supports it and has it
switched on.

## Troubleshooting

**There is no "API keys" entry in the MyŠkoda app.**
Update the app to 8.16 or newer, or open <https://go.skoda.eu/api-keys> on the
phone with the app.

**The entities show old values.**
They show what the vehicle reported last; a parked or charging car does not
report all the time. Compare **Last vehicle update** with **Last poll**: a
recent poll with an old vehicle update means the car sent nothing new. Press
**Wake vehicle**, or set **Wake charging vehicle after**.

**The quota is used up.**
Polls pause and the entities keep their values until the quota refills;
**API quota refills** and **Waiting for quota until** tell when. Check for
other users of the vehicle's API keys, such as scripts, a second Home
Assistant or the API reference page, or use a longer update interval.

**A change to a charging location is undone.**
The API replaces a charging location as a whole. When the app and Home
Assistant change the same location at about the same time, the last one wins.
Make one change at a time and wait until it shows.

**The auxiliary heating does not start.**
It needs the S-PIN of your Škoda account: enter it under **Configure**, or
pass `spin` to the action.

**A control is missing or shown as a sensor.**
The vehicle does not offer that command over the API, or read-only mode is on.

**Diagnostics and debug logs for an issue.**
On the integration page choose **Enable debug logging**, reproduce the problem,
then **Disable debug logging** to download the log. Download the diagnostics
from the integration entry (**⋮ → Download diagnostics**). Check both for
anything personal before you attach them.

## Privacy and data handling

- Only the documented endpoints of the MyŠkoda Public API are used, with your
  API key, plus the picture address the API gives. Nothing goes anywhere else.
- Data is fetched by polling; Home Assistant shows what the vehicle reported
  last.
- A part the API cannot deliver keeps its last values for up to 3 polls. For
  that, the last response is kept on disk; removing the vehicle deletes it.
- A refused request is logged with the HTTP status, the problem type and
  Škoda's trace id, with the VIN shortened to its last four characters
  (as a warning for server errors and unexpected refusals; routine ones, such
  as an expired key or a used-up quota, at debug level).
- **Download diagnostics** blanks the VIN, API key, S-PIN, licence plate,
  picture address, position and address, and the names of the vehicle and its
  charging locations.

## Contributing

Bug reports and feature requests are welcome in the
[issue tracker](https://github.com/aXistem-dev/ha-myskoda-public-api/issues).
Please use the issue templates and leave out your VIN, API key, S-PIN, licence
plate and addresses.

## Development

```sh
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

- `tools/mock_api.py` stands in for the API, with sample vehicles, the hourly
  quota and delayed commands: `uv run python tools/mock_api.py --port 8099`.
  Add a sample VIN (`TMBJB9NY5RF999999` electric, `TMBAR7NP9R7999999` diesel,
  `TMBZZZNX1R9999999` plug-in hybrid) with **Advanced → API address** set to
  the mock; any key works except `expired` and `unauthorized`. See `--help`
  for the quota, delay, key expiry and picture options.
- `tools/build_translations.py` writes the translation files from one table
  of English and Dutch texts. Edit the table, not the JSON files.
- `tools/deploy.sh` copies the integration to Home Assistant over SSH:
  `HA_SSH=<host> tools/deploy.sh` (`HA_CONFIG` sets the configuration folder,
  default `/config`).

## License and credits

MIT, see [LICENSE](LICENSE).

Started from
[homeassistant-myskoda](https://github.com/skodaconnect/homeassistant-myskoda)
by the MySkoda authors (MIT).

## Disclaimer

This software is provided as is, without warranty of any kind. Škoda may
change or withdraw the public API at any time, which can break the
integration. Your use of the API is subject to Škoda's terms for the MyŠkoda
Public API, which allow personal use only. You are responsible for the
commands you send to your vehicle.
