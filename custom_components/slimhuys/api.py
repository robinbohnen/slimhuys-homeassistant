"""Async HTTP client for the SlimHuys API."""
from __future__ import annotations

import asyncio
import json as _json
import logging
from typing import Any, AsyncIterator

import aiohttp

from .const import SSE_HEARTBEAT_TIMEOUT, VERSION

_LOGGER = logging.getLogger(__name__)


class SlimHuysApiError(Exception):
    """Raised when the API returns a non-2xx response or times out."""


class SlimHuysAuthError(SlimHuysApiError):
    """Raised on 401/403 — the user's API key is invalid or revoked."""


class SlimHuysClient:
    """Lightweight async client for the SlimHuys public + bearer-auth API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        api_key: str | None = None,
    ) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    def _headers(self, *, with_auth: bool = False) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": f"slimhuys-ha/{VERSION}",
        }
        if with_auth and self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
        with_auth: bool = False,
    ) -> Any:
        url = f"{self._base_url}{path}"
        try:
            async with asyncio.timeout(15):
                async with self._session.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    headers=self._headers(with_auth=with_auth),
                ) as resp:
                    text = await resp.text()
                    if resp.status in (401, 403):
                        raise SlimHuysAuthError(f"{resp.status}: {text[:200]}")
                    if resp.status >= 400:
                        raise SlimHuysApiError(f"HTTP {resp.status}: {text[:200]}")
                    if not text:
                        return None
                    return await resp.json(content_type=None)
        except (asyncio.TimeoutError, TimeoutError) as err:
            raise SlimHuysApiError("timeout") from err
        except aiohttp.ClientError as err:
            raise SlimHuysApiError(f"transport: {err}") from err

    # ----- Public endpoints (no auth) -----

    async def current_price(self, supplier: str) -> dict[str, Any]:
        return await self._request(
            "GET",
            "/v1/prices/current",
            params={"supplier": supplier},
        )

    async def price_range(
        self,
        supplier: str,
        from_iso: str,
        to_iso: str,
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            "/v1/prices/range",
            params={"supplier": supplier, "from": from_iso, "to": to_iso},
        )

    async def suppliers(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/v1/suppliers")
        return data.get("suppliers", []) if data else []

    # ----- Auth-required endpoints -----

    async def whoami(self) -> dict[str, Any]:
        """Verify the API key + return profile info. Used by config-flow."""
        return await self._request("GET", "/v1/me", with_auth=True)

    async def push_readings(self, readings: list[dict[str, Any]]) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/v1/me/readings",
            json={"readings": readings},
            with_auth=True,
        )

    async def current_usage(self) -> dict[str, Any]:
        """Snapshot — `live` (laatste reading), `today`, `meter`, `solar`.

        Gebruikt voor (a) probe bij setup om te bepalen welke 3-fase-velden
        de meter exposeert, (b) polling-fallback wanneer SSE faalt.
        """
        return await self._request("GET", "/v1/me/usage/current", with_auth=True)

    async def live_events_stream(self) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Async generator over `/v1/me/usage/live-events` (Server-Sent Events).

        Yield't `(event_name, parsed_json_data)`-tuples per binnenkomend event.
        Stopt zodra de stream sluit (server cap'd op 5min, of disconnect);
        upstream-coordinator regelt reconnect-strategie.

        Onbekende event-types (bijv. toekomstige `solar-reading`) worden
        gewoon doorgegeven — de coordinator beslist wat ermee te doen. SSE-
        comments/heartbeats (`: ping`) worden stil geconsumeerd; de read-
        timeout op `SSE_HEARTBEAT_TIMEOUT` triggert een reconnect bij stilte.
        """
        url = f"{self._base_url}/v1/me/usage/live-events"
        headers = self._headers(with_auth=True)
        headers["Accept"] = "text/event-stream"
        # Geen overall request-timeout (server houdt 'm 5min open), wel een
        # read-timeout zodat heartbeat-loss een reconnect triggert.
        timeout = aiohttp.ClientTimeout(
            total=None, connect=15, sock_read=SSE_HEARTBEAT_TIMEOUT
        )
        try:
            async with self._session.get(
                url, headers=headers, timeout=timeout
            ) as resp:
                if resp.status in (401, 403):
                    text = await resp.text()
                    raise SlimHuysAuthError(f"{resp.status}: {text[:200]}")
                if resp.status >= 400:
                    text = await resp.text()
                    raise SlimHuysApiError(f"HTTP {resp.status}: {text[:200]}")

                # SSE-spec: frames gescheiden door blank line. Elke frame
                # heeft `event:` (default `message`) + `data:` (multi-line
                # mogelijk, joined met `\n`). `:` start een comment/heartbeat.
                event_name = "message"
                data_lines: list[str] = []

                # `resp.content` itereert chunks, niet regels — gebruik
                # readline() in een loop om SSE per-regel te parsen.
                while True:
                    raw_line = await resp.content.readline()
                    if not raw_line:
                        break  # stream gesloten
                    try:
                        line = raw_line.decode("utf-8").rstrip("\r\n")
                    except UnicodeDecodeError:
                        continue

                    if line == "":
                        # Frame-einde — yield als er data is
                        if data_lines:
                            data_str = "\n".join(data_lines)
                            try:
                                payload = _json.loads(data_str)
                            except _json.JSONDecodeError:
                                _LOGGER.debug(
                                    "SSE: ongeldige JSON voor event %r: %r",
                                    event_name, data_str[:120],
                                )
                                payload = None
                            if payload is not None:
                                yield event_name, payload
                        event_name = "message"
                        data_lines = []
                        continue

                    if line.startswith(":"):
                        # Comment / heartbeat — negeer (read-timeout doet het werk)
                        continue
                    if line.startswith("event:"):
                        event_name = line[6:].strip() or "message"
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())
                    # Andere SSE-velden (id:, retry:) negeren we expliciet
        except (asyncio.TimeoutError, TimeoutError) as err:
            raise SlimHuysApiError("sse timeout") from err
        except aiohttp.ClientError as err:
            raise SlimHuysApiError(f"sse transport: {err}") from err
