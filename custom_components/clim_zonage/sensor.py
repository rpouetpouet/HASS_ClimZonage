"""Capteurs de diagnostic du zonage — la lecture de ce que fait le cerveau."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, NAME
from .coordinator import ZonageCoordinator


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator: ZonageCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            OpenVentsSensor(coordinator, entry),
            EngineSetpointSensor(coordinator, entry),
            VirtualTempSensor(coordinator, entry),
            DemandingZonesSensor(coordinator, entry),
            StrategySensor(coordinator, entry),
            SondesIndisponiblesSensor(coordinator, entry),
        ]
    )


class _Base(CoordinatorEntity[ZonageCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry, key: str):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=NAME,
            manufacturer="rpouetpouet",
            model="Zonage gainable réversible",
        )


class OpenVentsSensor(_Base):
    _attr_name = "Bouches ouvertes"
    _attr_icon = "mdi:air-filter"
    _attr_native_unit_of_measurement = "bouches"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "bouches_ouvertes")

    @property
    def native_value(self) -> int | None:
        return self.coordinator.data.open_vents if self.coordinator.data else None

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data
        if not data:
            return {}
        return {
            "zones_ouvertes": [
                z["name"] for z in data.zones.values() if z.get("open")
            ],
            "clapets_ouverts": {
                z["name"]: z.get("clapets_ouverts", 0)
                for z in data.zones.values()
                if z.get("open")
            },
            "comptage": "clapets physiques (la salle à manger en a deux)",
        }


class EngineSetpointSensor(_Base):
    _attr_name = "Consigne moteur"
    _attr_icon = "mdi:thermostat"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "consigne_moteur")

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.engine_setpoint if self.coordinator.data else None


class VirtualTempSensor(_Base):
    _attr_name = "Température déportée"
    _attr_icon = "mdi:home-thermometer"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "temperature_deportee")

    @property
    def native_value(self) -> float | None:
        if not self.coordinator.data:
            return None
        value = self.coordinator.data.virtual_temp
        return round(value, 1) if value is not None else None

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "methode": "zones en demande uniquement (la plus froide en chaud, la plus chaude en froid)",
            "usage": "à envoyer au gainable via remote_temperature_source (stratégie déportée)",
        }


class DemandingZonesSensor(_Base):
    _attr_name = "Zones en demande"
    _attr_icon = "mdi:home-lightning-bolt"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "zones_en_demande")

    @property
    def native_value(self) -> int | None:
        data = self.coordinator.data
        if not data:
            return None
        return sum(1 for z in data.zones.values() if z.get("demand"))

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data
        if not data:
            return {}
        return {
            "zones": [z["name"] for z in data.zones.values() if z.get("demand")],
            "mode": data.mode,
            "feu": data.fire,
            "cheminee_assure_le_chauffage": data.fire_takeover,
            "systeme_actif": data.active,
        }


class StrategySensor(_Base):
    """Stratégie réellement appliquée au moteur (et repli éventuel)."""

    _attr_name = "Stratégie moteur"
    _attr_icon = "mdi:source-branch"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "strategie")

    @property
    def native_value(self) -> str | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.strategy or None

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data
        if not data:
            return {}
        demande = self.coordinator.options.get("strategy")
        return {
            "strategie_demandee": demande,
            "repli_actif": demande != data.strategy,
            "temperature_deportee_disponible": data.virtual_temp is not None,
            "consigne_envoyee": data.engine_setpoint,
        }


class SondesIndisponiblesSensor(_Base):
    """Nombre de sondes essentielles muettes, avec le détail des minutes écoulées."""

    _attr_name = "Sondes indisponibles"
    _attr_icon = "mdi:thermometer-alert"
    _attr_native_unit_of_measurement = "sondes"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "sondes_indisponibles")

    @property
    def native_value(self) -> int:
        return len(self.coordinator.sensor_ko) + len(self.coordinator.sensor_figes)

    @property
    def extra_state_attributes(self) -> dict:
        coord = self.coordinator
        return {
            "mode": coord.watchdog,
            "sondes_suivies": coord.sensor_total,
            "indisponibles": sorted(coord.sensor_ko),
            "figees": sorted(coord.sensor_figes),
            "detail": coord.sensor_ko,
        }
