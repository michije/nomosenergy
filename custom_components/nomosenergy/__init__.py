"""The Nomos Energy integration."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from zoneinfo import ZoneInfo

from .api import NomosEnergyApi
from .const import (
    DOMAIN,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    INTERVAL_MINUTES,
)

_LOGGER = logging.getLogger(__name__)


PLATFORMS: list[str] = ["sensor"]


async def async_setup(_hass: HomeAssistant, _config: Dict[str, Any]) -> bool:
    """Set up the Nomos Energy integration via YAML is not supported."""
    # This integration is config-entry only.  Prevent YAML configuration.
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Nomos Energy from a config entry."""
    # Use HA's shared session instead of creating a private one.  HA manages
    # the lifecycle of this session, so we must NOT close it ourselves.
    session = async_get_clientsession(hass)
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

        # Determine current date and tomorrow's date in Berlin timezone
        now_berlin = datetime.now(tz=berlin_tz)
        today = now_berlin.date()
        tomorrow = today + timedelta(days=1)

        try:
            items = await api.fetch_prices(today, tomorrow)
        except Exception as err:
            raise UpdateFailed(f"Error fetching data: {err}") from err

        # Collect sums and counts per interval slot.
        # Slots are keyed as "{day}_{HH}_{MM}", e.g. "today_14_30".
        # This handles both hourly (60-min) and 15-min interval responses
        # dynamically: each timestamp is bucketed into INTERVAL_MINUTES slots.
        interval_sums: Dict[str, float] = defaultdict(float)
        interval_counts: Dict[str, int] = defaultdict(int)

        for item in items:
            timestamp: str | None = item.get("timestamp")
            amount = item.get("amount")
            if timestamp is None:
                continue
            # Skip null amounts rather than crashing or silently adding zero
            if amount is None:
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
            # Snap minutes to the nearest INTERVAL_MINUTES boundary
            minute_slot = (dt_berlin.minute // INTERVAL_MINUTES) * INTERVAL_MINUTES

            if date_ == today:
                slot_key = f"today_{hour:02d}_{minute_slot:02d}"
            elif date_ == tomorrow:
                slot_key = f"tomorrow_{hour:02d}_{minute_slot:02d}"
            else:
                # Ignore any data outside today/tomorrow
                continue

            interval_sums[slot_key] += amount
            interval_counts[slot_key] += 1

        # Build a mapping of sensor keys to average price values.
        # We generate keys for every INTERVAL_MINUTES slot in a day so that
        # sensors exist even before data arrives (value will be None).
        data: Dict[str, Any] = {}
        minutes_per_day = 24 * 60
        for day in ("today", "tomorrow"):
            for total_minutes in range(0, minutes_per_day, INTERVAL_MINUTES):
                h = total_minutes // 60
                m = total_minutes % 60
                key = f"{day}_{h:02d}_{m:02d}"
                count = interval_counts.get(key, 0)
                data[key] = interval_sums[key] / count if count > 0 else None

        # Determine current price for the current interval
        current_minute_slot = (now_berlin.minute // INTERVAL_MINUTES) * INTERVAL_MINUTES
        current_key = f"today_{now_berlin.hour:02d}_{current_minute_slot:02d}"
        data["current_price"] = data.get(current_key)

        # Update diagnostic data
        last_update_time = datetime.now(tz=berlin_tz)
        data["last_update_time"] = last_update_time
        data["last_update_success"] = True

        return data

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="Nomos Energy data",
        update_method=_async_update_data,
        # Update every 15 minutes to align with new 15-min price availability
        update_interval=timedelta(minutes=15),
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "api": api,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        # HA's shared session is managed by HA itself; do not close it here.
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
