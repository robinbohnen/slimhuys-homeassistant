"""Constants for the SlimHuys integration."""
from datetime import timedelta

DOMAIN = "slimhuys"
DEFAULT_BASE_URL = "https://api.slimhuys.nl"

# How often we poll the SlimHuys API for fresh prices.
# Prices update every 15 minutes; 5 min keeps sensors close enough
# without hammering the API.
SCAN_INTERVAL = timedelta(minutes=5)

# Config-flow keys
CONF_API_KEY = "api_key"
CONF_BASE_URL = "base_url"
CONF_SUPPLIER = "supplier"

# Service names
SERVICE_PUSH_READING = "push_reading"

# Reasonable default supplier (can be changed in config flow)
DEFAULT_SUPPLIER = "frank-energie"
