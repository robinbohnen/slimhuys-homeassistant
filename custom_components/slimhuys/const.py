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

# Service names
SERVICE_PUSH_READING = "push_reading"

# Reasonable default supplier
DEFAULT_SUPPLIER = "frank-energie"

# Push every 30 seconds by default — voldoende real-time zonder
# de SlimHuys API of Postmark-rate-limits te raken.
DEFAULT_P1_INTERVAL = 30
