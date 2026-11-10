/*
 * Dashboard strategy of the MyŠkoda Public API integration: `custom:skoda-api`
 * as a dashboard or a view. Options: device_id, show_map,
 * show_charging_locations, show_connection.
 */

const PLATFORM = "skoda_api";

const TEXTS = {
  en: {
    charging: "Charging",
    climate: "Climate",
    status: "Doors and windows",
    fuel: "Fuel and range",
    location: "Location",
    locations: "Charging locations",
    charging_times: "Preferred charging times",
    timers: "Timers",
    charging_details: "Charging details",
    climate_details: "Climate settings",
    here: "car is here",
    connection: "Connection",
    polling: "Polling",
    no_vehicle_title: "No vehicle yet",
    no_vehicle:
      "Add your Škoda to see it here.\n\n" +
      "1. In the MyŠkoda app open **Settings → Smart Home → API keys** and create a key for your car. Copy it at once: it is shown only one time.\n" +
      "2. In Home Assistant open [MyŠkoda Public API](/config/integrations/integration/skoda_api), add the vehicle and enter its VIN and the key.\n" +
      "3. Reload this page.",
  },
  nl: {
    charging: "Laden",
    climate: "Klimaat",
    status: "Deuren en ramen",
    fuel: "Brandstof en actieradius",
    location: "Locatie",
    locations: "Laadlocaties",
    charging_times: "Voorkeurslaadtijden",
    timers: "Timers",
    charging_details: "Laaddetails",
    climate_details: "Klimaatinstellingen",
    here: "wagen staat hier",
    connection: "Verbinding",
    polling: "Verversen",
    no_vehicle_title: "Nog geen wagen",
    no_vehicle:
      "Voeg je Škoda toe om hem hier te zien.\n\n" +
      "1. Open in de MyŠkoda-app **Instellingen → Smart Home → API-sleutels** en maak een sleutel aan voor je wagen. Kopieer hem meteen: hij wordt maar één keer getoond.\n" +
      "2. Open in Home Assistant [MyŠkoda Public API](/config/integrations/integration/skoda_api), voeg de wagen toe en vul het VIN en de sleutel in.\n" +
      "3. Herlaad deze pagina.",
  },
};

const texts = (hass) => {
  const language = (hass.locale?.language || hass.language || "en").split("-")[0];
  return TEXTS[language] || TEXTS.en;
};

/** The vehicles of this integration: device id -> { name, entities }. */
const vehicles = (hass) => {
  const found = new Map();
  for (const entry of Object.values(hass.entities || {})) {
    if (entry.platform !== PLATFORM || !entry.device_id || entry.hidden) continue;
    const state = hass.states[entry.entity_id];
    // An entity the integration no longer provides lingers as a restored state.
    if (!state || state.attributes.restored) continue;
    if (!found.has(entry.device_id)) {
      const device = hass.devices?.[entry.device_id] || {};
      found.set(entry.device_id, {
        id: entry.device_id,
        name: device.name_by_user || device.name || "Škoda",
        entities: [],
      });
    }
    found.get(entry.device_id).entities.push(entry);
  }
  return [...found.values()].sort((a, b) => a.name.localeCompare(b.name));
};

/** Everything needed to lay out one vehicle. */
class Vehicle {
  constructor(hass, vehicle) {
    this.hass = hass;
    this.name = vehicle.name;
    this.byKey = new Map();
    this.profiles = new Map();
    for (const entry of vehicle.entities) {
      const domain = entry.entity_id.split(".")[0];
      const key = `${domain}.${entry.translation_key}`;
      const attributes = hass.states[entry.entity_id].attributes;
      // Told by the key: other entities may name a profile too.
      const ofProfile = (entry.translation_key || "").startsWith("charging_profile_");
      if (ofProfile && attributes.profile_id !== undefined) {
        if (!this.profiles.has(attributes.profile_id)) {
          this.profiles.set(attributes.profile_id, {
            name: attributes.profile_name || String(attributes.profile_id),
            byKey: new Map(),
            items: new Map(),
          });
        }
        const profile = this.profiles.get(attributes.profile_id);
        if (attributes.item_id === undefined) {
          profile.byKey.set(key, entry.entity_id);
        } else {
          // A timer or a preferred charging time: several entities per entry.
          const kind = entry.translation_key.startsWith("charging_profile_timer")
            ? "timer"
            : "time";
          const id = `${kind}:${attributes.item_id}`;
          if (!profile.items.has(id)) {
            profile.items.set(id, { kind, number: attributes.item_id, byKey: new Map() });
          }
          profile.items.get(id).byKey.set(key, entry.entity_id);
        }
      } else {
        this.byKey.set(key, entry.entity_id);
      }
    }
  }

