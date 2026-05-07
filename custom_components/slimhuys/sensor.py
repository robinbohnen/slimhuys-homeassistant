"""SlimHuys sensors: huidige prijs, dagstats, goedkoopste blok, en live P1-data."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CURRENCY_EURO,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfVolume,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    LIVE_SUFFIX_ACTIVE_POWER,
    LIVE_SUFFIX_ACTIVE_POWER_RETURNED,
    LIVE_SUFFIX_CONSUMPTION_TOTAL,
    LIVE_SUFFIX_CURRENT_L1,
    LIVE_SUFFIX_CURRENT_L2,
    LIVE_SUFFIX_CURRENT_L3,
    LIVE_SUFFIX_DELIVERY_TOTAL,
    LIVE_SUFFIX_GAS_TOTAL,
    LIVE_SUFFIX_POWER_L1,
    LIVE_SUFFIX_POWER_L2,
    LIVE_SUFFIX_POWER_L3,
    LIVE_SUFFIX_VOLTAGE_L1,
    LIVE_SUFFIX_VOLTAGE_L2,
    LIVE_SUFFIX_VOLTAGE_L3,
    LIVE_SUFFIX_WATER_TOTAL,
    P1_MODE_PULL,
)
from .coordinator import SlimHuysCoordinator
from .live_coordinator import SlimHuysLiveCoordinator

_LOGGER = logging.getLogger(__name__)

UNIT_EUR_PER_KWH = f"{CURRENCY_EURO}/kWh"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    state = hass.data[DOMAIN][entry.entry_id]
    coordinator: SlimHuysCoordinator = state["coordinator"]
    supplier = state["supplier"]
    mode = state["mode"]
    live_coordinator: SlimHuysLiveCoordinator | None = state.get("live_coordinator")

    entities: list[SensorEntity] = [
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

    if mode == P1_MODE_PULL and live_coordinator is not None:
        entities.extend(_build_live_entities(live_coordinator, entry, supplier))

    async_add_entities(entities)


def _build_live_entities(
    coordinator: SlimHuysLiveCoordinator,
    entry: ConfigEntry,
    supplier: str,
) -> list[SensorEntity]:
    """Hoofd-set + dynamisch 3-fase op basis van probe-discovery.

    1-fase huizen krijgen geen permanent-unavailable L2/L3-entities. Als
    probe niet uitgevoerd is (`probe_at_setup=False`), dan worden 3-fase-
    entities altijd aangemaakt — `discovered_fields` is dan leeg en
    `_should_add_phase` valt terug op `True` voor alle fasen.
    """
    discovered = coordinator.discovered_fields

    def _has(field: str) -> bool:
        # Geen probe gelopen → discovered is leeg → maak alles aan
        return not discovered or field in discovered

    out: list[SensorEntity] = [
        LiveActivePowerSensor(coordinator, entry, supplier),
        LiveActivePowerReturnedSensor(coordinator, entry, supplier),
        LiveConsumptionTotalSensor(coordinator, entry, supplier),
        LiveDeliveryTotalSensor(coordinator, entry, supplier),
    ]
    if _has("voltage_l1"):
        out.append(LiveVoltageSensor(coordinator, entry, supplier, "l1"))
    if _has("voltage_l2"):
        out.append(LiveVoltageSensor(coordinator, entry, supplier, "l2"))
    if _has("voltage_l3"):
        out.append(LiveVoltageSensor(coordinator, entry, supplier, "l3"))
    if _has("current_l1_a"):
        out.append(LiveCurrentSensor(coordinator, entry, supplier, "l1"))
    if _has("current_l2_a"):
        out.append(LiveCurrentSensor(coordinator, entry, supplier, "l2"))
    if _has("current_l3_a"):
        out.append(LiveCurrentSensor(coordinator, entry, supplier, "l3"))
    if _has("active_power_l1_w"):
        out.append(LivePowerPhaseSensor(coordinator, entry, supplier, "l1"))
    if _has("active_power_l2_w"):
        out.append(LivePowerPhaseSensor(coordinator, entry, supplier, "l2"))
    if _has("active_power_l3_w"):
        out.append(LivePowerPhaseSensor(coordinator, entry, supplier, "l3"))
    if _has("gas_total_m3"):
        out.append(LiveGasTotalSensor(coordinator, entry, supplier))
    out.append(LiveWaterTotalSensor(coordinator, entry, supplier))
    return out


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


# ---------- Live (pull-mode) entities ----------


class _LiveBaseSensor(CoordinatorEntity[SlimHuysLiveCoordinator], SensorEntity):
    """Base voor pull-mode entities — read'en uit live_coordinator.data[stream][field]."""

    _attr_has_entity_name = True
    _stream: str = "p1"
    _field: str = ""

    def __init__(
        self,
        coordinator: SlimHuysLiveCoordinator,
        entry: ConfigEntry,
        supplier: str,
        unique_suffix: str,
        name: str,
    ) -> None:
        super().__init__(coordinator)
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{unique_suffix}"
        # Zelfde device-identifier als prijssensoren — één SlimHuys-device met
        # twee capabilities (prijs + live), niet twee aparte devices.
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": f"SlimHuys ({supplier})",
            "manufacturer": "SlimHuys.nl",
            "model": "Energy prices + P1",
            "configuration_url": "https://slimhuys.nl/app/tarieven",
        }

    def _read(self, key: str | None = None) -> Any:
        block = (self.coordinator.data or {}).get(self._stream) or {}
        return block.get(key or self._field)


