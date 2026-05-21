"""Sensor platform for Nomos Energy integration (v0.2).

Sensor inventory
----------------
Price sensors (unit: ct/kWh):
  nomosenergy_current_price       – current 15-min slot total price
  nomosenergy_next_price          – next 15-min slot total price
  nomosenergy_today_min           – cheapest slot today
  nomosenergy_today_max           – most expensive slot today
  nomosenergy_today_average       – average price today
  nomosenergy_tomorrow_min        – cheapest slot tomorrow (None if unpublished)
  nomosenergy_tomorrow_max        – most expensive slot tomorrow
  nomosenergy_tomorrow_average    – average price tomorrow

Optional component sensors (created only when the API returns components):
  nomosenergy_current_price_grid    – grid fee component
  nomosenergy_current_price_energy  – pure energy component
  nomosenergy_current_price_levies  – taxes/levies component

Diagnostic sensors:
  nomosenergy_last_update_time     – timestamp of last successful fetch
  nomosenergy_last_update_success  – boolean

Attributes on today_* / tomorrow_* sensors
-------------------------------------------
  prices: list[{"start": ISO-local-timestamp, "price": float ct/kWh}]
  – Full 15-min price curve; compatible with ApexCharts card.

Attributes on current_price
----------------------------
  start, end, next_price, unit, components (dict of raw component values)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


# ---------------------------------------------------------------------------
# Entity description dataclass
# ---------------------------------------------------------------------------

@dataclass
class NomosEnergySensorEntityDescription(SensorEntityDescription):
    """Describes a Nomos Energy sensor."""

    key: str = ""
    # Extra attribute keys whose values are pulled from coordinator.data
    extra_attr_keys: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Sensor entity
# ---------------------------------------------------------------------------

class NomosEnergySensor(CoordinatorEntity, SensorEntity):
    """A Nomos Energy sensor backed by the DataUpdateCoordinator."""

    entity_description: NomosEnergySensorEntityDescription

    def __init__(
        self,
        coordinator,
        description: NomosEnergySensorEntityDescription,
        entry_id: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry_id}_{description.key}"
        self._attr_name = description.name

    @property
    def native_value(self) -> Any:
        """Return the current sensor value from coordinator data."""
        if self.entity_description.key == "last_update_success":
            return self.coordinator.last_exception is None
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self.entity_description.key)

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return additional state attributes."""
        if self.coordinator.data is None:
            return {}
        attrs: Dict[str, Any] = {}
        for attr_key in self.entity_description.extra_attr_keys:
            value = self.coordinator.data.get(attr_key)
            if value is not None:
                attrs[attr_key] = value
        return attrs