  id(key) {
    return this.byKey.get(key);
  }

  /** The entity's own name, without the vehicle name in front. */
  label(entityId) {
    const name = this.hass.states[entityId]?.attributes.friendly_name || entityId;
    return name.startsWith(`${this.name} `) ? name.slice(this.name.length + 1) : name;
  }

  tile(entityId, options = {}) {
    if (!entityId) return undefined;
    const { columns = 6, name, hide_unknown: hideUnknown, visibility, ...rest } = options;
    const card = {
      type: "tile",
      entity: entityId,
      name: name || this.label(entityId),
      grid_options: { columns },
      ...rest,
    };
    if (entityId.startsWith("button.")) {
      const press = {
        action: "perform-action",
        perform_action: "button.press",
        target: { entity_id: entityId },
      };
      card.tap_action = press;
      card.icon_tap_action = press;
      card.hide_state = true;
    }
    const conditions = [...(visibility || [])];
    if (hideUnknown) {
      // A value the vehicle only reports now and then takes no room meanwhile.
      conditions.push(
        { condition: "state", entity: entityId, state_not: "unknown" },
        { condition: "state", entity: entityId, state_not: "unavailable" }
      );
    }
    if (conditions.length) card.visibility = conditions;
    return card;
  }

  /** Tiles for the given keys; keys the vehicle lacks are left out. */
  tiles(keys, options = {}) {
    return keys
      .map((key) => {
        const [id, extra] = Array.isArray(key) ? key : [key, {}];
        return this.tile(this.id(id), { ...options, ...extra });
      })
      .filter(Boolean);
  }
}

const heading = (title, icon, extra = {}) => ({
  type: "heading",
  heading: title,
  heading_style: "title",
  icon,
  ...extra,
});

const section = (cards, extra = {}) => ({ type: "grid", cards, ...extra });

/** A titled group of cards, or nothing when the vehicle has none of them. */
const group = (title, icon, cards) =>
  cards.length ? [heading(title, icon), ...cards] : [];

const TOGGLE = { features: [{ type: "toggle" }], features_position: "inline" };
const SLIDER = { columns: 12, features: [{ type: "numeric-input", style: "slider" }] };
const OPTIONS = { columns: 12, features: [{ type: "select-options" }] };
const STEPPER = { columns: 12, features: [{ type: "numeric-input", style: "buttons" }] };
const WARN = { color: "red" };
const HIDE = { hide_unknown: true };

/** Show a card only while an entity is in a state; no entity, no condition. */
const when = (entityId, state) =>
  entityId ? { visibility: [{ condition: "state", entity: entityId, state }] } : {};

const subtitle = (title, icon) => ({
  type: "heading",
  heading: title,
  heading_style: "subtitle",
  icon,
});

/** Cards folded away behind a title line; visibility conditions do not apply inside. */
const collapse = (title, icon, cards, extra = {}) =>
  cards.length
    ? [
        {
          type: "custom:skoda-api-collapse",
          title,
          icon,
          cards,
          grid_options: { columns: 12 },
          ...extra,
        },
      ]
    : [];

