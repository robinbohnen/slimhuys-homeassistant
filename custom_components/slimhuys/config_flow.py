"""Config flow voor SlimHuys — wizard waar de user een API-key + leverancier kiest."""
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
    CONF_SUPPLIER,
    DEFAULT_BASE_URL,
    DEFAULT_SUPPLIER,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class SlimHuysConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the user-facing add-integration wizard."""

    VERSION = 1

    def __init__(self) -> None:
        self._suppliers: list[dict[str, Any]] = []
        self._base_url: str = DEFAULT_BASE_URL
        self._api_key: str | None = None
        self._user_email: str | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Step 1: API-key + base URL."""
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
                # Voorkom duplicate-config voor dezelfde gebruiker.
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
            description_placeholders={"docs_url": "https://slimhuys.nl/app/account?tab=api"},
        )

    async def async_step_supplier(self, user_input: dict[str, Any] | None = None):
        """Step 2: kies een leverancier voor de prijs-sensors."""
        if user_input is not None:
            return self.async_create_entry(
                title=f"SlimHuys ({self._user_email})",
                data={
                    CONF_API_KEY: self._api_key,
                    CONF_BASE_URL: self._base_url,
                    CONF_SUPPLIER: user_input[CONF_SUPPLIER],
                },
            )

        choices = {s["id"]: s["name"] for s in self._suppliers if s.get("active", True)}
        if not choices:
            choices = {DEFAULT_SUPPLIER: "Frank Energie"}

        return self.async_show_form(
            step_id="supplier",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SUPPLIER, default=DEFAULT_SUPPLIER): vol.In(choices),
                }
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return SlimHuysOptionsFlow(config_entry)


class SlimHuysOptionsFlow(config_entries.OptionsFlow):
    """Laat user de leverancier later wisselen zonder opnieuw te configureren."""

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

        choices = {s["id"]: s["name"] for s in suppliers if s.get("active", True)}
        if not choices:
            choices = {DEFAULT_SUPPLIER: "Frank Energie"}

        current = self.config_entry.options.get(
            CONF_SUPPLIER, self.config_entry.data.get(CONF_SUPPLIER, DEFAULT_SUPPLIER)
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SUPPLIER, default=current): vol.In(choices),
                }
            ),
        )
