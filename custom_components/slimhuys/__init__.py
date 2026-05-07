"""SlimHuys integration entrypoint."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from time import monotonic
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_call_later, async_track_state_change_event

from .api import SlimHuysApiError, SlimHuysClient
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
    CONF_P1_MODE,
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
    CONF_PULL_POLL_FALLBACK,
    CONF_PULL_PROBE_AT_SETUP,
    CONF_SUPPLIER,
    DEFAULT_BASE_URL,
    DEFAULT_P1_INTERVAL,
    DEFAULT_PULL_POLL_FALLBACK,
    DEFAULT_PULL_PROBE_AT_SETUP,
    DEFAULT_SUPPLIER,
    DOMAIN,
    P1_MODE_NONE,
    P1_MODE_PULL,
    P1_MODE_PUSH,
    SERVICE_PUSH_READING,
)
from .coordinator import SlimHuysCoordinator
from .live_coordinator import SlimHuysLiveCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]

# Optionele velden voor de push_reading-service. Volledige spiegel van wat
# /v1/me/readings accepteert; users kunnen via automation 1-op-1 doorzetten.
PUSH_READING_SCHEMA = vol.Schema(
    {
        vol.Required("consumption_kwh_total"): vol.Coerce(float),
        vol.Required("delivered_kwh_total"): vol.Coerce(float),
        vol.Required("active_power_w"): vol.Coerce(int),
        vol.Optional("active_power_returned_w", default=0): vol.Coerce(int),
        vol.Optional("voltage_l1"): vol.Coerce(float),
        vol.Optional("voltage_l2"): vol.Coerce(float),
        vol.Optional("voltage_l3"): vol.Coerce(float),
        vol.Optional("current_l1_a"): vol.Coerce(float),
        vol.Optional("current_l2_a"): vol.Coerce(float),
        vol.Optional("current_l3_a"): vol.Coerce(float),
        vol.Optional("active_power_l1_w"): vol.Coerce(int),
        vol.Optional("active_power_l2_w"): vol.Coerce(int),
        vol.Optional("active_power_l3_w"): vol.Coerce(int),
        vol.Optional("active_power_returned_l1_w"): vol.Coerce(int),
        vol.Optional("active_power_returned_l2_w"): vol.Coerce(int),
        vol.Optional("active_power_returned_l3_w"): vol.Coerce(int),
        vol.Optional("gas_total_m3"): vol.Coerce(float),
        vol.Optional("tariff_indicator"): vol.In([1, 2]),
        vol.Optional("timestamp"): cv.string,
    }
)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Vertaal entry-schema v1 (`p1_enabled` boolean) → v2 (`p1_mode` enum)."""
    if entry.version >= 2:
        return True

    new_data = {**entry.data}
    new_options = {**entry.options}

    def _get(key, default=None):
        return entry.options.get(key, entry.data.get(key, default))

    # Lege DSMR-config + p1_enabled=True → "none" (push-mode zou toch niet werken).
    has_dsmr_sensors = bool(
        _get(CONF_P1_CONSUMPTION) and _get(CONF_P1_DELIVERY) and _get(CONF_P1_POWER)
    )
    if _get(CONF_P1_ENABLED, False) and has_dsmr_sensors:
        mode = P1_MODE_PUSH
    else:
        mode = P1_MODE_NONE

    if CONF_P1_MODE not in new_options and CONF_P1_MODE not in new_data:
        new_data[CONF_P1_MODE] = mode

    hass.config_entries.async_update_entry(
        entry, data=new_data, options=new_options, version=2
    )
    _LOGGER.info("Slimhuys-entry %s gemigreerd naar v2 (p1_mode=%s)", entry.entry_id, mode)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    session = async_get_clientsession(hass)

    base_url = entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL)
    api_key = entry.data[CONF_API_KEY]
    supplier = entry.options.get(CONF_SUPPLIER, entry.data.get(CONF_SUPPLIER, DEFAULT_SUPPLIER))
    mode = entry.options.get(CONF_P1_MODE, entry.data.get(CONF_P1_MODE, P1_MODE_NONE))

    client = SlimHuysClient(session, base_url, api_key)
    coordinator = SlimHuysCoordinator(hass, client, supplier)
    await coordinator.async_config_entry_first_refresh()

    live_coordinator: SlimHuysLiveCoordinator | None = None
    if mode == P1_MODE_PULL:
        poll_fallback = bool(entry.options.get(
            CONF_PULL_POLL_FALLBACK,
            entry.data.get(CONF_PULL_POLL_FALLBACK, DEFAULT_PULL_POLL_FALLBACK),
        ))
        probe_at_setup = bool(entry.options.get(
            CONF_PULL_PROBE_AT_SETUP,
            entry.data.get(CONF_PULL_PROBE_AT_SETUP, DEFAULT_PULL_PROBE_AT_SETUP),
        ))
        live_coordinator = SlimHuysLiveCoordinator(
            hass, client,
            poll_fallback_enabled=poll_fallback,
            probe_at_setup=probe_at_setup,
        )
        await live_coordinator.async_probe()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
        "live_coordinator": live_coordinator,
        "supplier": supplier,
        "mode": mode,
        "p1_unsub": None,
        "p1_pending_unsub": None,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    if live_coordinator is not None:
        await live_coordinator.async_start()

    if mode == P1_MODE_PUSH:
        # P1-auto-push: state-change-driven (event-driven ipv polling).
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
            optional_keys = (
                "voltage_l1", "voltage_l2", "voltage_l3",
                "current_l1_a", "current_l2_a", "current_l3_a",
                "active_power_l1_w", "active_power_l2_w", "active_power_l3_w",
                "active_power_returned_l1_w", "active_power_returned_l2_w", "active_power_returned_l3_w",
                "gas_total_m3", "tariff_indicator",
            )
            for opt in optional_keys:
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
    if state.get("p1_pending_unsub"):
        state["p1_pending_unsub"]()
    live: SlimHuysLiveCoordinator | None = state.get("live_coordinator")
    if live is not None:
        await live.async_stop()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN] and hass.services.has_service(DOMAIN, SERVICE_PUSH_READING):
            hass.services.async_remove(DOMAIN, SERVICE_PUSH_READING)
    return unload_ok


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _maybe_start_p1_push(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Subscribe op state-change-events van de gekozen DSMR-sensors.

    Pre-v0.3.0 deed dit met een vast polling-interval. Probleem: tussen
    polls werden meter-updates gemist (DSMR pusht ~1Hz, polling op 5s
    miste 4 metingen) én er werden onnodig pushes gedaan tijdens stabiele
    perioden. State-change is event-driven: trigger zodra de meter een
    nieuwe waarde publiceert, met een throttle om de upstream-API niet
    sneller te raken dan de configured push-interval.
    """
    def _get(key, default=None):
        return entry.options.get(key, entry.data.get(key, default))

    enabled = _get(CONF_P1_ENABLED, False)
    consumption = _get(CONF_P1_CONSUMPTION)
    delivery = _get(CONF_P1_DELIVERY)
    power = _get(CONF_P1_POWER)
    interval = max(1, min(300, int(_get(CONF_P1_INTERVAL, DEFAULT_P1_INTERVAL))))

    if not (enabled and consumption and delivery and power):
        return

    voltage_l1 = _get(CONF_P1_VOLTAGE_L1)
    voltage_l2 = _get(CONF_P1_VOLTAGE_L2)
    voltage_l3 = _get(CONF_P1_VOLTAGE_L3)
    current_l1 = _get(CONF_P1_CURRENT_L1)
    current_l2 = _get(CONF_P1_CURRENT_L2)
    current_l3 = _get(CONF_P1_CURRENT_L3)
    power_l1 = _get(CONF_P1_POWER_L1)
    power_l2 = _get(CONF_P1_POWER_L2)
    power_l3 = _get(CONF_P1_POWER_L3)
    power_returned_l1 = _get(CONF_P1_POWER_RETURNED_L1)
    power_returned_l2 = _get(CONF_P1_POWER_RETURNED_L2)
    power_returned_l3 = _get(CONF_P1_POWER_RETURNED_L3)
    gas = _get(CONF_P1_GAS)

    state = hass.data[DOMAIN][entry.entry_id]
    client: SlimHuysClient = state["client"]
    last_push_at = [0.0]  # mutable closure-state, monotonic seconds

    def _read_float(entity_id: str | None) -> float | None:
        if not entity_id:
            return None
        s = hass.states.get(entity_id)
        if not s or s.state in ("unknown", "unavailable", None):
            return None
        try:
            return float(s.state)
        except (ValueError, TypeError):
            return None

    def _read_power_w(entity_id: str | None) -> int | None:
        """Power-sensor kan W of kW zijn — detecteer via unit."""
        if not entity_id:
            return None
        s = hass.states.get(entity_id)
        if not s or s.state in ("unknown", "unavailable", None):
            return None
        try:
            value = float(s.state)
        except (ValueError, TypeError):
            return None
        unit = (s.attributes.get("unit_of_measurement") or "").lower()
        if unit in ("kw", "kilowatt"):
            value *= 1000
        return int(round(value))

    async def _do_push(_now=None) -> None:
        state["p1_pending_unsub"] = None
        c_total = _read_float(consumption)
        d_total = _read_float(delivery)
        p_w = _read_power_w(power)
        if c_total is None or d_total is None or p_w is None:
            return  # essential fields missen; niets doorzetten

        payload: dict[str, Any] = {
            "timestamp": _now_iso(),
            "consumption_kwh_total": c_total,
            "delivered_kwh_total": d_total,
            "active_power_w": p_w,
            "active_power_returned_w": 0,
        }
        # Optionele velden — alleen toevoegen als de sensor configured is
        # én een leesbare waarde heeft. Anders leveren we niets op die key.
        optional_floats = {
            "voltage_l1": voltage_l1, "voltage_l2": voltage_l2, "voltage_l3": voltage_l3,
            "current_l1_a": current_l1, "current_l2_a": current_l2, "current_l3_a": current_l3,
            "gas_total_m3": gas,
        }
        for key, eid in optional_floats.items():
            v = _read_float(eid)
            if v is not None:
                payload[key] = v

        optional_powers = {
            "active_power_l1_w": power_l1,
            "active_power_l2_w": power_l2,
            "active_power_l3_w": power_l3,
            "active_power_returned_l1_w": power_returned_l1,
            "active_power_returned_l2_w": power_returned_l2,
            "active_power_returned_l3_w": power_returned_l3,
        }
        for key, eid in optional_powers.items():
            v = _read_power_w(eid)
            if v is not None:
                payload[key] = v

        try:
            await client.push_readings([payload])
            last_push_at[0] = monotonic()
        except SlimHuysApiError as err:
            _LOGGER.debug("SlimHuys auto-push faalde (silent): %s", err)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Onverwachte fout in P1-push: %s", err)

    @callback
    def _on_state_change(_event) -> None:
        elapsed = monotonic() - last_push_at[0]
        if elapsed >= interval:
            # Genoeg tijd verstreken sinds laatste push — flush direct.
            hass.async_create_task(_do_push())
        elif state.get("p1_pending_unsub") is None:
            # Te kort geleden — schedule één push voor het einde van het
            # interval-window. Verdere state-changes binnen dit window
            # worden gemerged (de _do_push leest gewoon de nieuwste states).
            delay = max(0.1, interval - elapsed)
            state["p1_pending_unsub"] = async_call_later(hass, delay, _do_push)

    sensors_to_watch = [s for s in (
        consumption, delivery, power,
        voltage_l1, voltage_l2, voltage_l3,
        current_l1, current_l2, current_l3,
        power_l1, power_l2, power_l3,
        power_returned_l1, power_returned_l2, power_returned_l3,
        gas,
    ) if s]

    state["p1_unsub"] = async_track_state_change_event(
        hass, sensors_to_watch, _on_state_change
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