const overviewGroup = (v) => {
  const cards = [];
  const updated = v.id("sensor.last_updated");
  cards.push(
    heading(v.name, "mdi:car", {
      badges: updated
        ? [{ type: "entity", entity: updated, show_state: true, show_icon: true }]
        : [],
    })
  );
  const picture = v.id("image.render");
  if (picture) {
    cards.push({
      type: "picture-entity",
      entity: picture,
      show_name: false,
      show_state: false,
      grid_options: { columns: 12 },
    });
  }
  const level = { features: [{ type: "bar-gauge", min: 0, max: 100 }] };
  const unsecured = v.id("binary_sensor.parked_unsecured");
  cards.push(
    ...v.tiles([
      ["sensor.battery_percentage", { columns: 12, color: "green", ...level }],
      // The fuel status level of a plug-in hybrid, when charging lacks one.
      ...(v.id("sensor.battery_percentage")
        ? []
        : [["sensor.hybrid_battery", { columns: 12, color: "green", ...level }]]),
      ["sensor.gasoline_level", { columns: 12, ...level }],
      ["sensor.diesel_level", { columns: 12, ...level }],
      ["sensor.cng_level", { columns: 12, ...level }],
      ["sensor.lpg_level", { columns: 12, ...level }],
      "sensor.range",
      "sensor.mileage",
      // Locked is the normal case; an unlocked car stands out.
      ["binary_sensor.vehicle_lock", { columns: 12, ...WARN }],
      // Only there while the parked car is open or unlocked.
      ["binary_sensor.parked_unsecured", { columns: 12, ...WARN, ...when(unsecured, "on") }],
    ])
  );
  return cards;
};

const chargingGroup = (v, t) => {
  // Starting and stopping only means something with a cable plugged in.
  const cable = v.id("binary_sensor.charger_connected");
  const plugged = cable
    ? { visibility: [{ condition: "state", entity: cable, state_not: "off" }] }
    : {};
  // Power, speed and time left say nothing while the car is not charging.
  const charging = when(v.id("binary_sensor.charging"), "on");
  const modes = v.hass.states[v.id("select.charge_mode")]?.attributes.options || [];
  const cards = v.tiles([
    "sensor.charging_state",
    "binary_sensor.charger_connected",
    ["switch.charging", { ...TOGGLE, columns: 12, color: "green", ...plugged }],
    ["sensor.charging_power", charging],
    ["sensor.charging_rate", charging],
    ["sensor.remaining_charging_time", { ...charging, ...HIDE }],
    ["sensor.fully_charged_at", { ...charging, ...HIDE }],
    ["number.charge_limit", SLIDER],
    "sensor.target_battery_percentage",
    // A vehicle that offers one mode has nothing to choose.
    ...(modes.length > 1 ? [["select.charge_mode", OPTIONS]] : []),
    "sensor.charge_mode",
    // Only known while the car stands at one of its charging locations.
    ["sensor.charging_location", HIDE],
    ["sensor.next_charging_time", HIDE],
  ]);
  // Without a control the charging state is still worth showing.
  if (!v.id("switch.charging")) {
    cards.splice(2, 0, ...v.tiles([["binary_sensor.charging", { color: "green" }]]));
  }
  const details = v.tiles([
    "sensor.charge_type",
    "binary_sensor.charger_lock",
    "sensor.max_charge_current",
    "sensor.max_charge_current_ampere",
    "binary_sensor.battery_care_mode",
    "sensor.battery_care_target",
    ["binary_sensor.auto_unlock_plug", { columns: 12 }],
    ["binary_sensor.in_saved_location", { columns: 12 }],
  ]);
  cards.push(
    ...collapse(t.charging_details, "mdi:tune-variant", details, {
      summary: [v.id("sensor.max_charge_current"), v.id("sensor.charge_type")].filter(
        Boolean
      ),
    })
  );
  return group(t.charging, "mdi:ev-station", cards);
};

