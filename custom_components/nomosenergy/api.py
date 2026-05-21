"""Asynchronous client for communicating with the Nomos Energy API.

This module encapsulates all HTTP communication with the Nomos Energy
back-end.  It handles authentication via client credentials, caches the
access token (with expiry tracking) and subscription ID, and retrieves
price series for today and tomorrow.
"""

from __future__ import annotations

import base64
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import aiohttp
from aiohttp import ClientSession, ClientError, ClientResponseError

from .const import API_BASE_URL

_LOGGER = logging.getLogger(__name__)

# Refresh the token this many seconds before it actually expires to avoid
# race conditions where the token expires mid-request.
_TOKEN_REFRESH_BUFFER_SECONDS = 60


class NomosEnergyApi:
    """Client for the Nomos Energy REST API."""

    def __init__(self, session: ClientSession, client_id: str, client_secret: str) -> None:
        self._session = session
        self._client_id = client_id
        self._client_secret = client_secret
        self._token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None
        self._subscription_id: Optional[str] = None

    def _is_token_valid(self) -> bool:
        """Return True if the cached token is present and not near expiry."""
        if not self._token or self._token_expires_at is None:
            return False
        return datetime.now(tz=timezone.utc) < self._token_expires_at

    async def _ensure_token(self) -> str:
        """Return a valid access token, refreshing it if necessary."""
        if not self._is_token_valid():
            self._token = None
            self._token_expires_at = None
            await self._authenticate()
        return self._token  # type: ignore[return-value]

    async def _authenticate(self) -> str:
        """Authenticate against the API and return an access token.

        The /oauth/token endpoint expects a JSON body (confirmed via the
        OpenAPI spec at https://api.nomos.energy/openapi.json which declares
        the requestBody content-type as ``application/json``).

        Raises a ``RuntimeError`` if the request fails.
        """
        if not self._client_id or not self._client_secret:
            raise ValueError("Client ID or Client Secret not configured")

        credentials = f"{self._client_id}:{self._client_secret}"
        auth_header = base64.b64encode(credentials.encode()).decode()
        headers = {
            "Authorization": f"Basic {auth_header}",
        }
        # The OpenAPI spec declares content-type application/json for this
        # endpoint, so we pass the body as JSON (not form-encoded).
        body = {"grant_type": "client_credentials"}

        try:
            async with self._session.post(
                f"{API_BASE_URL}/oauth/token",
                json=body,
                headers=headers,
            ) as resp:
                resp.raise_for_status()
                payload: Dict[str, Any] = await resp.json()
                token = payload.get("access_token")
                if not token:
                    raise RuntimeError("No access token received from authentication")
                expires_in: int = payload.get("expires_in", 3600)
                self._token = token
                self._token_expires_at = (
                    datetime.now(tz=timezone.utc)
                    + timedelta(seconds=expires_in - _TOKEN_REFRESH_BUFFER_SECONDS)
                )
                _LOGGER.debug(
                    "Authenticated; token expires in %s s (buffered to %s s)",
                    expires_in,
                    expires_in - _TOKEN_REFRESH_BUFFER_SECONDS,
                )
                return token
        except ClientError as err:
            raise RuntimeError(f"Authentication failed: {err}") from err

    async def _get_subscription_id(self) -> str:
        """Return the first subscription ID from the API.

        Caches the subscription ID after the first request.
        """
        if self._subscription_id:
            return self._subscription_id

        token = await self._ensure_token()
        headers = {"Authorization": f"Bearer {token}"}
        try:
            async with self._session.get(f"{API_BASE_URL}/subscriptions", headers=headers) as resp:
                resp.raise_for_status()
                payload: Dict[str, Any] = await resp.json()
                items: List[Dict[str, Any]] = payload.get("items", [])
                if not items:
                    raise RuntimeError("No subscriptions found")
                subscription_id = items[0].get("id")
                if not subscription_id:
                    raise RuntimeError("Subscription ID missing in response")
                self._subscription_id = subscription_id
                _LOGGER.debug("Using subscription ID %s", subscription_id)
                return subscription_id
        except ClientError as err:
            raise RuntimeError(f"Failed to fetch subscriptions: {err}") from err

    async def _get_price_series(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        """Fetch price items from the API for a date range.

        The API expects ISO 8601 date strings (YYYY-MM-DD) for the start and
        end parameters.  Returns a list of items, each containing a
        timestamp and amount.

        Retries once on a 401 response by clearing the cached token and
        re-authenticating.
        """
        for attempt in range(2):
            token = await self._ensure_token()
            subscription_id = await self._get_subscription_id()
            params = {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
            }
            headers = {"Authorization": f"Bearer {token}"}
            url = f"{API_BASE_URL}/subscriptions/{subscription_id}/prices"
            try:
                async with self._session.get(url, headers=headers, params=params) as resp:
                    resp.raise_for_status()
                    payload: Dict[str, Any] = await resp.json()
                    items: List[Dict[str, Any]] = payload.get("items", [])
                    return items
            except ClientError as err:
                # Only retry on 401 Unauthorized; use isinstance guard to
                # safely access .status (not all ClientError subclasses have it)
                if (
                    attempt == 0
                    and isinstance(err, ClientResponseError)
                    and err.status == 401
                ):
                    _LOGGER.debug("Received 401; clearing token and retrying")
                    self._token = None
                    self._token_expires_at = None
                    continue
                raise RuntimeError(f"Failed to fetch price series: {err}") from err

        # Should not be reached, but satisfy the type checker
        raise RuntimeError("Failed to fetch price series after retry")

    async def fetch_prices(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        """Retrieve price data for the specified date range.

        Returns a list of objects with ``timestamp`` (UTC ISO string) and
        ``amount`` (price in ct/kWh).
        """
        return await self._get_price_series(start_date=start_date, end_date=end_date)

    async def validate_credentials(self) -> None:
        """Validate the configured credentials by authenticating and fetching
        the subscription list.

        Raises ``RuntimeError`` on failure.  Intended for use in config flows
        and other contexts where internal methods should not be called directly.
        """
        await self._authenticate()
        await self._get_subscription_id()
