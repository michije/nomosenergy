"""Asynchronous client for communicating with the Nomos Energy API.

This module encapsulates all HTTP communication with the Nomos Energy
back‭ef‑end.  It handles authentication via client credentials, caches the
access token and subscription ID, and retrieves price series for
today and tomorrow.
"""

from __future__ import annotations

import base64
import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from aiohttp import ClientSession, ClientError

from .const import API_BASE_URL

_LOGGER = logging.getLogger(__name__)


class NomosEnergyApi:
    """Client for the Nomos Energy REST API."""

    def __init__(self, session: ClientSession, client_id: str, client_secret: str) -> None:
        self._session = session
        self._client_id = client_id
        self._client_secret = client_secret
        self._token: Optional[str] = None
        self._subscription_id: Optional[str] = None

    async def _authenticate(self) -> str:
        """Authenticate against the API and return an access token.

        Raises a ``ClientError`` if the request fails.
        """
        if self._token:
            return self._token

        if not self._client_id or not self._client_secret:
            raise ValueError("Client ID or Client Secret not configured")

        credentials = f"{self._client_id}:{self._client_secret}"
        auth_header = base64.b64encode(credentials.encode()).decode()
        headers = {
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        data = {"grant_type": "client_credentials"}

        try:
            async with self._session.post(f"{API_BASE_URL}/oauth/token", data=data, headers=headers) as resp:
                resp.raise_for_status()
                payload: Dict[str, Any] = await resp.json()
                token = payload.get("access_token")
                if not token:
                    raise RuntimeError("No access token received from authentication")
                self._token = token
                return token
        except ClientError as err:
            raise RuntimeError(f"Authentication failed: {err}") from err

    async def _get_subscription_id(self) -> str:
        """Return the first subscription ID from the API.

        Caches the subscription ID after the first request.
        """
        if self._subscription_id:
            return self._subscription_id

        token = await self._authenticate()
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

        The API expects ISO 8601 date strings (YYYY‑MM‑DD) for the start and
        end parameters.  Returns a list of items, each containing a
        timestamp and amount.
        """
        token = await self._authenticate()
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
            raise RuntimeError(f"Failed to fetch price series: {err}") from err

    async def fetch_prices(self) -> List[Dict[str, Any]]:
        """Retrieve price data for today and tomorrow.

        Returns a list of objects with ``timestamp`` (UTC ISO string) and
        ``amount`` (price in ct/kWh).
        """
        # Determine today and tomorrow based on UTC to match the API's
        # behaviour.  The API returns UTC timestamps; we convert them
        # later when building the sensor data.
        today = date.today()
        tomorrow = today + timedelta(days=1)
        return await self._get_price_series(start_date=today, end_date=tomorrow)
