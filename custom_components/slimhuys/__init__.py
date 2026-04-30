"""SlimHuys integration entrypoint."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SlimHuysApiError, SlimHuysClient
from .const import (
    CONF_API_KEY,
    CONF_BASE_URL,
    CONF_SUPPLIER,
    DEFAULT_BASE_URL,
    DEFAULT_SUPPLIER,
    DOMAIN,
    SERVICE_PUSH_READING,
)
from .coordinator import SlimHuysCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]

PUSH_READING_SCHEMA = vol.Schema(
    {
        vol.Required("consumption_kwh_total"): vol.Coerce(float),
        vol.Required("delivered_kwh_total"): vol.Coerce(float),
        vol.Required("active_power_w"): vol.Coerce(int),
        vol.Optional("active_power_returned_w", default=0): vol.Coerce(int),
        vol.Optional("voltage_l1"): vol.Coerce(float),
        vol.Optional("current_l1_a"): vol.Coerce(float),
        vol.Optional("tariff_indicator"): vol.In([1, 2]),
        vol.Optional("timestamp"): cv.string,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SlimHuys from a config entry."""
    session = async_get_clientsession(hass)

    base_url = entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL)
    api_key = entry.data[CONF_API_KEY]
    supplier = entry.options.get(CONF_SUPPLIER, entry.data.get(CONF_SUPPLIER, DEFAULT_SUPPLIER))

    client = SlimHuysClient(session, base_url, api_key)
    coordinator = SlimHuysCoordinator(hass, client, supplier)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
        "supplier": supplier,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    # Service is per-installation; we register once on the first entry.
    if not hass.services.has_service(DOMAIN, SERVICE_PUSH_READING):
        async def _push_reading(call: ServiceCall) -> None:
            data = PUSH_READING_SCHEMA(dict(call.data))
            payload = {
                "timestamp": data.get("timestamp") or datetime.now().astimezone().isoformat(),
                "consumption_kwh_total": data["consumption_kwh_total"],
                "delivered_kwh_total": data["delivered_kwh_total"],
                "active_power_w": data["active_power_w"],
                "active_power_returned_w": data.get("active_power_returned_w", 0),
            }
            for opt in ("voltage_l1", "current_l1_a", "tariff_indicator"):
                if opt in data:
                    payload[opt] = data[opt]

            # Pak de eerste configured entry — meeste users hebben er één.
            entries = list(hass.data[DOMAIN].values())
            if not entries:
                raise HomeAssistantError("No SlimHuys integration configured")
            cli: SlimHuysClient = entries[0]["client"]
            try:
                await cli.push_readings([payload])
            except SlimHuysApiError as err:
                raise HomeAssistantError(f"SlimHuys push failed: {err}") from err

        hass.services.async_register(
            DOMAIN, SERVICE_PUSH_READING, _push_reading, schema=PUSH_READING_SCHEMA
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN] and hass.services.has_service(DOMAIN, SERVICE_PUSH_READING):
            hass.services.async_remove(DOMAIN, SERVICE_PUSH_READING)
    return unload_ok


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload integration wanneer leverancier wijzigt via OptionsFlow."""
    await hass.config_entries.async_reload(entry.entry_id)
