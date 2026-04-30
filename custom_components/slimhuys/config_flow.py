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
    CONF_P1_DELIVERY,
    CONF_P1_ENABLED,
    CONF_P1_INTERVAL,
    CONF_P1_POWER,
    CONF_SUPPLIER,
    DEFAULT_BASE_URL,
    DEFAULT_P1_INTERVAL,
    DEFAULT_SUPPLIER,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _detect_dsmr_sensors(hass) -> dict[str, list[str]]:
    """Scan HA-state for sensors die er als DSMR/P1 uitzien.

    Returnt drie suggestie-lijsten (op naam-pattern) die we als default
    in de dropdowns gebruiken; de user kan zelf elke andere sensor kiezen.
    """
    consumption: list[str] = []
    delivery: list[str] = []
    power: list[str] = []

    for state in hass.states.async_all("sensor"):
        eid = state.entity_id.lower()
        # Cumulatieve verbruik-sensors
        if any(p in eid for p in ["consumption_total", "energy_import", "_import_total", "imported_energy"]):
            consumption.append(state.entity_id)
        # Cumulatieve teruglevering-sensors
        elif any(p in eid for p in ["delivery_total", "energy_export", "_export_total", "exported_energy"]):
            delivery.append(state.entity_id)
        # Realtime vermogen-sensors
        elif any(p in eid for p in ["current_electricity_usage", "active_power", "current_power"]):
            power.append(state.entity_id)

    return {"consumption": consumption, "delivery": delivery, "power": power}


def _all_sensors(hass) -> list[str]:
    return sorted(s.entity_id for s in hass.states.async_all("sensor"))


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
            return self.async_create_entry(
                title=f"SlimHuys ({self._user_email})",
                data=data,
            )

        suggestions = _detect_dsmr_sensors(self.hass)
        all_sensors = _all_sensors(self.hass)
        sensor_choices = {s: s for s in all_sensors}

        # Defaults: 1e detected sensor uit elke categorie (of niets)
        default_consumption = suggestions["consumption"][0] if suggestions["consumption"] else None
        default_delivery = suggestions["delivery"][0] if suggestions["delivery"] else None
        default_power = suggestions["power"][0] if suggestions["power"] else None

        schema_dict: dict[Any, Any] = {
            vol.Required(CONF_P1_ENABLED, default=bool(default_consumption)): bool,
        }
        if sensor_choices:
            schema_dict.update({
                vol.Optional(CONF_P1_CONSUMPTION, default=default_consumption or vol.UNDEFINED): vol.In(sensor_choices),
                vol.Optional(CONF_P1_DELIVERY, default=default_delivery or vol.UNDEFINED): vol.In(sensor_choices),
                vol.Optional(CONF_P1_POWER, default=default_power or vol.UNDEFINED): vol.In(sensor_choices),
                vol.Optional(CONF_P1_INTERVAL, default=DEFAULT_P1_INTERVAL): vol.All(
                    vol.Coerce(int), vol.Range(min=10, max=300)
                ),
            })

        return self.async_show_form(
            step_id="p1_link",
            data_schema=vol.Schema(schema_dict),
            description_placeholders={
                "detected": str(len(suggestions["consumption"]) + len(suggestions["delivery"]) + len(suggestions["power"]))
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return SlimHuysOptionsFlow(config_entry)


class SlimHuysOptionsFlow(config_entries.OptionsFlow):
    """Wijzig leverancier + P1-koppeling achteraf."""

    def __init__(self, config_entry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        session = async_get_clientsession(self.hass)
        client = SlimHuysClient(session, self.config_entry.data[CONF_BASE_URL])
        try:
            suppliers = await client.suppliers()
        except SlimHuysApiError:
            suppliers = []

        choices = {s["id"]: s["name"] for s in suppliers if s.get("active", True)} or {
            DEFAULT_SUPPLIER: "Frank Energie"
        }
        current = self.config_entry.options.get(
            CONF_SUPPLIER, self.config_entry.data.get(CONF_SUPPLIER, DEFAULT_SUPPLIER)
        )

        all_sensors = _all_sensors(self.hass)
        sensor_choices = {s: s for s in all_sensors}
        current_p1 = {
            CONF_P1_ENABLED: self.config_entry.data.get(CONF_P1_ENABLED, False),
            CONF_P1_CONSUMPTION: self.config_entry.data.get(CONF_P1_CONSUMPTION),
            CONF_P1_DELIVERY: self.config_entry.data.get(CONF_P1_DELIVERY),
            CONF_P1_POWER: self.config_entry.data.get(CONF_P1_POWER),
            CONF_P1_INTERVAL: self.config_entry.data.get(CONF_P1_INTERVAL, DEFAULT_P1_INTERVAL),
        }

        schema_dict: dict[Any, Any] = {
            vol.Required(CONF_SUPPLIER, default=current): vol.In(choices),
            vol.Required(CONF_P1_ENABLED, default=current_p1[CONF_P1_ENABLED]): bool,
        }
        if sensor_choices:
            schema_dict.update({
                vol.Optional(
                    CONF_P1_CONSUMPTION,
                    default=current_p1[CONF_P1_CONSUMPTION] or vol.UNDEFINED,
                ): vol.In(sensor_choices),
                vol.Optional(
                    CONF_P1_DELIVERY,
                    default=current_p1[CONF_P1_DELIVERY] or vol.UNDEFINED,
                ): vol.In(sensor_choices),
                vol.Optional(
                    CONF_P1_POWER,
                    default=current_p1[CONF_P1_POWER] or vol.UNDEFINED,
                ): vol.In(sensor_choices),
                vol.Optional(
                    CONF_P1_INTERVAL,
                    default=current_p1[CONF_P1_INTERVAL],
                ): vol.All(vol.Coerce(int), vol.Range(min=10, max=300)),
            })

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema_dict),
        )
