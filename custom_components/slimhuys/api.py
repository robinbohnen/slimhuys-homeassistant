"""Async HTTP client for the SlimHuys API."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

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
            "User-Agent": "slimhuys-ha/0.1.0",
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