const climateGroup = (v, t) => {
  const heated = (key) => [key, { color: "orange", ...when(v.id(key), "on") }];
  const cards = v.tiles([
    [
      "climate.climate",
      {
        columns: 12,
        features: [{ type: "climate-hvac-modes" }, { type: "target-temperature" }],
      },
    ],
    // The state sensor would repeat what the climate tile shows.
    ...(v.id("climate.climate")
      ? []
      : ["sensor.air_conditioning_state", "sensor.target_temperature"]),
    ["sensor.target_temperature_reached_at", { columns: 12, ...HIDE }],
    // Shown while the heating is actually on.
    heated("binary_sensor.window_heating_front"),
    heated("binary_sensor.window_heating_rear"),
    ["switch.auxiliary_heating", { ...TOGGLE, columns: 12, color: "orange" }],
    "sensor.auxiliary_heating_state",
    ["sensor.auxiliary_heating_reached_at", HIDE],
    ["switch.active_ventilation", { ...TOGGLE, columns: 12, color: "cyan" }],
    "sensor.active_ventilation_state",
  ]);
  const details = v.tiles([
    "binary_sensor.window_heating_front",
    "binary_sensor.window_heating_rear",
    ["binary_sensor.window_heating_enabled", { columns: 12 }],
    ["binary_sensor.ac_at_unlock", { columns: 12 }],
    ["binary_sensor.ac_without_external_power", { columns: 12 }],
    "sensor.auxiliary_heating_duration",
    "sensor.active_ventilation_duration",
  ]);
  cards.push(...collapse(t.climate_details, "mdi:tune-variant", details));
  return group(t.climate, "mdi:air-conditioner", cards);
};

const statusGroup = (v, t) =>
  group(
    t.status,
    "mdi:car-door",
    v.tiles(
      [
        "binary_sensor.doors_open",
        "binary_sensor.windows_open",
        "binary_sensor.trunk_open",
        "binary_sensor.bonnet_open",
        "binary_sensor.sunroof_open",
        ["binary_sensor.lights_on", { color: "amber" }],
      ],
      WARN
    )
  );

const fuelGroup = (v, t) =>
  group(
    t.fuel,
    "mdi:gas-station",
    v.tiles([
      "sensor.gasoline_range",
      "sensor.diesel_range",
      "sensor.cng_range",
      "sensor.lpg_range",
      "sensor.electric_range",
      "sensor.adblue_range",
    ])
  );

const locationGroup = (v, t, config) => {
  const tracker = v.id("device_tracker.parking_position");
  const moving = v.id("binary_sensor.vehicle_in_motion");
  const cards = [];
  // On the move the car reports no position; say so above the last one.
  cards.push(
    ...v.tiles([[
      "binary_sensor.vehicle_in_motion",
      { columns: 12, color: "amber", ...when(moving, "on") },
    ]])
  );
  if (tracker && config.show_map !== false) {
    cards.push({
      type: "map",
      entities: [tracker],
      default_zoom: 15,
      grid_options: { columns: 12, rows: 5 },
      visibility: [
        { condition: "state", entity: tracker, state_not: "unknown" },
        { condition: "state", entity: tracker, state_not: "unavailable" },
      ],
    });
  }
  cards.push(...v.tiles([["sensor.parking_address", { columns: 12, ...HIDE }]]));
  return group(t.location, "mdi:map-marker", cards);
};

/** Short weekday names in the language of the user, keyed as the API names them. */
const weekdays = (hass) => {
  const language = hass.locale?.language || hass.language || "en";
  const format = new Intl.DateTimeFormat(language, { weekday: "short", timeZone: "UTC" });
  const names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];
  // 1 January 2024 was a Monday.
  return Object.fromEntries(
    names.map((name, index) => [name, format.format(new Date(Date.UTC(2024, 0, 1 + index)))])
  );
};