# ---------------------------------------------------------------------------
# Platform setup
# ---------------------------------------------------------------------------

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: Callable,
) -> None:
    """Set up Nomos Energy sensors based on a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    # ---------------------------------------------------------------------- #
    # Core price sensors (always created)
    # ---------------------------------------------------------------------- #
    sensors: List[NomosEnergySensor] = [
        NomosEnergySensor(
            coordinator,
            NomosEnergySensorEntityDescription(
                key="current_price",
                name="Nomos Current Price",
                native_unit_of_measurement="ct/kWh",
                state_class=SensorStateClass.MEASUREMENT,
                icon="mdi:lightning-bolt",
                extra_attr_keys=[
                    "current_price_start",
                    "current_price_end",
                    "next_price",
                    "current_components",
                ],
            ),
            entry.entry_id,
        ),
        NomosEnergySensor(
            coordinator,
            NomosEnergySensorEntityDescription(
                key="next_price",
                name="Nomos Next Price",
                native_unit_of_measurement="ct/kWh",
                state_class=SensorStateClass.MEASUREMENT,
                icon="mdi:lightning-bolt-outline",
            ),
            entry.entry_id,
        ),
        # Today aggregates
        NomosEnergySensor(
            coordinator,
            NomosEnergySensorEntityDescription(
                key="today_min",
                name="Nomos Today Min Price",
                native_unit_of_measurement="ct/kWh",
                state_class=SensorStateClass.MEASUREMENT,
                icon="mdi:arrow-down-bold",
                extra_attr_keys=["today_prices"],
            ),
            entry.entry_id,
        ),
        NomosEnergySensor(
            coordinator,
            NomosEnergySensorEntityDescription(
                key="today_max",
                name="Nomos Today Max Price",
                native_unit_of_measurement="ct/kWh",
                state_class=SensorStateClass.MEASUREMENT,
                icon="mdi:arrow-up-bold",
                extra_attr_keys=["today_prices"],
            ),
            entry.entry_id,
        ),
        NomosEnergySensor(
            coordinator,
            NomosEnergySensorEntityDescription(
                key="today_average",
                name="Nomos Today Average Price",
                native_unit_of_measurement="ct/kWh",
                state_class=SensorStateClass.MEASUREMENT,
                icon="mdi:chart-bell-curve",
                extra_attr_keys=["today_prices"],
            ),
            entry.entry_id,
        ),
        # Tomorrow aggregates
        NomosEnergySensor(
            coordinator,
            NomosEnergySensorEntityDescription(
                key="tomorrow_min",
                name="Nomos Tomorrow Min Price",
                native_unit_of_measurement="ct/kWh",
                state_class=SensorStateClass.MEASUREMENT,
                icon="mdi:arrow-down-bold",
                extra_attr_keys=["tomorrow_prices"],
            ),
            entry.entry_id,
        ),
        NomosEnergySensor(
            coordinator,
            NomosEnergySensorEntityDescription(
                key="tomorrow_max",
                name="Nomos Tomorrow Max Price",
                native_unit_of_measurement="ct/kWh",
                state_class=SensorStateClass.MEASUREMENT,
                icon="mdi:arrow-up-bold",
                extra_attr_keys=["tomorrow_prices"],
            ),
            entry.entry_id,
        ),
        NomosEnergySensor(
            coordinator,
            NomosEnergySensorEntityDescription(
                key="tomorrow_average",
                name="Nomos Tomorrow Average Price",
                native_unit_of_measurement="ct/kWh",
                state_class=SensorStateClass.MEASUREMENT,
                icon="mdi:chart-bell-curve",
                extra_attr_keys=["tomorrow_prices"],
            ),
            entry.entry_id,
        ),
        # Diagnostic sensors
        NomosEnergySensor(
            coordinator,
            NomosEnergySensorEntityDescription(
                key="last_update_time",
                name="Nomos Last Update Time",
                device_class=SensorDeviceClass.TIMESTAMP,
                entity_category=EntityCategory.DIAGNOSTIC,
            ),
            entry.entry_id,
        ),
        NomosEnergySensor(
            coordinator,
            NomosEnergySensorEntityDescription(
                key="last_update_success",
                name="Nomos Last Update Success",
                entity_category=EntityCategory.DIAGNOSTIC,
            ),
            entry.entry_id,
        ),
    ]

    # ---------------------------------------------------------------------- #
    # Optional component sensors — only added when the API provides data
    # ---------------------------------------------------------------------- #
    data: Dict[str, Any] = coordinator.data or {}

    component_defs = [
        ("current_price_grid", "Nomos Current Price Grid", "mdi:transmission-tower"),
        ("current_price_energy", "Nomos Current Price Energy", "mdi:flash"),
        ("current_price_levies", "Nomos Current Price Levies", "mdi:bank"),
    ]
    for key, name, icon in component_defs:
        if data.get(key) is not None:
            sensors.append(
                NomosEnergySensor(
                    coordinator,
                    NomosEnergySensorEntityDescription(
                        key=key,
                        name=name,
                        native_unit_of_measurement="ct/kWh",
                        state_class=SensorStateClass.MEASUREMENT,
                        icon=icon,
                    ),
                    entry.entry_id,
                )
            )

    async_add_entities(sensors)
