"""Write translations/<language>.json from one table of (English, Dutch) texts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

LANGUAGES = ("en", "nl")
TARGET = (
    Path(__file__).parent.parent / "custom_components" / "skoda_api" / "translations"
)

KEYS = "[go.skoda.eu/api-keys]({api_keys_url})"

CHARGE_MODES = {
    "manual": ("Manual", "Handmatig"),
    "timer": ("Timer", "Timer"),
    "timer_charging_with_climatisation": (
        "Timer with air conditioning",
        "Timer met airconditioning",
    ),
    "preferred_charging_times": ("Preferred charging times", "Voorkeurslaadtijden"),
    "only_own_current": ("Own solar power only", "Alleen eigen zonnestroom"),
    "immediate_discharging": ("Immediate discharging", "Direct ontladen"),
    "home_storage_charging": ("Home storage charging", "Laden als thuisbatterij"),
}
MAX_CURRENT = {"maximum": ("Maximum", "Maximaal"), "reduced": ("Reduced", "Verlaagd")}
RUN_STATES = {
    "off": ("Off", "Uit"),
    "cooling": ("Cooling", "Koelen"),
    "heating": ("Heating", "Verwarmen"),
    "heating_auxiliary": ("Auxiliary heating", "Standverwarming"),
    "preheating": ("Preheating", "Voorverwarmen"),
    "ventilation": ("Ventilating", "Ventileren"),
    "completed": ("Completed", "Voltooid"),
}


def states(table: dict[str, tuple[str, str]], *keys: str) -> dict[str, Any]:
    return {key: table[key] for key in (keys or table)}


def entity(
    name: tuple[str, str], state: dict[str, Any] | None = None
) -> dict[str, Any]:
    result: dict[str, Any] = {"name": name}
    if state:
        result["state"] = state
    return result


FUELS = {
    "gasoline": ("Gasoline", "Benzine"),
    "diesel": ("Diesel", "Diesel"),
    "cng": ("CNG", "CNG"),
    "lpg": ("LPG", "LPG"),
}

VEHICLE_FIELD = {
    "name": ("Vehicle", "Wagen"),
    "description": ("The vehicle to control.", "De wagen om te bedienen."),
}

TEXTS: dict[str, Any] = {
    "config": {
        "step": {
            "user": {
                "title": ("Add a Škoda", "Škoda toevoegen"),
                "description": (
                    f"An unofficial integration, not made or supported by Škoda; it uses Škoda's official public API.\n\nCreate an API key in the MyŠkoda app: Settings → Smart Home → API keys, or open {KEYS} on your phone. Select the vehicle the key may access and copy the key at once; it is shown only one time.",
                    f"Een onofficiële integratie, niet gemaakt of ondersteund door Škoda; ze gebruikt de officiële publieke API van Škoda.\n\nMaak een API-sleutel aan in de MyŠkoda-app: Instellingen → Smart Home → API-sleutels, of open {KEYS} op je telefoon. Kies de wagen waarvoor de sleutel geldt en kopieer de sleutel meteen; hij wordt maar één keer getoond.",
                ),
                "data": {
                    "vin": ("VIN", "VIN"),
                    "api_key": ("API key", "API-sleutel"),
                },
                "data_description": {
                    "vin": (
                        "The 17-character vehicle identification number, as shown in the MyŠkoda app and on the registration certificate.",
                        "Het voertuigidentificatienummer van 17 tekens, te vinden in de MyŠkoda-app en op het inschrijvingsbewijs.",
                    ),
                    "api_key": (
                        "The key created in the MyŠkoda app for this vehicle.",
                        "De sleutel die je in de MyŠkoda-app voor deze wagen aanmaakte.",
                    ),
                },
                "sections": {
                    "advanced": {
                        "name": ("Advanced", "Geavanceerd"),
                        "data": {"base_url": ("API address", "API-adres")},
                        "data_description": {
                            "base_url": (
                                "Where the MyŠkoda Public API is reached. Leave unchanged unless Škoda moves it or you run a test server.",
                                "Waar de MyŠkoda Public API bereikbaar is. Laat ongewijzigd, tenzij Škoda het adres wijzigt of je een testserver gebruikt.",
                            )
                        },
                    }
                },
            },
            "reauth_confirm": {
                "title": ("New API key needed", "Nieuwe API-sleutel nodig"),
                "description": (
                    f"The API key of {{name}} has expired or no longer covers the vehicle. Create or update a key in the MyŠkoda app ({KEYS}) and enter it here.",
                    f"De API-sleutel van {{name}} is verlopen of geldt niet meer voor de wagen. Maak of vernieuw een sleutel in de MyŠkoda-app ({KEYS}) en vul hem hier in.",
                ),
                "data": {"api_key": ("API key", "API-sleutel")},
                "data_description": {
                    "api_key": (
                        "The new key for this vehicle.",
                        "De nieuwe sleutel voor deze wagen.",
                    )
                },
            },
            "reconfigure": {
                "title": ("Replace the API key", "API-sleutel vervangen"),
                "description": (
                    f"Enter a new API key for {{name}}. Keys are created in the MyŠkoda app ({KEYS}).",
                    f"Vul een nieuwe API-sleutel in voor {{name}}. Sleutels maak je aan in de MyŠkoda-app ({KEYS}).",
                ),
                "data": {"api_key": ("API key", "API-sleutel")},
                "data_description": {
                    "api_key": (
                        "The new key for this vehicle.",
                        "De nieuwe sleutel voor deze wagen.",
                    )
                },
            },
        },
        "error": {
            "invalid_vin": (
                "A VIN has 17 characters: digits and capital letters, without I, O and Q.",
                "Een VIN telt 17 tekens: cijfers en hoofdletters, zonder I, O en Q.",
            ),
            "invalid_auth": (
                "The API key is invalid or has expired.",
                "De API-sleutel is ongeldig of verlopen.",
            ),
            "key_not_authorized": (
                "This API key does not cover this vehicle. Update the key in the MyŠkoda app and select the vehicle.",
                "Deze API-sleutel geldt niet voor deze wagen. Pas de sleutel aan in de MyŠkoda-app en kies de wagen.",
            ),
            "vehicle_not_found": (
                "No vehicle with this VIN is known.",
                "Er is geen wagen met dit VIN bekend.",
            ),
            "rate_limited": (
                "Too many requests for this vehicle. Try again later.",
                "Te veel aanvragen voor deze wagen. Probeer het later opnieuw.",
            ),
            "cannot_connect": (
                "The Škoda service cannot be reached.",
                "De dienst van Škoda is niet bereikbaar.",
            ),
            "unknown": ("Unexpected error.", "Onverwachte fout."),
        },
        "abort": {
            "already_configured": (
                "This vehicle is already set up.",
                "Deze wagen is al ingesteld.",
            ),
            "reauth_successful": (
                "The new API key is in use.",
                "De nieuwe API-sleutel is in gebruik.",
            ),
            "reconfigure_successful": (
                "The new API key is in use.",
                "De nieuwe API-sleutel is in gebruik.",
            ),
        },
    },
    "options": {
        "step": {
            "init": {
                "title": ("MyŠkoda Public API options", "Opties MyŠkoda Public API"),
                "data": {
                    "poll_interval": ("Update interval", "Verversingsinterval"),
                    "active_poll_interval": (
                        "Update interval while active",
                        "Verversingsinterval tijdens activiteit",
                    ),
                    "fast_poll_when_plugged": (
                        "Fast updates while plugged in",
                        "Sneller verversen met kabel aangesloten",
                    ),
                    "auto_wake_minutes": (
                        "Wake charging vehicle after",
                        "Ladende wagen wekken na",
                    ),
                    "spin": ("S-PIN", "S-PIN"),
                    "readonly": ("Read only", "Alleen lezen"),
                },
                "data_description": {
                    "poll_interval": (
                        "How often the vehicle data is fetched. The API allows 20 requests per vehicle and hour; commands use that budget too.",
                        "Hoe vaak de gegevens van de wagen worden opgehaald. De API laat 20 aanvragen per wagen en per uur toe; commando's tellen daarin mee.",
                    ),
                    "active_poll_interval": (
                        "How often the data is fetched while the vehicle charges or runs its air conditioning, auxiliary heating or ventilation. Never slower than the update interval.",
                        "Hoe vaak de gegevens worden opgehaald terwijl de wagen laadt of de airconditioning, standverwarming of ventilatie werkt. Nooit trager dan het verversingsinterval.",
                    ),
                    "fast_poll_when_plugged": (
                        "Also use the shorter interval while a charging cable is plugged in, without charging.",
                        "Gebruik het kortere interval ook zolang er een laadkabel is aangesloten, zonder te laden.",
                    ),
                    "auto_wake_minutes": (
                        "When a charging vehicle has not reported for this many minutes, ask it for fresh data. Each wake is a command of the hourly quota. 0 switches it off; otherwise 10 to 120.",
                        "Wanneer een ladende wagen zoveel minuten niets meldde, vraag hem om nieuwe gegevens. Elke wekoproep is een commando van het uurtegoed. 0 schakelt het uit; anders 10 tot 120.",
                    ),
                    "spin": (
                        "Only needed to start the auxiliary heating. Leave empty to remove it.",
                        "Alleen nodig om de standverwarming te starten. Laat leeg om hem te wissen.",
                    ),
                    "readonly": (
                        "Show the vehicle without any controls.",
                        "Toon de wagen zonder bediening.",
                    ),
                },
            }
        },
        "error": {
            "invalid_spin": (
                "The S-PIN has four digits.",
                "De S-PIN telt vier cijfers.",
            ),
            "invalid_auto_wake": (
                "Enter 0 to switch it off, or 10 to 120 minutes.",
                "Vul 0 in om het uit te schakelen, of 10 tot 120 minuten.",
            ),
        },
    },
    "issues": {
        "api_key_expiring": {
            "title": (
                "The API key of {name} expires on {date}",
                "De API-sleutel van {name} verloopt op {date}",
            ),
            "description": (
                "Create or update a key in the MyŠkoda app, then use Reconfigure on the MyŠkoda Public API integration to enter it. After the expiry date the vehicle data stops updating.",
                "Maak of vernieuw een sleutel in de MyŠkoda-app en vul hem in via Opnieuw configureren bij de integratie MyŠkoda Public API. Na de vervaldatum worden de gegevens van de wagen niet meer bijgewerkt.",
            ),
        }
    },
    "exceptions": {
        "auth_failed": {
            "message": (
                "The API key is invalid, has expired, or does not cover this vehicle.",
                "De API-sleutel is ongeldig, verlopen of geldt niet voor deze wagen.",
            )
        },
        "rate_limited": {
            "message": (
                "Too many requests for this vehicle; waiting for the quota to refill.",
                "Te veel aanvragen voor deze wagen; wacht tot het tegoed is aangevuld.",
            )
        },
        "update_failed": {
            "message": (
                "The vehicle data could not be fetched: {error}",
                "De gegevens van de wagen konden niet worden opgehaald: {error}",
            )
        },
        "readonly": {
            "message": (
                "This vehicle is set to read only.",
                "Deze wagen staat op alleen lezen.",
            )
        },
        "command_failed": {
            "message": (
                "The command failed: {error}",
                "Het commando is mislukt: {error}",
            )
        },
        "command_not_authorized": {
            "message": (
                "The vehicle refused the command for the owner of the API key.",
                "De wagen weigerde het commando voor de eigenaar van de API-sleutel.",
            )
        },
        "vehicle_declined": {
            "message": (
                "The vehicle is not accepting commands right now. Try again in about {minutes} min.",
                "De wagen aanvaardt nu geen commando's. Probeer het over ongeveer {minutes} min opnieuw.",
            )
        },
        "command_rate_limited": {
            "message": (
                "The hourly request quota of this vehicle is used up. Try again in about {minutes} min.",
                "Het uurtegoed aan aanvragen voor deze wagen is op. Probeer het over ongeveer {minutes} min opnieuw.",
            )
        },
        "refresh_rate_limited": {
            "message": (
                "The API asked to wait until {time} before the next request; the data shown is the last received.",
                "De API vroeg om tot {time} te wachten met de volgende aanvraag; de getoonde gegevens zijn de laatst ontvangen.",
            )
        },
        "command_disabled": {
            "message": (
                "This function is currently switched off for the vehicle.",
                "Deze functie is momenteel uitgeschakeld voor de wagen.",
            )
        },
        "command_not_supported": {
            "message": (
                "The vehicle does not support this function.",
                "De wagen ondersteunt deze functie niet.",
            )
        },
        "command_not_found": {
            "message": (
                "The vehicle or the charging profile is unknown.",
                "De wagen of het laadprofiel is onbekend.",
            )
        },
        "vehicle_timeout": {
            "message": (
                "The vehicle did not respond in time.",
                "De wagen antwoordde niet op tijd.",
            )
        },
        "cannot_connect": {
            "message": (
                "The Škoda service cannot be reached.",
                "De dienst van Škoda is niet bereikbaar.",
            )
        },
        "cable_not_connected": {
            "message": (
                "Charging cannot start: no charging cable is connected.",
                "Het laden kan niet starten: er is geen laadkabel aangesloten.",
            )
        },
        "spin_required": {
            "message": (
                "Starting the auxiliary heating needs the S-PIN. Enter it in the options of the integration.",
                "Om de standverwarming te starten is de S-PIN nodig. Vul hem in bij de opties van de integratie.",
            )
        },
        "profile_not_found": {
            "message": (
                "There is no charging profile {profile}.",
                "Er is geen laadprofiel {profile}.",
            )
        },
        "profile_entry_not_found": {
            "message": (
                "The charging profile has no entry {id} in {field}.",
                "Het laadprofiel heeft geen item {id} in {field}.",
            )
        },
        "vehicle_not_loaded": {
            "message": (
                "This device is not a loaded MyŠkoda Public API vehicle.",
                "Dit apparaat is geen geladen wagen van MyŠkoda Public API.",
            )
        },
        "nothing_to_change": {
            "message": (
                "Give at least one value to change.",
                "Geef minstens één waarde om te wijzigen.",
            )
        },
        "profile_entry_position_not_found": {
            "message": (
                "The charging profile has {count} entries in {field}; there is no position {position}.",
                "Het laadprofiel heeft {count} items in {field}; er is geen positie {position}.",
            )
        },
        "wake_command_pending": {
            "message": (
                "A command is still waiting for the vehicle; wake it once that is done.",
                "Er wacht nog een opdracht op de wagen; wek hem wanneer die klaar is.",
            )
        },
        "wake_not_possible": {
            "message": (
                "The vehicle cannot be woken: it does not report a charge mode or does not accept a new one.",
                "De wagen kan niet worden gewekt: hij meldt geen laadmodus of aanvaardt geen nieuwe.",
            )
        },
        "auto_wake_range": {
            "message": (
                "Enter 0 to switch the automatic wake off, or {min} to {max} minutes.",
                "Vul 0 in om het automatisch wekken uit te schakelen, of {min} tot {max} minuten.",
            )
        },
    },
    "entity": {
        "sensor": {
            "range": entity(("Range", "Actieradius")),
            "electric_range": entity(("Electric range", "Elektrische actieradius")),
            **{
                f"{fuel}_range": entity(
                    (
                        f"{en} range",
                        f"Actieradius {nl.lower() if nl in ('Benzine', 'Diesel') else nl}",
                    )
                )
                for fuel, (en, nl) in FUELS.items()
            },
            **{
                f"{fuel}_level": entity(
                    (
                        f"{en} level",
                        f"{nl}peil" if nl in ("Benzine", "Diesel") else f"{nl}-peil",
                    )
                )
                for fuel, (en, nl) in FUELS.items()
            },
            "adblue_range": entity(("AdBlue range", "Actieradius AdBlue")),
            "car_type": entity(
                ("Drivetrain", "Aandrijving"),
                {"hybrid": ("Hybrid", "Hybride"), **FUELS},
            ),
            "mileage": entity(("Mileage", "Kilometerstand")),
            "battery_percentage": entity(("Battery", "Batterij")),
            "hybrid_battery": entity(("Hybrid battery", "Hybride batterij")),
            "charging_state": entity(
                ("Charging state", "Laadstatus"),
                {
                    "connect_cable": ("Cable not connected", "Kabel niet aangesloten"),
                    "charging": ("Charging", "Laden"),
                    "conserving": ("Conserving", "Lading behouden"),
                    "ready_for_charging": ("Ready to charge", "Klaar om te laden"),
                    "discharging": ("Discharging", "Ontladen"),
                    "charging_interrupted": (
                        "Charging interrupted",
                        "Laden onderbroken",
                    ),
                },
            ),
            "charge_type": entity(
                ("Charge type", "Laadtype"),
                {"ac": ("AC", "AC"), "dc": ("DC", "DC"), "off": ("Off", "Uit")},
            ),
            "charging_power": entity(("Charging power", "Laadvermogen")),
            "charging_rate": entity(("Charging rate", "Laadsnelheid")),
            "remaining_charging_time": entity(
                ("Remaining charging time", "Resterende laadtijd")
            ),
            "fully_charged_at": entity(("Fully charged", "Volledig geladen")),
            "target_battery_percentage": entity(("Charge limit", "Laadlimiet")),
            "charge_mode": entity(("Charge mode", "Laadmodus"), CHARGE_MODES),
            "battery_care_target": entity(
                ("Battery care charge limit", "Laadlimiet batterijzorg")
            ),
            "max_charge_current": entity(
                ("Charging current", "Laadstroom"), MAX_CURRENT
            ),
            "max_charge_current_ampere": entity(
                ("Charging current limit", "Laadstroomlimiet")
            ),
            "charging_location": entity(("Charging location", "Laadlocatie")),
            "next_charging_time": entity(("Next charging time", "Volgende laadtijd")),
            "air_conditioning_state": entity(
                ("Air conditioning state", "Status airconditioning"),
                states(
                    RUN_STATES,
                    "off",
                    "cooling",
                    "heating",
                    "heating_auxiliary",
                    "ventilation",
                    "completed",
                ),
            ),
            "target_temperature": entity(("Target temperature", "Doeltemperatuur")),
            "target_temperature_reached_at": entity(
                ("Target temperature reached", "Doeltemperatuur bereikt")
            ),
            "auxiliary_heating_state": entity(
                ("Auxiliary heating state", "Status standverwarming"),
                states(
                    RUN_STATES, "off", "preheating", "heating_auxiliary", "ventilation"
                ),
            ),
            "auxiliary_heating_duration": entity(
                ("Auxiliary heating duration", "Duur standverwarming")
            ),
            "auxiliary_heating_reached_at": entity(
                (
                    "Auxiliary heating target reached",
                    "Doeltemperatuur standverwarming bereikt",
                )
            ),
            "active_ventilation_state": entity(
                ("Active ventilation state", "Status actieve ventilatie"),
                states(RUN_STATES, "off", "preheating", "ventilation"),
            ),
            "active_ventilation_duration": entity(
                ("Active ventilation duration", "Duur actieve ventilatie")
            ),
            "lock_state": entity(
                ("Lock state", "Slotstatus"),
                {
                    "locked": ("Locked", "Vergrendeld"),
                    "unlocked": ("Unlocked", "Ontgrendeld"),
                    "opened": ("Door or bonnet open", "Deur of motorkap open"),
                    "trunk_opened": ("Trunk open", "Koffer open"),
                },
            ),
            "parking_address": entity(("Parking address", "Parkeeradres")),
            "last_updated": entity(
                ("Last vehicle update", "Laatste update van de wagen")
            ),
            "license_plate": entity(("License plate", "Nummerplaat")),
            "unavailable_data": entity(
                ("Unavailable data", "Niet-beschikbare gegevens")
            ),
            "api_key_expiry": entity(("API key expiry", "Vervaldatum API-sleutel")),
            "api_quota_reset": entity(("API quota refills", "API-tegoed aangevuld")),
            "api_requests_remaining": entity(
                ("API requests remaining", "Resterende API-aanvragen")
            ),
            "last_poll": entity(("Last poll", "Laatste opvraging")),
            "api_status": entity(
                ("API status", "API-status"),
                {
                    "ok": ("OK", "OK"),
                    "skipped_quota": (
                        "Skipped to save quota",
                        "Overgeslagen om tegoed te sparen",
                    ),
                    "rate_limited": ("Rate limited", "Aanvraaglimiet bereikt"),
                    "auth_failed": ("API key refused", "API-sleutel geweigerd"),
                    "error": ("Error", "Fout"),
                },
            ),
            "quota_wait_until": entity(
                ("Waiting for quota until", "Wachten op tegoed tot")
            ),
            "current_poll_interval": {
                **entity(("Current polling interval", "Huidig verversingsinterval")),
                "state_attributes": {
                    "mode": {
                        "name": ("Mode", "Modus"),
                        "state": {
                            "normal": ("Normal", "Normaal"),
                            "active": ("Active", "Actief"),
                        },
                    }
                },
            },
            "charging_profile_schedule": entity(
                ("{profile} schedules", "{profile} schema's")
            ),
        },
        "binary_sensor": {
            "vehicle_lock": entity(("Lock", "Slot")),
            "doors_open": entity(("Doors", "Deuren")),
            "windows_open": entity(("Windows", "Ramen")),
            "trunk_open": entity(("Trunk", "Koffer")),
            "bonnet_open": entity(("Bonnet", "Motorkap")),
            "sunroof_open": entity(("Sunroof", "Zonnedak")),
            "lights_on": entity(("Lights", "Lichten")),
            "vehicle_in_motion": entity(("In motion", "In beweging")),
            "parked_unsecured": entity(("Parked unsecured", "Onbeveiligd geparkeerd")),
            "charging": entity(("Charging", "Laden")),
            "charger_connected": entity(("Charging cable", "Laadkabel")),
            "charger_lock": entity(("Charging cable lock", "Slot laadkabel")),
            "in_saved_location": entity(
                ("At saved charging location", "Op opgeslagen laadlocatie")
            ),
            "battery_care_mode": entity(("Battery care mode", "Batterijzorgmodus")),
            "auto_unlock_plug": entity(
                ("Unlock cable when charged", "Kabel ontgrendelen na laden")
            ),
            "window_heating_front": entity(
                ("Front window heating", "Voorruitverwarming")
            ),
            "window_heating_rear": entity(
                ("Rear window heating", "Achterruitverwarming")
            ),
            "window_heating_enabled": entity(
                (
                    "Window heating with air conditioning",
                    "Ruitverwarming bij airconditioning",
                )
            ),
            "ac_at_unlock": entity(
                ("Air conditioning at unlock", "Airconditioning bij ontgrendelen")
            ),
            "ac_without_external_power": entity(
                (
                    "Air conditioning without external power",
                    "Airconditioning zonder externe stroom",
                )
            ),
        },
        "switch": {
            "charging": entity(("Charging", "Laden")),
            "active_ventilation": entity(("Active ventilation", "Actieve ventilatie")),
            "auxiliary_heating": entity(("Auxiliary heating", "Standverwarming")),
            "charging_profile_auto_unlock_plug": entity(
                (
                    "{profile} unlock cable when charged",
                    "{profile} kabel ontgrendelen na laden",
                )
            ),
            "charging_profile_min_battery_enabled": entity(
                ("{profile} minimum charge", "{profile} minimale lading")
            ),
            "charging_profile_timer": entity(
                ("{profile} timer {number}", "{profile} timer {number}")
            ),
            "charging_profile_time": entity(
                ("{profile} charging time {number}", "{profile} laadtijd {number}")
            ),
            "fast_poll_when_plugged": entity(
                (
                    "Fast polling while plugged in",
                    "Sneller verversen met kabel aangesloten",
                )
            ),
        },
        "time": {
            "charging_profile_timer_time": entity(
                ("{profile} timer {number} time", "{profile} timer {number} tijdstip")
            ),
            "charging_profile_time_start": entity(
                (
                    "{profile} charging time {number} start",
                    "{profile} laadtijd {number} begin",
                )
            ),
            "charging_profile_time_end": entity(
                (
                    "{profile} charging time {number} end",
                    "{profile} laadtijd {number} einde",
                )
            ),
        },
        "number": {
            "charge_limit": entity(("Charge limit", "Laadlimiet")),
            "charging_profile_target": entity(
                ("{profile} charge limit", "{profile} laadlimiet")
            ),
            "charging_profile_min_battery": entity(
                ("{profile} minimum charge level", "{profile} minimaal laadniveau")
            ),
            "poll_interval": entity(("Polling interval", "Verversingsinterval")),
            "active_poll_interval": entity(
                (
                    "Polling interval while active",
                    "Verversingsinterval tijdens activiteit",
                )
            ),
            "auto_wake_minutes": entity(
                ("Wake charging vehicle after", "Ladende wagen wekken na")
            ),
        },
        "select": {
            "charge_mode": entity(("Charge mode", "Laadmodus"), CHARGE_MODES),
            "charging_profile_max_current": entity(
                ("{profile} charging current", "{profile} laadstroom"), MAX_CURRENT
            ),
        },
        "climate": {"climate": entity(("Air conditioning", "Airconditioning"))},
        "image": {"render": entity(("Picture", "Afbeelding"))},
        "button": {
            "refresh": entity(("Refresh data", "Gegevens verversen")),
            "wake": entity(("Wake vehicle", "Wagen wekken")),
        },
    },
    "services": {
        **{
            key: {
                "name": name,
                "description": description,
                "fields": {"device_id": VEHICLE_FIELD},
            }
            for key, name, description in (
                (
                    "start_charging",
                    ("Start charging", "Laden starten"),
                    ("Starts charging a vehicle.", "Start het laden van een wagen."),
                ),
                (
                    "stop_charging",
                    ("Stop charging", "Laden stoppen"),
                    ("Stops charging a vehicle.", "Stopt het laden van een wagen."),
                ),
                (
                    "stop_air_conditioning",
                    ("Stop air conditioning", "Airconditioning stoppen"),
                    (
                        "Stops the air conditioning of a vehicle.",
                        "Stopt de airconditioning van een wagen.",
                    ),
                ),
                (
                    "stop_auxiliary_heating",
                    ("Stop auxiliary heating", "Standverwarming stoppen"),
                    (
                        "Stops the auxiliary heater of a vehicle.",
                        "Stopt de standverwarming van een wagen.",
                    ),
                ),
                (
                    "start_active_ventilation",
                    ("Start active ventilation", "Actieve ventilatie starten"),
                    (
                        "Starts the active ventilation of a vehicle.",
                        "Start de actieve ventilatie van een wagen.",
                    ),
                ),
                (
                    "stop_active_ventilation",
                    ("Stop active ventilation", "Actieve ventilatie stoppen"),
                    (
                        "Stops the active ventilation of a vehicle.",
                        "Stopt de actieve ventilatie van een wagen.",
                    ),
                ),
            )
        },
        "set_charging_limit": {
            "name": ("Set charge limit", "Laadlimiet instellen"),
            "description": (
                "Sets the state of charge at which a vehicle stops charging.",
                "Stelt het laadniveau in waarop een wagen stopt met laden.",
            ),
            "fields": {
                "device_id": VEHICLE_FIELD,
                "target_state_of_charge": {
                    "name": ("Charge limit", "Laadlimiet"),
                    "description": (
                        "Vehicles typically accept 50 to 100 % in steps of 10.",
                        "Wagens aanvaarden doorgaans 50 tot 100 % in stappen van 10.",
                    ),
                },
            },
        },
        "set_charge_mode": {
            "name": ("Set charge mode", "Laadmodus instellen"),
            "description": (
                "Changes how a vehicle decides when to charge.",
                "Wijzigt hoe een wagen bepaalt wanneer hij laadt.",
            ),
            "fields": {
                "device_id": VEHICLE_FIELD,
                "charge_mode": {
                    "name": ("Charge mode", "Laadmodus"),
                    "description": (
                        "One of the modes the vehicle offers.",
                        "Een van de modi die de wagen aanbiedt.",
                    ),
                },
            },
        },
        "start_air_conditioning": {
            "name": ("Start air conditioning", "Airconditioning starten"),
            "description": (
                "Starts the air conditioning of a vehicle, optionally towards a temperature.",
                "Start de airconditioning van een wagen, eventueel naar een temperatuur.",
            ),
            "fields": {
                "device_id": {
                    "name": ("Vehicle", "Wagen"),
                    "description": (
                        "The vehicle to control.",
                        "De wagen om te bedienen.",
                    ),
                },
                "temperature": {
                    "name": ("Temperature", "Temperatuur"),
                    "description": (
                        "Target cabin temperature. Without it the vehicle uses its last one.",
                        "Doeltemperatuur in de wagen. Zonder waarde gebruikt de wagen de vorige.",
                    ),
                },
                "without_external_power": {
                    "name": ("Without external power", "Zonder externe stroom"),
                    "description": (
                        "Allow the air conditioning to run on the battery when no charger is connected.",
                        "Laat de airconditioning op de batterij werken wanneer er geen lader is aangesloten.",
                    ),
                },
            },
        },
        "start_auxiliary_heating": {
            "name": ("Start auxiliary heating", "Standverwarming starten"),
            "description": (
                "Starts the auxiliary heater of a vehicle. Needs the S-PIN.",
                "Start de standverwarming van een wagen. De S-PIN is nodig.",
            ),
            "fields": {
                "device_id": {
                    "name": ("Vehicle", "Wagen"),
                    "description": (
                        "The vehicle to control.",
                        "De wagen om te bedienen.",
                    ),
                },
                "duration": {
                    "name": ("Duration", "Duur"),
                    "description": (
                        "How long the heater runs. Without it the vehicle uses its own setting.",
                        "Hoelang de verwarming werkt. Zonder waarde gebruikt de wagen de eigen instelling.",
                    ),
                },
                "start_mode": {
                    "name": ("Mode", "Modus"),
                    "description": (
                        "Heat or only ventilate.",
                        "Verwarmen of alleen ventileren.",
                    ),
                },
                "temperature": {
                    "name": ("Temperature", "Temperatuur"),
                    "description": (
                        "Target cabin temperature.",
                        "Doeltemperatuur in de wagen.",
                    ),
                },
                "spin": {
                    "name": ("S-PIN", "S-PIN"),
                    "description": (
                        "Only needed when no S-PIN is stored in the options.",
                        "Alleen nodig wanneer er geen S-PIN in de opties staat.",
                    ),
                },
            },
        },
        "update_charging_profile": {
            "name": ("Update charging profile", "Laadprofiel aanpassen"),
            "description": (
                "Changes a charging profile (saved charging location). Only the given values change.",
                "Past een laadprofiel (opgeslagen laadlocatie) aan. Alleen de opgegeven waarden wijzigen.",
            ),
            "fields": {
                "device_id": {
                    "name": ("Vehicle", "Wagen"),
                    "description": (
                        "The vehicle to control.",
                        "De wagen om te bedienen.",
                    ),
                },
                "profile": {
                    "name": ("Profile", "Profiel"),
                    "description": (
                        "Name or id of the charging profile.",
                        "Naam of id van het laadprofiel.",
                    ),
                },
                "name": {
                    "name": ("New name", "Nieuwe naam"),
                    "description": (
                        "Renames the charging profile.",
                        "Geeft het laadprofiel een andere naam.",
                    ),
                },
                "target_state_of_charge": {
                    "name": ("Charge limit", "Laadlimiet"),
                    "description": (
                        "State of charge at which charging stops at this location.",
                        "Laadniveau waarop het laden op deze locatie stopt.",
                    ),
                },
                "max_charging_current": {
                    "name": ("Charging current", "Laadstroom"),
                    "description": ("Maximum or reduced.", "Maximaal of verlaagd."),
                },
                "auto_unlock_plug": {
                    "name": (
                        "Unlock cable when charged",
                        "Kabel ontgrendelen na laden",
                    ),
                    "description": (
                        "Release the charging cable once charging has finished.",
                        "Geef de laadkabel vrij zodra het laden klaar is.",
                    ),
                },
                "min_battery_enabled": {
                    "name": ("Minimum charge", "Minimale lading"),
                    "description": (
                        "Charge at once, whatever the schedule, while the battery is below the minimum level.",
                        "Laad meteen, ongeacht het schema, zolang de batterij onder het minimale niveau zit.",
                    ),
                },
                "min_battery_state_of_charge": {
                    "name": ("Minimum charge level", "Minimaal laadniveau"),
                    "description": (
                        "Level below which charging starts at once.",
                        "Niveau waaronder het laden meteen start.",
                    ),
                },
                "preferred_charging_times": {
                    "name": ("Preferred charging times", "Voorkeurslaadtijden"),
                    "description": (
                        "List of changes. Each names a charging time by its id (the number in its entity name), or by position (its place in the list, from 1), and gives any of enabled, start_time and end_time (HH:MM).",
                        "Lijst met wijzigingen. Elke wijziging noemt een laadtijd bij zijn id (het getal in de naam van zijn entiteit), of bij position (zijn plaats in de lijst, vanaf 1), en geeft een of meer van enabled, start_time en end_time (UU:MM).",
                    ),
                },
                "timers": {
                    "name": ("Timers", "Timers"),
                    "description": (
                        "List of changes. Each names a timer by its id (the number in its entity name), or by position (its place in the list, from 1), and gives any of enabled, time (HH:MM), type (one_off or recurring), one_off_day and recurring_on (weekdays).",
                        "Lijst met wijzigingen. Elke wijziging noemt een timer bij zijn id (het getal in de naam van zijn entiteit), of bij position (zijn plaats in de lijst, vanaf 1), en geeft een of meer van enabled, time (UU:MM), type (one_off of recurring), one_off_day en recurring_on (weekdagen).",
                    ),
                },
            },
        },
    },
    "selector": {
        "start_mode": {
            "options": {
                "heating": ("Heating", "Verwarmen"),
                "ventilation": ("Ventilation", "Ventileren"),
            }
        },
        "max_charging_current": {"options": MAX_CURRENT},
        "charge_mode": {"options": CHARGE_MODES},
    },
}


def pick(node: Any, index: int) -> Any:
    if isinstance(node, tuple):
        return node[index]
    return {key: pick(value, index) for key, value in node.items()}


def main() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    for index, language in enumerate(LANGUAGES):
        path = TARGET / f"{language}.json"
        path.write_text(
            json.dumps(pick(TEXTS, index), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {path.relative_to(TARGET.parent.parent.parent)}")


if __name__ == "__main__":
    main()
