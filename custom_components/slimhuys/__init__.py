"""SlimHuys integration entrypoint."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval

from .api import SlimHuysApiError, SlimHuysClient
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
        "p1_unsub": None,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    # P1-auto-push: registreer een interval-listener op de gekozen sensors
    _maybe_start_p1_push(hass, entry)

    # Service push_reading: voor users die liever zelf via automation pushen
    if not hass.services.has_service(DOMAIN, SERVICE_PUSH_READING):
        async def _push_reading(call: ServiceCall) -> None:
            data = PUSH_READING_SCHEMA(dict(call.data))
            payload = {
                "timestamp": data.get("timestamp") or _now_iso(),
                "consumption_kwh_total": data["consumption_kwh_total"],
                "delivered_kwh_total": data["delivered_kwh_total"],
                "active_power_w": data["active_power_w"],
                "active_power_returned_w": data.get("active_power_returned_w", 0),
            }
            for opt in ("voltage_l1", "current_l1_a", "tariff_indicator"):
                if opt in data:
                    payload[opt] = data[opt]

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
    state = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    if state.get("p1_unsub"):
        state["p1_unsub"]()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN] and hass.services.has_service(DOMAIN, SERVICE_PUSH_READING):
            hass.services.async_remove(DOMAIN, SERVICE_PUSH_READING)
    return unload_ok


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _maybe_start_p1_push(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Start een interval-task die de huidige DSMR-states naar SlimHuys pusht.

    Werkt alleen als de user in de config-flow auto-push heeft aangezet en
    sensors heeft gekoppeld. Faalt stil als sensors niet bestaan.
    """
    # Options (van OptionsFlow) wint van data (van originele setup).
    def _get(key, default=None):
        return entry.options.get(key, entry.data.get(key, default))

    enabled = _get(CONF_P1_ENABLED, False)
    consumption = _get(CONF_P1_CONSUMPTION)
    delivery = _get(CONF_P1_DELIVERY)
    power = _get(CONF_P1_POWER)
    interval = int(_get(CONF_P1_INTERVAL, DEFAULT_P1_INTERVAL))

    if not (enabled and consumption and delivery and power):
        return

    state = hass.data[DOMAIN][entry.entry_id]
    client: SlimHuysClient = state["client"]

    async def _tick(now=None) -> None:
        try:
            cs = hass.states.get(consumption)
            ds = hass.states.get(delivery)
            ps = hass.states.get(power)
            if not (cs and ds and ps):
                return
            if cs.state in ("unknown", "unavailable") or ds.state in ("unknown", "unavailable") or ps.state in ("unknown", "unavailable"):
                return

            # Power-sensor kan W of kW zijn — detecteer via unit
            unit = (ps.attributes.get("unit_of_measurement") or "").lower()
            try:
                p_value = float(ps.state)
            except ValueError:
                return
            if unit in ("kw", "kilowatt"):
                p_value = p_value * 1000

            try:
                payload = {
                    "timestamp": _now_iso(),
                    "consumption_kwh_total": float(cs.state),
                    "delivered_kwh_total": float(ds.state),
                    "active_power_w": int(round(p_value)),
                    "active_power_returned_w": 0,
                }
            except (ValueError, TypeError):
                return

            await client.push_readings([payload])
        except SlimHuysApiError as err:
            _LOGGER.debug("SlimHuys auto-push faalde (silent): %s", err)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Onverwachte fout in P1-push: %s", err)

    state["p1_unsub"] = async_track_time_interval(hass, _tick, _interval_timedelta(interval))


def _interval_timedelta(seconds: int):
    from datetime import timedelta
    return timedelta(seconds=max(10, min(300, seconds)))


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