/** The settings of each charging location, folded away behind its name. */
const locationsGroup = (v, t, config) => {
  if (config.show_charging_locations === false) return [];
  const cards = [];
  const days = weekdays(v.hass);
  const sorted = [...v.profiles.values()].sort((a, b) => a.name.localeCompare(b.name));
  for (const profile of sorted) {
    // "Home charge limit" reads better as "Charge limit" under a Home heading.
    const strip = (entityId) => {
      const label = v.label(entityId);
      if (!label.startsWith(`${profile.name} `)) return label;
      const rest = label.slice(profile.name.length + 1);
      return rest.charAt(0).toUpperCase() + rest.slice(1);
    };
    const tile = (entityId, options = {}) =>
      entityId ? v.tile(entityId, { name: strip(entityId), ...options }) : undefined;
    const setting = (key, options) => tile(profile.byKey.get(key), options);

    const inner = [
      setting("number.charging_profile_target", SLIDER),
      setting("select.charging_profile_max_current", OPTIONS),
      setting("switch.charging_profile_auto_unlock_plug", { ...TOGGLE, columns: 12 }),
      setting("switch.charging_profile_min_battery_enabled", { ...TOGGLE, columns: 12 }),
      setting("number.charging_profile_min_battery", SLIDER),
    ].filter(Boolean);

    const entries = (kind) =>
      [...profile.items.values()]
        .filter((item) => item.kind === kind)
        .sort((a, b) => a.number - b.number);
    const times = entries("time").flatMap((item) =>
      [
        tile(item.byKey.get("switch.charging_profile_time"), { ...TOGGLE, columns: 12 }),
        tile(item.byKey.get("time.charging_profile_time_start")),
        tile(item.byKey.get("time.charging_profile_time_end")),
      ].filter(Boolean)
    );
    if (times.length) {
      inner.push(subtitle(t.charging_times, "mdi:clock-outline"), ...times);
    }
    const timers = entries("timer").flatMap((item) => {
      const switchId = item.byKey.get("switch.charging_profile_timer");
      // The days a timer runs on, next to its name: "Timer 1 · Mon, Fri".
      const attributes = v.hass.states[switchId]?.attributes || {};
      const on =
        attributes.type === "one_off"
          ? [attributes.one_off_day]
          : attributes.recurring_on || [];
      const shown = on.map((day) => days[day]).filter(Boolean).join(", ");
      const name = switchId && shown ? `${strip(switchId)} · ${shown}` : undefined;
      return [
        tile(switchId, { ...TOGGLE, columns: 12, ...(name ? { name } : {}) }),
        tile(item.byKey.get("time.charging_profile_timer_time"), { columns: 12 }),
      ].filter(Boolean);
    });
    if (timers.length) {
      inner.push(subtitle(t.timers, "mdi:timer-outline"), ...timers);
    }
    // Without anything to set, the schedule overview is all there is.
    if (!inner.length) {
      const schedule = setting("sensor.charging_profile_schedule", { columns: 12 });
      if (schedule) inner.push(schedule);
    }

    cards.push(
      ...collapse(profile.name, "mdi:home-lightning-bolt-outline", inner, {
        summary: [
          profile.byKey.get("number.charging_profile_target"),
          profile.byKey.get("select.charging_profile_max_current"),
        ].filter(Boolean),
        // The location the car stands at is marked.
        active: { entity: v.id("sensor.charging_location"), state: profile.name },
        active_icon: "mdi:map-marker-check",
        active_label: t.here,
      })
    );
  }
  return group(t.locations, "mdi:map-marker-star", cards);
};

const connectionGroup = (v, t, config) => {
  if (config.show_connection === false) return [];
  const issues = v.id("sensor.unavailable_data");
  const cards = v.tiles([
    "sensor.last_updated",
    "button.refresh",
    // Asks the car for a fresh report; a command of the hourly quota.
    ["button.wake", { columns: 12 }],
    "sensor.api_requests_remaining",
    ["sensor.api_quota_reset", { hide_unknown: true }],
    // Only while the API has asked to wait.
    ["sensor.quota_wait_until", { columns: 12, color: "orange", hide_unknown: true }],
    ["sensor.api_key_expiry", { columns: 12 }],
    // Worth a look only when the vehicle left something out.
    [
      "sensor.unavailable_data",
      {
        columns: 12,
        color: "red",
        visibility: issues
          ? [{ condition: "numeric_state", entity: issues, above: 0 }]
          : undefined,
      },
    ],
  ]);
  // How and how often the data is fetched: set once, looked at rarely.
  const polling = v.tiles([
    "sensor.api_status",
    "sensor.last_poll",
    "sensor.current_poll_interval",
    ["number.poll_interval", STEPPER],
    ["number.active_poll_interval", STEPPER],
    ["switch.fast_poll_when_plugged", { ...TOGGLE, columns: 12 }],
    ["number.auto_wake_minutes", STEPPER],
  ]);
  cards.push(
    ...collapse(t.polling, "mdi:timer-sync-outline", polling, {
      summary: [v.id("sensor.current_poll_interval"), v.id("sensor.api_status")].filter(
        Boolean
      ),
    })
  );
  return group(t.connection, "mdi:cloud-sync", cards);
};

