"""The Nomos Energy integration.

Sets up the DataUpdateCoordinator that fetches price data from the
Nomos Energy API and pre-computes all sensor values so that individual
sensor entities simply read from the coordinator's data dict.

Data structure produced by _async_update_data
---------------------------------------------
{
    # Current slot
    "current_price":        float | None,   # total price ct/kWh
    "current_price_start":  str | None,     # ISO timestamp (local)
    "current_price_end":    str | None,     # ISO timestamp (local)
    "next_price":           float | None,

    # Today aggregates
    "today_min":     float | None,
    "today_max":     float | None,
    "today_average": float | None,
    "today_prices":  list[{"start": str, "price": float}],

    # Tomorrow aggregates (None when not yet published)
    "tomorrow_min":     float | None,
    "tomorrow_max":     float | None,
    "tomorrow_average": float | None,
    "tomorrow_prices":  list[{"start": str, "price": float}],

    # Optional price components (present only if API returns them)
    "current_price_grid":    float | None,
    "current_price_energy":  float | None,
    "current_price_levies":  float | None,
    "current_components":    dict | None,   # raw passthrough of all component fields

    # Diagnostics
    "last_update_time":    datetime,
    "last_update_success": bool,
}
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone, date
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import NomosEnergyApi, NomosConnectionError
from .const import (
    DOMAIN,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    INTERVAL_MINUTES,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = ["sensor"]

# Known component field names returned by the Nomos API.  Additional
# unknown fields are passed through as raw components.
_COMPONENT_GRID_FIELDS = ("grid",)
_COMPONENT_ENERGY_FIELDS = ("electricity", "energy")
_COMPONENT_LEVIES_FIELDS = ("levies", "taxes", "tax")


async def async_setup(_hass: HomeAssistant, _config: Dict[str, Any]) -> bool:
    """Set up the Nomos Energy integration via YAML is not supported."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Nomos Energy from a config entry."""
    session = async_get_clientsession(hass)
    api = NomosEnergyApi(
        session,
        entry.data[CONF_CLIENT_ID],
        entry.data[CONF_CLIENT_SECRET],
    )

    local_tz = ZoneInfo(hass.config.time_zone or "Europe/Berlin")

    async def _async_update_data() -> Dict[str, Any]:
        """Fetch data from Nomos Energy and prepare all sensor values.

        All timestamp processing is done in UTC; local-time conversion
        happens only at the point where we produce human-readable output.
        This makes the logic correct across DST transitions (23- and 25-hour
        days) because we iterate over actual API items rather than generating
        fixed wall-clock slots.
        """
        now_utc = datetime.now(tz=timezone.utc)
        now_local = now_utc.astimezone(local_tz)
        today_local: date = now_local.date()
        tomorrow_local: date = today_local + timedelta(days=1)

        try:
            items: List[Dict[str, Any]] = await api.fetch_prices(today_local, tomorrow_local)
        except NomosConnectionError as err:
            # Transient failure — tell HA to retry later
            raise UpdateFailed(f"Connection error fetching prices: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Unexpected error fetching prices: {err}") from err

        # ------------------------------------------------------------------ #
        # Bucket items into today / tomorrow lists (UTC, sorted)
        # ------------------------------------------------------------------ #
        today_items: List[Dict[str, Any]] = []
        tomorrow_items: List[Dict[str, Any]] = []

        for item in items:
            ts_raw: Optional[str] = item.get("timestamp")
            amount = item.get("amount")
            if ts_raw is None or amount is None:
                continue
            try:
                dt_utc = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            except ValueError:
                _LOGGER.warning("Skipping item with invalid timestamp: %s", ts_raw)
                continue
            # Classify by local date (handles DST correctly because we
            # convert *each* timestamp independently)
            dt_local = dt_utc.astimezone(local_tz)
            local_date = dt_local.date()
            if local_date == today_local:
                today_items.append({"dt_utc": dt_utc, "amount": amount, "raw": item})
            elif local_date == tomorrow_local:
                tomorrow_items.append({"dt_utc": dt_utc, "amount": amount, "raw": item})
            # Items outside today/tomorrow window are silently ignored

        today_items.sort(key=lambda x: x["dt_utc"])
        tomorrow_items.sort(key=lambda x: x["dt_utc"])

        # ------------------------------------------------------------------ #
        # Helper: build price curve list for attributes
        # ------------------------------------------------------------------ #
        def _price_curve(bucket: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            return [
                {
                    "start": entry["dt_utc"].astimezone(local_tz).isoformat(),
                    "price": entry["amount"],
                }
                for entry in bucket
            ]

        # ------------------------------------------------------------------ #
        # Helper: extract aggregate stats
        # ------------------------------------------------------------------ #
        def _stats(bucket: List[Dict[str, Any]]):
            if not bucket:
                return None, None, None
            prices = [entry["amount"] for entry in bucket]
            return min(prices), max(prices), sum(prices) / len(prices)

        today_min, today_max, today_avg = _stats(today_items)
        tomorrow_min, tomorrow_max, tomorrow_avg = _stats(tomorrow_items)

        # ------------------------------------------------------------------ #
        # Find current slot and next slot
        # ------------------------------------------------------------------ #
        # Snap now_utc to the INTERVAL_MINUTES boundary (floor)
        slot_seconds = INTERVAL_MINUTES * 60
        now_epoch = now_utc.timestamp()
        current_slot_start_epoch = (now_epoch // slot_seconds) * slot_seconds
        current_slot_start = datetime.fromtimestamp(current_slot_start_epoch, tz=timezone.utc)
        next_slot_start = current_slot_start + timedelta(minutes=INTERVAL_MINUTES)

        def _find_slot(
            bucket: List[Dict[str, Any]], slot_start: datetime
        ) -> Optional[Dict[str, Any]]:
            """Return the item whose slot contains slot_start."""
            for entry in bucket:
                diff = abs((entry["dt_utc"] - slot_start).total_seconds())
                if diff < slot_seconds:
                    return entry
            return None

        all_items = today_items + tomorrow_items
        current_entry = _find_slot(all_items, current_slot_start)
        next_entry = _find_slot(all_items, next_slot_start)

        current_price: Optional[float] = current_entry["amount"] if current_entry else None
        next_price: Optional[float] = next_entry["amount"] if next_entry else None

        current_start_str: Optional[str] = (
            current_slot_start.astimezone(local_tz).isoformat() if current_entry else None
        )
        current_end_str: Optional[str] = (
            (current_slot_start + timedelta(minutes=INTERVAL_MINUTES))
            .astimezone(local_tz)
            .isoformat()
            if current_entry
            else None
        )

        # ------------------------------------------------------------------ #
        # Price components
        # ------------------------------------------------------------------ #
        current_components: Optional[Dict[str, Any]] = None
        current_price_grid: Optional[float] = None
        current_price_energy: Optional[float] = None
        current_price_levies: Optional[float] = None

        if current_entry:
            raw = current_entry["raw"]
            # Collect component fields: either a nested "components" dict or
            # top-level fields alongside "amount"
            components_src: Dict[str, Any] = raw.get("components") or {}
            # Also check top-level fields (exclude known non-component keys)
            _non_component_keys = {"timestamp", "amount", "id", "subscriptionId"}
            for k, v in raw.items():
                if k not in _non_component_keys and isinstance(v, (int, float)):
                    components_src.setdefault(k, v)

            if components_src:
                current_components = components_src
                # Map to well-known sensor keys
                for field in _COMPONENT_GRID_FIELDS:
                    if field in components_src:
                        current_price_grid = components_src[field]
                        break
                for field in _COMPONENT_ENERGY_FIELDS:
                    if field in components_src:
                        current_price_energy = components_src[field]
                        break
                for field in _COMPONENT_LEVIES_FIELDS:
                    if field in components_src:
                        current_price_levies = components_src[field]
                        break

        # ------------------------------------------------------------------ #
        # Assemble coordinator data dict
        # ------------------------------------------------------------------ #
        data: Dict[str, Any] = {
            # Current slot
            "current_price": current_price,
            "current_price_start": current_start_str,
            "current_price_end": current_end_str,
            "next_price": next_price,
            # Today
            "today_min": today_min,
            "today_max": today_max,
            "today_average": today_avg,
            "today_prices": _price_curve(today_items),
            # Tomorrow
            "tomorrow_min": tomorrow_min,
            "tomorrow_max": tomorrow_max,
            "tomorrow_average": tomorrow_avg,
            "tomorrow_prices": _price_curve(tomorrow_items),
            # Components
            "current_price_grid": current_price_grid,
            "current_price_energy": current_price_energy,
            "current_price_levies": current_price_levies,
            "current_components": current_components,
            # Diagnostics
            "last_update_time": now_utc,
            "last_update_success": True,
        }
        return data

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="Nomos Energy data",
        update_method=_async_update_data,
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
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
