"""Sensor platform for Nomos Energy integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, List

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription, SensorDeviceClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN, INTERVAL_MINUTES


@dataclass
class NomosEnergySensorEntityDescription(SensorEntityDescription):
    """Describes a Nomos Energy sensor."""

    key: str = ""


class NomosEnergySensor(CoordinatorEntity, SensorEntity):
    """Base sensor for Nomos Energy data."""

    def __init__(
        self,
        coordinator,
        description: NomosEnergySensorEntityDescription,
        entry_id: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        # Unique ID includes the config entry ID to avoid collisions when
        # multiple accounts are added.
        self._attr_unique_id = f"{entry_id}_{description.key}"
        # Human readable name
        self._attr_name = description.name
        # Set unit for price sensors, none for diagnostics
        if description.key in ("last_update_time", "last_update_success"):
            self._attr_native_unit_of_measurement = None
        else:
            self._attr_native_unit_of_measurement = "ct/kWh"

    @property
    def native_value(self) -> Any:
        """Return the sensor value from the coordinator data."""
        if self.entity_description.key == "last_update_success":
            return self.coordinator.last_exception is None
        return self.coordinator.data.get(self.entity_description.key)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: Callable[[List[NomosEnergySensor], bool], None],
) -> None:
    """Set up Nomos Energy sensors based on a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]

    sensors: List[NomosEnergySensor] = []

    # Create sensor for current price
    sensors.append(
        NomosEnergySensor(
            coordinator,
            NomosEnergySensorEntityDescription(
                key="current_price",
                name="Nomos Current Price",
            ),
            entry.entry_id,
        )
    )

    # Create sensors for each 15-minute interval today and tomorrow.
    # Keys use the format "{day}_{HH}_{MM}", e.g. "today_14_30".
    # Friendly names use the format "Nomos Today 14:30".
    minutes_per_day = 24 * 60
    for day in ("today", "tomorrow"):
        human_day = "Today" if day == "today" else "Tomorrow"
        for total_minutes in range(0, minutes_per_day, INTERVAL_MINUTES):
            h = total_minutes // 60
            m = total_minutes % 60
            key = f"{day}_{h:02d}_{m:02d}"
            name = f"Nomos {human_day} {h:02d}:{m:02d}"
            sensors.append(
                NomosEnergySensor(
                    coordinator,
                    NomosEnergySensorEntityDescription(key=key, name=name),
                    entry.entry_id,
                )
            )

    # Create diagnostic sensors
    sensors.append(
        NomosEnergySensor(
            coordinator,
            NomosEnergySensorEntityDescription(
                key="last_update_time",
                name="Nomos Last Update Time",
                device_class=SensorDeviceClass.TIMESTAMP,
                entity_category=EntityCategory.DIAGNOSTIC,
            ),
            entry.entry_id,
        )
    )
    sensors.append(
        NomosEnergySensor(
            coordinator,
            NomosEnergySensorEntityDescription(
                key="last_update_success",
                name="Nomos Last Update Success",
                entity_category=EntityCategory.DIAGNOSTIC,
            ),
            entry.entry_id,
        )
    )

    async_add_entities(sensors)
