"""Config flow voor SlimHuys."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SlimHuysApiError, SlimHuysAuthError, SlimHuysClient
from .const import (
    CONF_API_KEY,
    CONF_BASE_URL,
    CONF_P1_CONSUMPTION,
    CONF_P1_CURRENT_L1,
    CONF_P1_CURRENT_L2,
    CONF_P1_CURRENT_L3,
    CONF_P1_DELIVERY,
    CONF_P1_ENABLED,
    CONF_P1_GAS,
    CONF_P1_INTERVAL,
    CONF_P1_POWER,
    CONF_P1_POWER_L1,
    CONF_P1_POWER_L2,
    CONF_P1_POWER_L3,
    CONF_P1_POWER_RETURNED_L1,
    CONF_P1_POWER_RETURNED_L2,
    CONF_P1_POWER_RETURNED_L3,
    CONF_P1_VOLTAGE_L1,
    CONF_P1_VOLTAGE_L2,
    CONF_P1_VOLTAGE_L3,
    CONF_SUPPLIER,
    DEFAULT_BASE_URL,
    DEFAULT_P1_INTERVAL,
    DEFAULT_SUPPLIER,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _detect_dsmr_sensors(hass) -> dict[str, list[str]]:
    """Naam-patroon-suggesties voor de drie defaults in de dropdowns."""
    consumption: list[str] = []
    delivery: list[str] = []
    power: list[str] = []

    for state in hass.states.async_all("sensor"):
        eid = state.entity_id.lower()
        if any(p in eid for p in [
            "consumption_total", "energy_import", "_import_total", "imported_energy",
            "stroom_verbruik_totaal", "verbruik_totaal", "_consumption", "_import",
        ]):
            consumption.append(state.entity_id)
        elif any(p in eid for p in [
            "delivery_total", "energy_export", "_export_total", "exported_energy",
            "_teruglevering_totaal", "teruglevering_totaal", "_delivery", "_export",
        ]):
            delivery.append(state.entity_id)
        elif any(p in eid for p in [
            "current_electricity_usage", "active_power", "current_power",
            "vermogen_nu", "current_consumption_w",
        ]):
            power.append(state.entity_id)

    return {"consumption": consumption, "delivery": delivery, "power": power}


def _energy_sensors(hass) -> list[str]:
    """Sensors met unit kWh — voor cumulatief verbruik / teruglevering."""
    out = []
    for state in hass.states.async_all("sensor"):
        unit = (state.attributes.get("unit_of_measurement") or "").lower()
        if unit == "kwh":
            out.append(state.entity_id)
    return sorted(out)


def _power_sensors(hass) -> list[str]:
    """Sensors met unit W / kW — voor huidig vermogen."""
    out = []
    for state in hass.states.async_all("sensor"):
        unit = (state.attributes.get("unit_of_measurement") or "").lower()
        device_class = (state.attributes.get("device_class") or "").lower()
        if unit in ("w", "kw") or device_class == "power":
            out.append(state.entity_id)
    return sorted(out)


def _voltage_sensors(hass) -> list[str]:
    """Sensors met unit V — voor 3-fase voltage-meting."""
    out = []
    for state in hass.states.async_all("sensor"):
        unit = (state.attributes.get("unit_of_measurement") or "").lower()
        device_class = (state.attributes.get("device_class") or "").lower()
        if unit == "v" or device_class == "voltage":
            out.append(state.entity_id)
    return sorted(out)


def _current_sensors(hass) -> list[str]:
    """Sensors met unit A — voor 3-fase stroom-meting."""
    out = []
    for state in hass.states.async_all("sensor"):
        unit = (state.attributes.get("unit_of_measurement") or "").lower()
        device_class = (state.attributes.get("device_class") or "").lower()
        if unit == "a" or device_class == "current":
            out.append(state.entity_id)
    return sorted(out)


def _gas_sensors(hass) -> list[str]:
    """Sensors met unit m³ of device_class=gas — DSMR-gas-aansluiting."""
    out = []
    for state in hass.states.async_all("sensor"):
        unit = (state.attributes.get("unit_of_measurement") or "").lower()
        device_class = (state.attributes.get("device_class") or "").lower()
        if unit in ("m³", "m3") or device_class == "gas":
            out.append(state.entity_id)
    return sorted(out)


def _suggest_phase(candidates: list[str], phase: str) -> str | None:
    """Pak eerste sensor met '_l1' / '_l2' / '_l3' in de naam."""
    needle = f"_l{phase}"
    return next((s for s in candidates if needle in s.lower()), None)


def _suggest_gas(candidates: list[str]) -> str | None:
    return next((s for s in candidates if "gas" in s.lower()), None) or (
        candidates[0] if candidates else None
    )


def _add_optional_phase_fields(
    schema_dict: dict,
    voltage_choices: dict, current_choices: dict, power_choices: dict, gas_choices: dict,
    voltage_sensors: list, current_sensors: list, power_sensors: list, gas_sensors: list,
    *, defaults: dict | None = None,
) -> None:
    """Voegt de tien optionele 3-fase + gas-dropdowns toe aan een schema-dict.

    Gedeeld tussen Config- en OptionsFlow. `defaults` staat toe om bestaande
    waarden uit een bewaarde entry voor te selecteren — als er geen `defaults`
    zijn (= eerste setup), suggereert de helper sensors waarvan de naam '_l1' /
    '_l2' / '_l3' / 'gas' bevat.
    """
    defaults = defaults or {}

    def _safe_default(value, choices):
        return value if value in choices else vol.UNDEFINED

    def _value_for(key, candidates_by_phase, fallback_suggester=None):
        if key in defaults:
            return _safe_default(defaults[key], _choices_for(key))
        # Suggest from sensor names op basis van phase-indicator.
        suggested = fallback_suggester() if fallback_suggester else None
        return suggested or vol.UNDEFINED

    def _choices_for(key):
        if key in (CONF_P1_VOLTAGE_L1, CONF_P1_VOLTAGE_L2, CONF_P1_VOLTAGE_L3):
            return voltage_choices
        if key in (CONF_P1_CURRENT_L1, CONF_P1_CURRENT_L2, CONF_P1_CURRENT_L3):
            return current_choices
        if key in (CONF_P1_POWER_L1, CONF_P1_POWER_L2, CONF_P1_POWER_L3,
                   CONF_P1_POWER_RETURNED_L1, CONF_P1_POWER_RETURNED_L2, CONF_P1_POWER_RETURNED_L3):
            return power_choices
        if key == CONF_P1_GAS:
            return gas_choices
        return {}

    field_specs = [
        (CONF_P1_VOLTAGE_L1, voltage_sensors, "1"),
        (CONF_P1_VOLTAGE_L2, voltage_sensors, "2"),
        (CONF_P1_VOLTAGE_L3, voltage_sensors, "3"),
        (CONF_P1_CURRENT_L1, current_sensors, "1"),
        (CONF_P1_CURRENT_L2, current_sensors, "2"),
        (CONF_P1_CURRENT_L3, current_sensors, "3"),
        (CONF_P1_POWER_L1, power_sensors, "1"),
        (CONF_P1_POWER_L2, power_sensors, "2"),
        (CONF_P1_POWER_L3, power_sensors, "3"),
        (CONF_P1_POWER_RETURNED_L1, power_sensors, "1"),
        (CONF_P1_POWER_RETURNED_L2, power_sensors, "2"),
        (CONF_P1_POWER_RETURNED_L3, power_sensors, "3"),
    ]
    for key, candidates, phase in field_specs:
        choices = _choices_for(key)
        if not choices:
            continue
        default = _value_for(key, candidates, lambda c=candidates, p=phase: _suggest_phase(c, p))
        schema_dict[vol.Optional(key, default=default)] = vol.In({**choices, "": "—"})

    if gas_choices:
        default = _value_for(CONF_P1_GAS, gas_sensors, lambda c=gas_sensors: _suggest_gas(c))
        schema_dict[vol.Optional(CONF_P1_GAS, default=default)] = vol.In({**gas_choices, "": "—"})


class SlimHuysConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Multi-step setup wizard."""

    VERSION = 1

    def __init__(self) -> None:
        self._suppliers: list[dict[str, Any]] = []
        self._base_url: str = DEFAULT_BASE_URL
        self._api_key: str | None = None
        self._user_email: str | None = None
        self._supplier: str = DEFAULT_SUPPLIER

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Stap 1: API-key + base URL."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._base_url = user_input.get(CONF_BASE_URL, DEFAULT_BASE_URL).rstrip("/")
            self._api_key = user_input[CONF_API_KEY].strip()

            session = async_get_clientsession(self.hass)
            client = SlimHuysClient(session, self._base_url, self._api_key)
            try:
                profile = await client.whoami()
                self._user_email = profile.get("email")
                self._suppliers = await client.suppliers()
            except SlimHuysAuthError:
                errors["base"] = "invalid_auth"
            except SlimHuysApiError as err:
                _LOGGER.warning("SlimHuys API onbereikbaar: %s", err)
                errors["base"] = "cannot_connect"

            if not errors:
                await self.async_set_unique_id(self._user_email)
                self._abort_if_unique_id_configured()
                return await self.async_step_supplier()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): str,
                    vol.Optional(CONF_BASE_URL, default=DEFAULT_BASE_URL): str,
                }
            ),
            errors=errors,
        )

    async def async_step_supplier(self, user_input: dict[str, Any] | None = None):
        """Stap 2: leverancier kiezen."""
        if user_input is not None:
            self._supplier = user_input[CONF_SUPPLIER]
            return await self.async_step_p1_link()

        choices = {s["id"]: s["name"] for s in self._suppliers if s.get("active", True)}
        if not choices:
            choices = {DEFAULT_SUPPLIER: "Frank Energie"}

        return self.async_show_form(
            step_id="supplier",
            data_schema=vol.Schema(
                {vol.Required(CONF_SUPPLIER, default=DEFAULT_SUPPLIER): vol.In(choices)}
            ),
        )

    async def async_step_p1_link(self, user_input: dict[str, Any] | None = None):
        """Stap 3: P1-meter koppelen — pak DSMR-sensors uit dropdowns.

        Optioneel; user kan 'm uitzetten en zelf later via service-call pushen.
        """
        if user_input is not None:
            data = {
                CONF_API_KEY: self._api_key,
                CONF_BASE_URL: self._base_url,
                CONF_SUPPLIER: self._supplier,
                CONF_P1_ENABLED: user_input.get(CONF_P1_ENABLED, False),
            }
            if data[CONF_P1_ENABLED]:
                data[CONF_P1_CONSUMPTION] = user_input.get(CONF_P1_CONSUMPTION)
                data[CONF_P1_DELIVERY] = user_input.get(CONF_P1_DELIVERY)
                data[CONF_P1_POWER] = user_input.get(CONF_P1_POWER)
                data[CONF_P1_INTERVAL] = int(user_input.get(CONF_P1_INTERVAL, DEFAULT_P1_INTERVAL))
                # Alle optionele 3-fase + gas — alleen opslaan als de user
                # er expliciet een sensor voor heeft gekozen.
                for opt_key in (
                    CONF_P1_VOLTAGE_L1, CONF_P1_VOLTAGE_L2, CONF_P1_VOLTAGE_L3,
                    CONF_P1_CURRENT_L1, CONF_P1_CURRENT_L2, CONF_P1_CURRENT_L3,
                    CONF_P1_POWER_L1, CONF_P1_POWER_L2, CONF_P1_POWER_L3,
                    CONF_P1_POWER_RETURNED_L1, CONF_P1_POWER_RETURNED_L2, CONF_P1_POWER_RETURNED_L3,
                    CONF_P1_GAS,
                ):
                    if user_input.get(opt_key):
                        data[opt_key] = user_input[opt_key]
            return self.async_create_entry(
                title=f"SlimHuys ({self._user_email})",
                data=data,
            )

        suggestions = _detect_dsmr_sensors(self.hass)
        energy_sensors = _energy_sensors(self.hass)
        power_sensors = _power_sensors(self.hass)
        voltage_sensors = _voltage_sensors(self.hass)
        current_sensors = _current_sensors(self.hass)
        gas_sensors = _gas_sensors(self.hass)

        energy_choices = {s: s for s in energy_sensors}
        power_choices = {s: s for s in power_sensors}
        voltage_choices = {s: s for s in voltage_sensors}
        current_choices = {s: s for s in current_sensors}
        gas_choices = {s: s for s in gas_sensors}

        default_consumption = next(
            (s for s in suggestions["consumption"] if s in energy_sensors), None
        ) or (energy_sensors[0] if energy_sensors else None)
        default_delivery = next(
            (s for s in suggestions["delivery"] if s in energy_sensors), None
        ) or (energy_sensors[1] if len(energy_sensors) > 1 else None)
        default_power = next(
            (s for s in suggestions["power"] if s in power_sensors), None
        ) or (power_sensors[0] if power_sensors else None)

        schema_dict: dict[Any, Any] = {
            vol.Required(CONF_P1_ENABLED, default=bool(default_consumption)): bool,
        }
        if energy_choices and power_choices:
            schema_dict.update({
                vol.Optional(CONF_P1_CONSUMPTION, default=default_consumption or vol.UNDEFINED): vol.In(energy_choices),
                vol.Optional(CONF_P1_DELIVERY, default=default_delivery or vol.UNDEFINED): vol.In(energy_choices),
                vol.Optional(CONF_P1_POWER, default=default_power or vol.UNDEFINED): vol.In(power_choices),
                vol.Optional(CONF_P1_INTERVAL, default=DEFAULT_P1_INTERVAL): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=300)
                ),
            })
            _add_optional_phase_fields(
                schema_dict,
                voltage_choices, current_choices, power_choices, gas_choices,
                voltage_sensors, current_sensors, power_sensors, gas_sensors,
            )

        return self.async_show_form(
            step_id="p1_link",
            data_schema=vol.Schema(schema_dict),
            description_placeholders={
                "energy_count": str(len(energy_sensors)),
                "power_count": str(len(power_sensors)),
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return SlimHuysOptionsFlow()


class SlimHuysOptionsFlow(config_entries.OptionsFlow):
    """Wijzig leverancier + P1-koppeling achteraf.

    HA 2024.12+ stelt self.config_entry automatisch in — geen __init__
    nodig (en de oude pattern conflicteert met de nieuwe property).
    """

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            # Filter lege strings (de "—"-keuze) zodat optionele velden
            # echt unset blijven ipv een lege string opslaan.
            cleaned = {k: v for k, v in user_input.items() if v != ""}
            return self.async_create_entry(title="", data=cleaned)

        entry = self.config_entry

        # Suppliers ophalen — als API onbereikbaar, sane fallback.
        try:
            session = async_get_clientsession(self.hass)
            client = SlimHuysClient(session, entry.data.get(CONF_BASE_URL, "https://api.slimhuys.nl"))
            suppliers = await client.suppliers()
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("OptionsFlow kon suppliers niet laden: %s", err)
            suppliers = []

        choices = {s["id"]: s["name"] for s in suppliers if s.get("active", True)} or {
            DEFAULT_SUPPLIER: "Frank Energie"
        }

        # Huidige instellingen — eerst options, dan data, dan default.
        def get(key, default=None):
            return entry.options.get(key, entry.data.get(key, default))

        current_supplier = get(CONF_SUPPLIER, DEFAULT_SUPPLIER)
        current_p1_enabled = bool(get(CONF_P1_ENABLED, False))
        current_p1_consumption = get(CONF_P1_CONSUMPTION)
        current_p1_delivery = get(CONF_P1_DELIVERY)
        current_p1_power = get(CONF_P1_POWER)
        current_p1_interval = int(get(CONF_P1_INTERVAL, DEFAULT_P1_INTERVAL))

        energy_sensors = _energy_sensors(self.hass)
        power_sensors = _power_sensors(self.hass)
        voltage_sensors = _voltage_sensors(self.hass)
        current_sensors = _current_sensors(self.hass)
        gas_sensors = _gas_sensors(self.hass)
        energy_choices = {s: s for s in energy_sensors}
        power_choices = {s: s for s in power_sensors}
        voltage_choices = {s: s for s in voltage_sensors}
        current_choices = {s: s for s in current_sensors}
        gas_choices = {s: s for s in gas_sensors}

        def safe_default(value, choices):
            return value if value in choices else vol.UNDEFINED

        schema_dict: dict[Any, Any] = {
            vol.Required(CONF_SUPPLIER, default=current_supplier): vol.In(choices),
            vol.Required(CONF_P1_ENABLED, default=current_p1_enabled): bool,
        }
        if energy_choices and power_choices:
            schema_dict.update({
                vol.Optional(CONF_P1_CONSUMPTION, default=safe_default(current_p1_consumption, energy_choices)): vol.In(energy_choices),
                vol.Optional(CONF_P1_DELIVERY, default=safe_default(current_p1_delivery, energy_choices)): vol.In(energy_choices),
                vol.Optional(CONF_P1_POWER, default=safe_default(current_p1_power, power_choices)): vol.In(power_choices),
                vol.Optional(CONF_P1_INTERVAL, default=current_p1_interval): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=300)
                ),
            })
            optional_defaults = {
                k: v for k in (
                    CONF_P1_VOLTAGE_L1, CONF_P1_VOLTAGE_L2, CONF_P1_VOLTAGE_L3,
                    CONF_P1_CURRENT_L1, CONF_P1_CURRENT_L2, CONF_P1_CURRENT_L3,
                    CONF_P1_POWER_L1, CONF_P1_POWER_L2, CONF_P1_POWER_L3,
                    CONF_P1_POWER_RETURNED_L1, CONF_P1_POWER_RETURNED_L2, CONF_P1_POWER_RETURNED_L3,
                    CONF_P1_GAS,
                ) if (v := get(k))
            }
            _add_optional_phase_fields(
                schema_dict,
                voltage_choices, current_choices, power_choices, gas_choices,
                voltage_sensors, current_sensors, power_sensors, gas_sensors,
                defaults=optional_defaults,
            )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema_dict),
        )
