"""The Nomos Energy integration."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from zoneinfo import ZoneInfo

from .api import NomosEnergyApi
from .const import (
    DOMAIN,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    HOURS_IN_DAY,
)

_LOGGER = logging.getLogger(__name__)


PLATFORMS: list[str] = ["sensor"]


async def async_setup(_hass: HomeAssistant, _config: Dict[str, Any]) -> bool:
    """Set up the Nomos Energy integration via YAML is not supported."""
    # This integration is config‑entry only.  Prevent YAML configuration.
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Nomos Energy from a config entry."""
    # Create a single shared HTTP session for API calls
    session = aiohttp.ClientSession()
    api = NomosEnergyApi(
        session,
        entry.data[CONF_CLIENT_ID],
        entry.data[CONF_CLIENT_SECRET],
    )

    berlin_tz = ZoneInfo("Europe/Berlin")
    last_update_time = None  # Persist last successful update time across refreshes

    async def _async_update_data() -> Dict[str, Any]:
        """Fetch data from Nomos Energy and prepare sensor values."""
        nonlocal last_update_time

        try:
            items = await api.fetch_prices()
        except Exception as err:
            raise UpdateFailed(f"Error fetching data: {err}") from err

        # Build a mapping of sensor keys to price values
        data: Dict[str, Any] = {}

        # Determine current date and tomorrow's date in Berlin timezone
        now_berlin = datetime.now(tz=berlin_tz)
        today = now_berlin.date()
        tomorrow = today + timedelta(days=1)

        # Populate data for each returned item
        for item in items:
            timestamp: str | None = item.get("timestamp")
            amount = item.get("amount")
            if timestamp is None:
                continue
            # Parse UTC timestamp and convert to Berlin timezone
            try:
                # Replace trailing 'Z' with +00:00 for fromisoformat compatibility
                dt_utc = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError:
                _LOGGER.warning("Invalid timestamp received: %s", timestamp)
                continue
            dt_berlin = dt_utc.astimezone(berlin_tz)
            date_ = dt_berlin.date()
            hour = dt_berlin.hour
            key: str
            if date_ == today:
                key = f"today_{hour:02d}"
            elif date_ == tomorrow:
                key = f"tomorrow_{hour:02d}"
            else:
                # Ignore any data outside today/tomorrow
                continue
            data[key] = amount

        # Fill missing hours with None so sensors are created consistently
        for h in range(HOURS_IN_DAY):
            k_today = f"today_{h:02d}"
            k_tomorrow = f"tomorrow_{h:02d}"
            data.setdefault(k_today, None)
            data.setdefault(k_tomorrow, None)

        # Determine current price for the current hour
        current_key = f"today_{now_berlin.hour:02d}"
        data["current_price"] = data.get(current_key)

        # Update diagnostic data
        last_update_time = datetime.now(tz=berlin_tz).isoformat()
        data["last_update_time"] = last_update_time
        data["last_update_success"] = True

        return data

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="Nomos Energy data",
        update_method=_async_update_data,
        # Update every hour to align with new price availability
        update_interval=timedelta(hours=1),
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "api": api,
        "session": session,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        # Clean up our API session
        data = hass.data[DOMAIN].pop(entry.entry_id)
        session: aiohttp.ClientSession = data["session"]
        await session.close()
    return unload_ok