class LiveActivePowerSensor(_LiveBaseSensor):
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_icon = "mdi:flash"
    _field = "active_power_w"

    def __init__(self, coordinator, entry, supplier):
        super().__init__(coordinator, entry, supplier, LIVE_SUFFIX_ACTIVE_POWER, "Actief vermogen")

    @property
    def native_value(self) -> int | None:
        v = self._read()
        return int(v) if v is not None else None


class LiveActivePowerReturnedSensor(_LiveBaseSensor):
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_icon = "mdi:transmission-tower-export"
    _field = "active_power_returned_w"

    def __init__(self, coordinator, entry, supplier):
        super().__init__(coordinator, entry, supplier, LIVE_SUFFIX_ACTIVE_POWER_RETURNED, "Teruglevering vermogen")

    @property
    def native_value(self) -> int | None:
        v = self._read()
        return int(v) if v is not None else None


class LiveConsumptionTotalSensor(_LiveBaseSensor):
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_suggested_display_precision = 3
    _attr_icon = "mdi:counter"
    _field = "consumption_total_kwh"

    def __init__(self, coordinator, entry, supplier):
        super().__init__(coordinator, entry, supplier, LIVE_SUFFIX_CONSUMPTION_TOTAL, "Verbruik totaal")

    @property
    def native_value(self) -> float | None:
        v = self._read()
        return float(v) if v is not None else None


class LiveDeliveryTotalSensor(_LiveBaseSensor):
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_suggested_display_precision = 3
    _attr_icon = "mdi:counter"
    _field = "delivered_total_kwh"

    def __init__(self, coordinator, entry, supplier):
        super().__init__(coordinator, entry, supplier, LIVE_SUFFIX_DELIVERY_TOTAL, "Teruglevering totaal")

    @property
    def native_value(self) -> float | None:
        v = self._read()
        return float(v) if v is not None else None


class LiveVoltageSensor(_LiveBaseSensor):
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_icon = "mdi:sine-wave"
    # L2/L3 zijn diagnostic — voorkomt dat 3-fase-details het hoofd-dashboard vervuilen
    _PHASE_NAMES = {"l1": "Spanning L1", "l2": "Spanning L2", "l3": "Spanning L3"}
    _PHASE_SUFFIX = {
        "l1": LIVE_SUFFIX_VOLTAGE_L1,
        "l2": LIVE_SUFFIX_VOLTAGE_L2,
        "l3": LIVE_SUFFIX_VOLTAGE_L3,
    }

    def __init__(self, coordinator, entry, supplier, phase: str):
        super().__init__(
            coordinator, entry, supplier,
            self._PHASE_SUFFIX[phase], self._PHASE_NAMES[phase],
        )
        self._field = f"voltage_{phase}"
        if phase in ("l2", "l3"):
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> float | None:
        v = self._read()
        return float(v) if v is not None else None


class LiveCurrentSensor(_LiveBaseSensor):
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_icon = "mdi:current-ac"
    _PHASE_NAMES = {"l1": "Stroom L1", "l2": "Stroom L2", "l3": "Stroom L3"}
    _PHASE_SUFFIX = {
        "l1": LIVE_SUFFIX_CURRENT_L1,
        "l2": LIVE_SUFFIX_CURRENT_L2,
        "l3": LIVE_SUFFIX_CURRENT_L3,
    }

    def __init__(self, coordinator, entry, supplier, phase: str):
        super().__init__(
            coordinator, entry, supplier,
            self._PHASE_SUFFIX[phase], self._PHASE_NAMES[phase],
        )
        self._field = f"current_{phase}_a"
        if phase in ("l2", "l3"):
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> float | None:
        v = self._read()
        return float(v) if v is not None else None


class LivePowerPhaseSensor(_LiveBaseSensor):
    """Per-fase actief vermogen — signed (negatief = export op die fase)."""
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_icon = "mdi:flash"
    _PHASE_NAMES = {"l1": "Vermogen L1", "l2": "Vermogen L2", "l3": "Vermogen L3"}
    _PHASE_SUFFIX = {
        "l1": LIVE_SUFFIX_POWER_L1,
        "l2": LIVE_SUFFIX_POWER_L2,
        "l3": LIVE_SUFFIX_POWER_L3,
    }

    def __init__(self, coordinator, entry, supplier, phase: str):
        super().__init__(
            coordinator, entry, supplier,
            self._PHASE_SUFFIX[phase], self._PHASE_NAMES[phase],
        )
        self._field = f"active_power_{phase}_w"

    @property
    def native_value(self) -> int | None:
        v = self._read()
        return int(v) if v is not None else None


class LiveGasTotalSensor(_LiveBaseSensor):
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_device_class = SensorDeviceClass.GAS
    _attr_suggested_display_precision = 3
    _attr_icon = "mdi:gas-burner"
    _field = "gas_total_m3"

    def __init__(self, coordinator, entry, supplier):
        super().__init__(coordinator, entry, supplier, LIVE_SUFFIX_GAS_TOTAL, "Gas totaal")

    @property
    def native_value(self) -> float | None:
        v = self._read()
        return float(v) if v is not None else None


class LiveWaterTotalSensor(_LiveBaseSensor):
    """Water-meter cumulatief — native L (puls-eenheid), display m³ voor NL."""
    _attr_native_unit_of_measurement = UnitOfVolume.LITERS
    _attr_suggested_unit_of_measurement = UnitOfVolume.CUBIC_METERS
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_device_class = SensorDeviceClass.WATER
    _attr_suggested_display_precision = 3
    _attr_icon = "mdi:water"
    _stream = "water"
    _field = "total_liter"

    def __init__(self, coordinator, entry, supplier):
        super().__init__(coordinator, entry, supplier, LIVE_SUFFIX_WATER_TOTAL, "Water totaal")

    @property
    def native_value(self) -> float | None:
        v = self._read()
        return float(v) if v is not None else None
