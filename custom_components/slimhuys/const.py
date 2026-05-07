"""Constants for the SlimHuys integration."""
import json
from datetime import timedelta
from pathlib import Path

DOMAIN = "slimhuys"
DEFAULT_BASE_URL = "https://api.slimhuys.nl"


def _read_manifest_version() -> str:
    """Lees version uit manifest.json — voorkomt drift in User-Agent."""
    try:
        with (Path(__file__).parent / "manifest.json").open() as fh:
            return json.load(fh).get("version", "0.0.0")
    except Exception:  # noqa: BLE001
        return "0.0.0"


VERSION = _read_manifest_version()

# How often we poll the SlimHuys API for fresh prices.
SCAN_INTERVAL = timedelta(minutes=5)

# Config-flow keys
CONF_API_KEY = "api_key"
CONF_BASE_URL = "base_url"
CONF_SUPPLIER = "supplier"
CONF_P1_ENABLED = "p1_enabled"
CONF_P1_CONSUMPTION = "p1_consumption_sensor"
CONF_P1_DELIVERY = "p1_delivery_sensor"
CONF_P1_POWER = "p1_power_sensor"
CONF_P1_INTERVAL = "p1_interval_seconds"

# Optionele 3-fase + gas — leeg laten als de meter ze niet exposeert.
CONF_P1_VOLTAGE_L1 = "p1_voltage_l1_sensor"
CONF_P1_VOLTAGE_L2 = "p1_voltage_l2_sensor"
CONF_P1_VOLTAGE_L3 = "p1_voltage_l3_sensor"
CONF_P1_CURRENT_L1 = "p1_current_l1_sensor"
CONF_P1_CURRENT_L2 = "p1_current_l2_sensor"
CONF_P1_CURRENT_L3 = "p1_current_l3_sensor"
CONF_P1_POWER_L1 = "p1_power_l1_sensor"
CONF_P1_POWER_L2 = "p1_power_l2_sensor"
CONF_P1_POWER_L3 = "p1_power_l3_sensor"
# DSMR publiceert per fase TWEE waarden (consumed + returned). Voor signed
# netto-vermogen per fase moet je beide koppelen.
CONF_P1_POWER_RETURNED_L1 = "p1_power_returned_l1_sensor"
CONF_P1_POWER_RETURNED_L2 = "p1_power_returned_l2_sensor"
CONF_P1_POWER_RETURNED_L3 = "p1_power_returned_l3_sensor"
CONF_P1_GAS = "p1_gas_sensor"

# P1-mode (v0.5.0+): drie wederzijds-exclusieve P1-bronnen per entry.
CONF_P1_MODE = "p1_mode"
P1_MODE_NONE = "none"
P1_MODE_PUSH = "push"  # HA → SlimHuys (DSMR-sensors → POST /me/readings)
P1_MODE_PULL = "pull"  # SlimHuys → HA (SSE /me/usage/live-events → entities)

# Pull-mode opties
CONF_PULL_POLL_FALLBACK = "pull_poll_fallback"
CONF_PULL_PROBE_AT_SETUP = "pull_probe_at_setup"
DEFAULT_PULL_POLL_FALLBACK = True
DEFAULT_PULL_PROBE_AT_SETUP = True

# SSE-tuning
SSE_RECONNECT_INITIAL_DELAY = 1.0
SSE_RECONNECT_MAX_DELAY = 30.0
SSE_HEARTBEAT_TIMEOUT = 45  # 3× server-ping-window van 15s — robuust tegen jitter
POLL_FALLBACK_INTERVAL = 5.0

# Sensor unique-id-suffixes voor pull-mode entities (stabiel over restarts)
LIVE_SUFFIX_ACTIVE_POWER = "live_active_power"
LIVE_SUFFIX_ACTIVE_POWER_RETURNED = "live_active_power_returned"
LIVE_SUFFIX_CONSUMPTION_TOTAL = "live_consumption_total"
LIVE_SUFFIX_DELIVERY_TOTAL = "live_delivery_total"
LIVE_SUFFIX_VOLTAGE_L1 = "live_voltage_l1"
LIVE_SUFFIX_VOLTAGE_L2 = "live_voltage_l2"
LIVE_SUFFIX_VOLTAGE_L3 = "live_voltage_l3"
LIVE_SUFFIX_CURRENT_L1 = "live_current_l1"
LIVE_SUFFIX_CURRENT_L2 = "live_current_l2"
LIVE_SUFFIX_CURRENT_L3 = "live_current_l3"
LIVE_SUFFIX_POWER_L1 = "live_power_l1"
LIVE_SUFFIX_POWER_L2 = "live_power_l2"
LIVE_SUFFIX_POWER_L3 = "live_power_l3"
LIVE_SUFFIX_GAS_TOTAL = "live_gas_total"
LIVE_SUFFIX_WATER_TOTAL = "live_water_total"

# Service names
SERVICE_PUSH_READING = "push_reading"

# Reasonable default supplier
DEFAULT_SUPPLIER = "frank-energie"

# Push every 30 seconds by default — voldoende real-time zonder
# de SlimHuys API of Postmark-rate-limits te raken.
DEFAULT_P1_INTERVAL = 30