/** Three sections of related groups, stacked in this order on a narrow screen. */
const vehicleSections = (hass, vehicle, config) => {
  const v = new Vehicle(hass, vehicle);
  const t = texts(hass);
  return [
    [...overviewGroup(v), ...statusGroup(v, t)],
    [...chargingGroup(v, t), ...fuelGroup(v, t), ...climateGroup(v, t)],
    [
      ...locationGroup(v, t, config),
      ...locationsGroup(v, t, config),
      ...connectionGroup(v, t, config),
    ],
  ]
    .filter((cards) => cards.length)
    .map((cards) => section(cards));
};

const emptyView = (hass) => {
  const t = texts(hass);
  return {
    title: "Škoda",
    icon: "mdi:car",
    type: "sections",
    max_columns: 1,
    sections: [
      section([
        heading(t.no_vehicle_title, "mdi:car-off"),
        { type: "markdown", content: t.no_vehicle },
      ]),
    ],
  };
};

const vehicleView = (hass, vehicle, config) => ({
  title: vehicle.name,
  path: `skoda-${vehicle.id.slice(0, 8)}`,
  type: "sections",
  max_columns: 3,
  sections: vehicleSections(hass, vehicle, config),
});

const selected = (hass, config) => {
  const all = vehicles(hass);
  return config.device_id ? all.filter((v) => v.id === config.device_id) : all;
};

class SkodaApiDashboardStrategy extends HTMLElement {
  static async generate(config, hass) {
    const found = selected(hass, config);
    return {
      title: "Škoda",
      views: found.length
        ? found.map((vehicle) => vehicleView(hass, vehicle, config))
        : [emptyView(hass)],
    };
  }
}

class SkodaApiViewStrategy extends HTMLElement {
  static async generate(config, hass) {
    const [vehicle] = selected(hass, config);
    if (!vehicle) {
      const { title, icon, path, ...view } = emptyView(hass);
      return view;
    }
    return {
      type: "sections",
      max_columns: 3,
      sections: vehicleSections(hass, vehicle, config),
    };
  }
}

/**
 * A card that folds other cards away behind a title line.
 *
 *   type: custom:skoda-api-collapse
 *   title: Home
 *   icon: mdi:home
 *   summary: [number.car_home_charge_limit]   # states shown under the title
 *   active: { entity: sensor.car_charging_location, state: Home }
 *   active_icon: mdi:map-marker-check         # icon and label while active
 *   active_label: car is here
 *   open: false
 *   cards: [...]
 *
 * It is drawn with the elements and the variables of the active theme. The
 * cards inside are created when it is first opened.
 */
class SkodaApiCollapse extends HTMLElement {
  setConfig(config) {
    if (!Array.isArray(config.cards)) throw new Error("cards is required");
    this._config = config;
    this._open = Boolean(config.open);
    this._cards = undefined;
    if (this.shadowRoot) this.shadowRoot.innerHTML = "";
    this._root = undefined;
    this._update();
  }

  set hass(hass) {
    this._hass = hass;
    for (const card of this._cards || []) card.hass = hass;
    this._update();
  }

  getCardSize() {
    return 1;
  }

  getGridOptions() {
    return { columns: 12, rows: "auto", min_columns: 6 };
  }

