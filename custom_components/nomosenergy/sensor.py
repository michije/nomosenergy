"""Sensor platform for Nomos Energy integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN, HOURS_IN_DAY


@dataclass
class NomosEnergySensorEntityDescription(SensorEntityDescription):
    """Describes a Nomos Energy sensor."""

    key: str


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
        # All sensors measure monetary values in ct/kWh
        self._attr_native_unit_of_measurement = "ct/kWh"

    @property
    def native_value(self) -> Any:
        """Return the sensor value from the coordinator data."""
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

    # Create sensors for each hour today and tomorrow
    for day in ("today", "tomorrow"):
        for hour in range(HOURS_IN_DAY):
            key = f"{day}_{hour:02d}"
            # Friendly name e.g. "Nomos Today 14:00"
            human_day = "Today" if day == "today" else "Tomorrow"
            name = f"Nomos {human_day} {hour:02d}:00"
            sensors.append(
                NomosEnergySensor(
                    coordinator,
                    NomosEnergySensorEntityDescription(key=key, name=name),
                    entry.entry_id,
                )
            )

    async_add_entities(sensors)
