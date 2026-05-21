"""Asynchronous client for communicating with the Nomos Energy API.

This module encapsulates all HTTP communication with the Nomos Energy
back-end.  It handles authentication via client credentials, caches the
access token (with expiry tracking) and subscription ID, and retrieves
price series for today and tomorrow.

Error hierarchy
---------------
NomosAuthError       – 401/403 or missing credentials; not retryable
NomosConnectionError – 5xx, timeout, or other network failure; retryable
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


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class NomosAuthError(RuntimeError):
    """Raised for authentication/authorisation failures (401, 403, bad creds).

    This error is *not* retryable – the user must fix their credentials.
    """


class NomosConnectionError(RuntimeError):
    """Raised for transient connection problems (5xx, timeout, network error).

    This error *is* retryable; the coordinator will schedule another update.
    """


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------

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

        Raises:
            NomosAuthError: if credentials are missing or the server returns
                401/403.
            NomosConnectionError: for any other network-level failure.
        """
        if not self._client_id or not self._client_secret:
            raise NomosAuthError("Client ID or Client Secret not configured")

        credentials = f"{self._client_id}:{self._client_secret}"
        auth_header = base64.b64encode(credentials.encode()).decode()
        headers = {"Authorization": f"Basic {auth_header}"}
        body = {"grant_type": "client_credentials"}

        try:
            async with self._session.post(
                f"{API_BASE_URL}/oauth/token",
                json=body,
                headers=headers,
            ) as resp:
                if resp.status in (401, 403):
                    raise NomosAuthError(
                        f"Authentication rejected by server (HTTP {resp.status})"
                    )
                resp.raise_for_status()
                payload: Dict[str, Any] = await resp.json()
                token = payload.get("access_token")
                if not token:
                    raise NomosAuthError("No access token received from authentication")
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
        except (NomosAuthError, NomosConnectionError):
            raise
        except aiohttp.ServerTimeoutError as err:
            raise NomosConnectionError(f"Timeout during authentication: {err}") from err
        except ClientResponseError as err:
            if err.status >= 500:
                raise NomosConnectionError(
                    f"Server error during authentication (HTTP {err.status}): {err}"
                ) from err
            raise NomosAuthError(f"Authentication failed (HTTP {err.status}): {err}") from err
        except ClientError as err:
            raise NomosConnectionError(f"Network error during authentication: {err}") from err

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
                if resp.status in (401, 403):
                    raise NomosAuthError(
                        f"Not authorised to list subscriptions (HTTP {resp.status})"
                    )
                resp.raise_for_status()
                payload: Dict[str, Any] = await resp.json()
                items: List[Dict[str, Any]] = payload.get("items", [])
                if not items:
                    raise NomosAuthError("No subscriptions found for these credentials")
                subscription_id = items[0].get("id")
                if not subscription_id:
                    raise NomosConnectionError("Subscription ID missing in API response")
                self._subscription_id = subscription_id
                _LOGGER.debug("Using subscription ID %s", subscription_id)
                return subscription_id
        except (NomosAuthError, NomosConnectionError):
            raise
        except aiohttp.ServerTimeoutError as err:
            raise NomosConnectionError(f"Timeout fetching subscriptions: {err}") from err
        except ClientResponseError as err:
            if err.status >= 500:
                raise NomosConnectionError(
                    f"Server error fetching subscriptions (HTTP {err.status}): {err}"
                ) from err
            raise NomosAuthError(
                f"Failed to fetch subscriptions (HTTP {err.status}): {err}"
            ) from err
        except ClientError as err:
            raise NomosConnectionError(f"Network error fetching subscriptions: {err}") from err

    async def _get_price_series(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        """Fetch price items from the API for a date range.

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
                    if resp.status in (401, 403):
                        if attempt == 0 and resp.status == 401:
                            _LOGGER.debug("Received 401; clearing token and retrying")
                            self._token = None
                            self._token_expires_at = None
                            continue
                        raise NomosAuthError(
                            f"Not authorised to fetch prices (HTTP {resp.status})"
                        )
                    resp.raise_for_status()
                    payload: Dict[str, Any] = await resp.json()
                    items: List[Dict[str, Any]] = payload.get("items", [])
                    return items
            except (NomosAuthError, NomosConnectionError):
                raise
            except aiohttp.ServerTimeoutError as err:
                raise NomosConnectionError(f"Timeout fetching prices: {err}") from err
            except ClientResponseError as err:
                if err.status >= 500:
                    raise NomosConnectionError(
                        f"Server error fetching prices (HTTP {err.status}): {err}"
                    ) from err
                raise NomosAuthError(
                    f"Failed to fetch prices (HTTP {err.status}): {err}"
                ) from err
            except ClientError as err:
                raise NomosConnectionError(f"Network error fetching prices: {err}") from err

        raise NomosConnectionError("Failed to fetch price series after retry")

    async def fetch_prices(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        """Retrieve price data for the specified date range.

        Returns a list of raw API items.  Each item typically contains at
        minimum a ``timestamp`` (UTC ISO-8601 string) and ``amount`` (total
        price in ct/kWh), but may also carry component fields such as
        ``electricity``, ``grid``, ``levies``, or a nested ``components``
        dict.  The raw items are returned as-is so the coordinator can decide
        which fields to surface.
        """
        return await self._get_price_series(start_date=start_date, end_date=end_date)

    async def validate_credentials(self) -> None:
        """Validate the configured credentials by authenticating and fetching
        the subscription list.

        Raises ``NomosAuthError`` or ``NomosConnectionError`` on failure.
        Intended for use in config flows.
        """
        await self._authenticate()
        await self._get_subscription_id()
