"""SlimHuys sensors: huidige prijs, dagstats, goedkoopste blok, etc."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CURRENCY_EURO
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SlimHuysCoordinator

_LOGGER = logging.getLogger(__name__)

UNIT_EUR_PER_KWH = f"{CURRENCY_EURO}/kWh"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SlimHuysCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    supplier = hass.data[DOMAIN][entry.entry_id]["supplier"]

    async_add_entities(
        [
            CurrentPriceSensor(coordinator, entry, supplier),
            EpexBareSensor(coordinator, entry, supplier),
            TodayAverageSensor(coordinator, entry, supplier),
            TodayLowestSensor(coordinator, entry, supplier),
            TodayHighestSensor(coordinator, entry, supplier),
            CheapestBlockStartSensor(coordinator, entry, supplier),
            CheapestBlockAverageSensor(coordinator, entry, supplier),
            NextNegativeSensor(coordinator, entry, supplier),
            CurrentLevelSensor(coordinator, entry, supplier),
        ]
    )


class _BaseSensor(CoordinatorEntity[SlimHuysCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SlimHuysCoordinator,
        entry: ConfigEntry,
        supplier: str,
        unique_suffix: str,
        name: str,
    ) -> None:
        super().__init__(coordinator)
        self._supplier = supplier
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{unique_suffix}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": f"SlimHuys ({supplier})",
            "manufacturer": "SlimHuys.nl",
            "model": "Energy prices",
            "configuration_url": "https://slimhuys.nl/app/tarieven",
        }


class CurrentPriceSensor(_BaseSensor):
    _attr_native_unit_of_measurement = UNIT_EUR_PER_KWH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_suggested_display_precision = 4
    _attr_icon = "mdi:flash"

    def __init__(self, coordinator, entry, supplier):
        super().__init__(coordinator, entry, supplier, "current_price", "Huidige prijs")

    @property
    def native_value(self) -> float | None:
        cur = (self.coordinator.data or {}).get("current")
        if not cur:
            return None
        return cur["now"]["breakdown"]["total_eur_per_kwh"]

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        cur = (self.coordinator.data or {}).get("current")
        if not cur:
            return None
        b = cur["now"]["breakdown"]
        return {
            "epex_eur_per_kwh": b["epex_eur_per_kwh"],
            "supplier_markup_eur": b["supplier_markup_eur"],
            "energy_tax_eur": b["energy_tax_eur"],
            "vat_eur": b["vat_eur"],
            "valid_from": cur["now"]["timestamp"],
            "valid_until": cur["now"]["valid_until"],
            "level": cur["now"]["level"],
            "supplier": self._supplier,
        }


class EpexBareSensor(_BaseSensor):
    _attr_native_unit_of_measurement = UNIT_EUR_PER_KWH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 4
    _attr_icon = "mdi:transmission-tower"

    def __init__(self, coordinator, entry, supplier):
        super().__init__(coordinator, entry, supplier, "epex_bare", "EPEX kale prijs")

    @property
    def native_value(self) -> float | None:
        cur = (self.coordinator.data or {}).get("current")
        if not cur:
            return None
        return cur["now"]["breakdown"]["epex_eur_per_kwh"]


class TodayAverageSensor(_BaseSensor):
    _attr_native_unit_of_measurement = UNIT_EUR_PER_KWH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 4
    _attr_icon = "mdi:chart-line"

    def __init__(self, coordinator, entry, supplier):
        super().__init__(coordinator, entry, supplier, "today_avg", "Daggemiddelde")

    @property
    def native_value(self) -> float | None:
        cur = (self.coordinator.data or {}).get("current")
        if not cur:
            return None
        return cur["comparison"].get("day_avg_eur")


class TodayLowestSensor(_BaseSensor):
    _attr_native_unit_of_measurement = UNIT_EUR_PER_KWH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 4
    _attr_icon = "mdi:arrow-down-bold"

    def __init__(self, coordinator, entry, supplier):
        super().__init__(coordinator, entry, supplier, "today_low", "Laagste vandaag")

    @property
    def native_value(self) -> float | None:
        hourly = (self.coordinator.data or {}).get("hourly", [])
        # Filter naar vandaag
        today = (self.coordinator.data or {}).get("fetched_at", "")[:10]
        prices = [h["price"] for h in hourly if h["day"] == today and h["price"] is not None]
        return min(prices) if prices else None


class TodayHighestSensor(_BaseSensor):
    _attr_native_unit_of_measurement = UNIT_EUR_PER_KWH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 4
    _attr_icon = "mdi:arrow-up-bold"

    def __init__(self, coordinator, entry, supplier):
        super().__init__(coordinator, entry, supplier, "today_high", "Hoogste vandaag")

    @property
    def native_value(self) -> float | None:
        hourly = (self.coordinator.data or {}).get("hourly", [])
        today = (self.coordinator.data or {}).get("fetched_at", "")[:10]
        prices = [h["price"] for h in hourly if h["day"] == today and h["price"] is not None]
        return max(prices) if prices else None


class CheapestBlockStartSensor(_BaseSensor):
    _attr_icon = "mdi:clock-start"

    def __init__(self, coordinator, entry, supplier):
        super().__init__(coordinator, entry, supplier, "cheapest_block_start", "Goedkoopste blok start")

    @property
    def native_value(self) -> str | None:
        b = (self.coordinator.data or {}).get("cheapest_block")
        if not b:
            return None
        return f"{b['start_day']} {b['start_hour']:02d}:00"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        b = (self.coordinator.data or {}).get("cheapest_block")
        if not b:
            return None
        return {
            "start_day": b["start_day"],
            "start_hour": b["start_hour"],
            "end_hour": b["end_hour"],
            "duration_hours": 3,
        }


class CheapestBlockAverageSensor(_BaseSensor):
    _attr_native_unit_of_measurement = UNIT_EUR_PER_KWH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 4
    _attr_icon = "mdi:cash-marker"

    def __init__(self, coordinator, entry, supplier):
        super().__init__(coordinator, entry, supplier, "cheapest_block_avg", "Goedkoopste blok gemiddelde")

    @property
    def native_value(self) -> float | None:
        b = (self.coordinator.data or {}).get("cheapest_block")
        return b["avg"] if b else None


class NextNegativeSensor(_BaseSensor):
    _attr_icon = "mdi:flash-alert"

    def __init__(self, coordinator, entry, supplier):
        super().__init__(coordinator, entry, supplier, "next_negative", "Volgende negatieve prijs")

    @property
    def native_value(self) -> str | None:
        n = (self.coordinator.data or {}).get("next_negative")
        if not n:
            return "geen"
        return f"{n['day']} {n['hour']:02d}:00"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        n = (self.coordinator.data or {}).get("next_negative")
        if not n:
            return None
        return {"day": n["day"], "hour": n["hour"], "price_eur_per_kwh": n["price"]}


class CurrentLevelSensor(_BaseSensor):
    _attr_icon = "mdi:gauge"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry, supplier):
        super().__init__(coordinator, entry, supplier, "level", "Tariefniveau nu")

    @property
    def native_value(self) -> str | None:
        cur = (self.coordinator.data or {}).get("current")
        return cur["now"]["level"] if cur else None
