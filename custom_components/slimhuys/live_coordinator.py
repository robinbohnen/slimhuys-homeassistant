"""Push-coordinator voor SlimHuys → HA pull-mode (SSE-stream + polling-fallback)."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import SlimHuysApiError, SlimHuysAuthError, SlimHuysClient
from .const import (
    DOMAIN,
    POLL_FALLBACK_INTERVAL,
    SSE_RECONNECT_INITIAL_DELAY,
    SSE_RECONNECT_MAX_DELAY,
)

_LOGGER = logging.getLogger(__name__)


class SlimHuysLiveCoordinator(DataUpdateCoordinator):
    """Maintains laatste reading per stream-type, push'ed via SSE.

    State-shape: `self.data` is een dict met sub-dicts per event-type:

        { "p1": {timestamp, active_power_w, ...},
          "water": {timestamp, total_liter},
          ... }

    Sensor-entities lezen hun eigen subkey. Geen merging tussen streams —
    een SSE-event update alleen z'n eigen subkey, andere blijven onaangeroerd.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client: SlimHuysClient,
        *,
        poll_fallback_enabled: bool,
        probe_at_setup: bool,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_live",
            update_interval=None,  # push-driven; geen poll-tick
        )
        self._client = client
        self._poll_fallback_enabled = poll_fallback_enabled
        self._probe_at_setup = probe_at_setup
        self._stream_task: asyncio.Task | None = None
        self._poll_task: asyncio.Task | None = None
        self._consecutive_failures = 0
        self._discovered_fields: set[str] = set()

    @property
    def discovered_fields(self) -> set[str]:
        """Velden die tijdens probe of eerste events zijn gezien.

        Sensor-platform gebruikt dit om 3-fase-entities alleen aan te maken
        voor velden die de meter daadwerkelijk publiceert.
        """
        return self._discovered_fields

    async def async_probe(self) -> None:
        """Eenmalige `/me/usage/current`-call voor initial state + 3-fase-discovery."""
        if not self._probe_at_setup:
            # Geen probe — sensoren starten "unavailable", 3-fase wordt
            # impliciet gediscover'd op het eerste SSE-event.
            self.data = {}
            return
        try:
            snapshot = await self._client.current_usage()
        except SlimHuysAuthError as err:
            raise ConfigEntryAuthFailed("API-key revoked") from err
        except SlimHuysApiError as err:
            _LOGGER.warning("Probe-call faalde, sensoren starten leeg: %s", err)
            self.data = {}
            return

        live = (snapshot or {}).get("live") or {}
        water = (snapshot or {}).get("water") or {}
        self._record_fields(live)
        self.data = {}
        if live:
            self.data["p1"] = live
        if water:
            self.data["water"] = water

    async def async_start(self) -> None:
        """Start de SSE-loop + (optioneel) latente polling-fallback."""
        if self._stream_task is None or self._stream_task.done():
            self._stream_task = self.hass.async_create_background_task(
                self._run_stream_loop(), name="slimhuys-live-sse"
            )
        if self._poll_fallback_enabled and (
            self._poll_task is None or self._poll_task.done()
        ):
            self._poll_task = self.hass.async_create_background_task(
                self._run_poll_fallback_loop(), name="slimhuys-live-poll"
            )

    async def async_stop(self) -> None:
        for task in (self._stream_task, self._poll_task):
            if task and not task.done():
                task.cancel()
        for task in (self._stream_task, self._poll_task):
            if task:
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
        self._stream_task = None
        self._poll_task = None

    async def _run_stream_loop(self) -> None:
        """Reconnect-loop met exponential backoff."""
        backoff = SSE_RECONNECT_INITIAL_DELAY
        while True:
            try:
                async for event_name, payload in self._client.live_events_stream():
                    self._handle_event(event_name, payload)
                    backoff = SSE_RECONNECT_INITIAL_DELAY  # succes → reset
                    self._consecutive_failures = 0
                # Stream eindigde netjes (server 5min-cap) — direct reconnect
                _LOGGER.debug("SSE-stream eindigde, reconnect")
                await asyncio.sleep(SSE_RECONNECT_INITIAL_DELAY)
            except SlimHuysAuthError as err:
                # 401/403 — token revoked. Stop coordinator, surface aan HA.
                _LOGGER.error("SlimHuys API-key revoked: %s", err)
                self.last_update_success = False
                self.async_update_listeners()
                return
            except asyncio.CancelledError:
                raise
            except SlimHuysApiError as err:
                self._consecutive_failures += 1
                _LOGGER.debug(
                    "SSE faalde (#%d), backoff %.1fs: %s",
                    self._consecutive_failures, backoff, err,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, SSE_RECONNECT_MAX_DELAY)
            except Exception as err:  # noqa: BLE001
                self._consecutive_failures += 1
                _LOGGER.warning("Onverwachte SSE-fout: %s", err)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, SSE_RECONNECT_MAX_DELAY)

    async def _run_poll_fallback_loop(self) -> None:
        """Lazy polling-fallback — alleen actief tijdens SSE-onderbreking.

        Activeert na ≥2 opeenvolgende SSE-failures. Zodra de SSE-loop
        weer een event ontvangt, wordt `_consecutive_failures` ge-reset
        naar 0 en valt de fallback automatisch stil. Geen permanente
        dubbel-fetch tijdens stabiele perioden.
        """
        while True:
            try:
                await asyncio.sleep(POLL_FALLBACK_INTERVAL)
                if self._consecutive_failures < 2:
                    # SSE draait stabiel of probeert nog z'n eerste connect
                    continue
                snapshot = await self._client.current_usage()
                live = (snapshot or {}).get("live") or {}
                water = (snapshot or {}).get("water") or {}
                if live:
                    self._handle_event("reading", live)
                if water:
                    self._handle_event("water-reading", water)
            except asyncio.CancelledError:
                raise
            except SlimHuysAuthError:
                # Auth-fout wordt al door SSE-loop afgehandeld; hier niets doen
                pass
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Polling-fallback faalde: %s", err)

    def _handle_event(self, event_name: str, payload: dict[str, Any]) -> None:
        """Map event-name → state-key, push naar listeners."""
        # `hello` is een initial-handshake event uit de SSE-stream — geen data
        if event_name == "hello":
            return

        stream_key = {
            "reading": "p1",
            "water-reading": "water",
            "solar-reading": "solar",
        }.get(event_name)
        if stream_key is None:
            _LOGGER.debug("Onbekend SSE-event-type: %s", event_name)
            return

        self._record_fields(payload)
        new_data = dict(self.data or {})
        new_data[stream_key] = payload
        self.async_set_updated_data(new_data)

    def _record_fields(self, payload: dict[str, Any]) -> None:
        """Track which optionele velden de meter publiceert (3-fase, gas, water)."""
        for key in payload:
            if payload.get(key) is not None:
                self._discovered_fields.add(key)