  _build() {
    const root = this.attachShadow ? this.shadowRoot || this.attachShadow({ mode: "open" }) : this;
    root.innerHTML = `
      <style>
        :host { display: block; }
        .head {
          display: flex; align-items: center; gap: 12px;
          padding: 10px 12px; min-height: 36px;
          cursor: pointer; user-select: none;
          border-radius: var(--ha-card-border-radius, 12px);
          outline: none;
        }
        .head:focus-visible { box-shadow: 0 0 0 2px var(--primary-color); }
        .icon { color: var(--state-icon-color, var(--secondary-text-color)); flex: none; }
        :host([active]) .icon { color: var(--state-active-color, var(--primary-color)); }
        .text { flex: 1; min-width: 0; }
        .title {
          color: var(--primary-text-color); font-weight: 500;
          overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
        }
        .summary {
          color: var(--secondary-text-color); font-size: 0.85em;
          overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
        }
        .chevron { color: var(--secondary-text-color); flex: none; transition: transform 0.2s; }
        :host([open]) .chevron { transform: rotate(180deg); }
        .body {
          display: none; grid-template-columns: repeat(12, minmax(0, 1fr));
          gap: var(--ha-section-grid-row-gap, 8px) var(--ha-section-grid-column-gap, 8px);
          padding: 0 12px 12px;
        }
        :host([open]) .body { display: grid; }
      </style>
      <ha-card>
        <div class="head" role="button" tabindex="0" aria-expanded="false">
          <ha-icon class="icon"></ha-icon>
          <div class="text"><div class="title"></div><div class="summary"></div></div>
          <ha-icon class="chevron" icon="mdi:chevron-down"></ha-icon>
        </div>
        <div class="body"></div>
      </ha-card>`;
    const head = root.querySelector(".head");
    head.addEventListener("click", () => this._toggle());
    head.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        this._toggle();
      }
    });
    this._root = root;
  }

  _toggle() {
    this._open = !this._open;
    this._update();
  }

  async _fill() {
    this._cards = [];
    const helpers = await window.loadCardHelpers();
    const body = this._root.querySelector(".body");
    for (const config of this._config.cards) {
      const card = helpers.createCardElement(config);
      const columns = config.grid_options?.columns;
      card.style.gridColumn = `span ${Number.isInteger(columns) ? columns : 12}`;
      if (this._hass) card.hass = this._hass;
      body.appendChild(card);
      this._cards.push(card);
    }
  }

  /** True while the entity named under `active` is in the given state. */
  _active() {
    const { entity, state } = this._config.active || {};
    return Boolean(entity && this._hass?.states[entity]?.state === state);
  }

  _summary() {
    const hass = this._hass;
    if (!hass) return "";
    return (this._config.summary || [])
      .map((entityId) => hass.states[entityId])
      .filter((state) => state && !["unknown", "unavailable"].includes(state.state))
      .map((state) => (hass.formatEntityState ? hass.formatEntityState(state) : state.state))
      .join(" · ");
  }

  _update() {
    if (!this._config) return;
    if (!this._root) this._build();
    const root = this._root;
    const active = this._active();
    const icon = (active && this._config.active_icon) || this._config.icon || "mdi:tune";
    root.querySelector(".icon").setAttribute("icon", icon);
    root.querySelector(".title").textContent = this._config.title || "";
    root.querySelector(".summary").textContent = [
      active ? this._config.active_label : "",
      this._summary(),
    ]
      .filter(Boolean)
      .join(" · ");
    this.toggleAttribute("active", active);
    root.querySelector(".head").setAttribute("aria-expanded", String(this._open));
    this.toggleAttribute("open", this._open);
    if (this._open && !this._cards) this._fill();
  }
}

const ELEMENTS = {
  "skoda-api-collapse": SkodaApiCollapse,
  "ll-strategy-dashboard-skoda-api": SkodaApiDashboardStrategy,
  "ll-strategy-view-skoda-api": SkodaApiViewStrategy,
};

/*
 * Home Assistant replaces the element registry while it starts, so the
 * elements are defined only once its root element is registered.
 */
const register = () => {
  if (!customElements.get("home-assistant")) return false;
  for (const [tag, element] of Object.entries(ELEMENTS)) {
    if (!customElements.get(tag)) customElements.define(tag, element);
  }
  return true;
};

if (!register()) {
  const timer = setInterval(() => {
    if (register()) clearInterval(timer);
  }, 50);
}
