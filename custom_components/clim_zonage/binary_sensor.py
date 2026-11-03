"""Binary sensors du zonage : demande globale et cheminée."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, NAME
from .coordinator import ZonageCoordinator


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator: ZonageCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            DemandeBinarySensor(coordinator, entry),
            FeuBinarySensor(coordinator, entry),
            ChemineeTakeoverBinarySensor(coordinator, entry),
        ]
    )


class _Base(CoordinatorEntity[ZonageCoordinator], BinarySensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, key: str):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=NAME,
            manufacturer="rpouetpouet",
            model="Zonage gainable réversible",
        )


class DemandeBinarySensor(_Base):
    _attr_name = "Chauffage en demande"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "demande")

    @property
    def is_on(self) -> bool:
        data = self.coordinator.data
        if not data:
            return False
        return any(z.get("demand") for z in data.zones.values())


class FeuBinarySensor(_Base):
    """Feu détecté par l'écart panache/ambiance (hystérésis 5 °C / 2 °C)."""

    _attr_name = "Cheminée : feu détecté"
    _attr_device_class = BinarySensorDeviceClass.HEAT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "feu")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data and self.coordinator.data.fire)


class ChemineeTakeoverBinarySensor(_Base):
    """Le feu est autorisé à être le seul chauffage de la pièce (pièce ≥ 19 °C)."""

    _attr_name = "Cheminée : chauffage assuré par le feu"
    _attr_icon = "mdi:fireplace"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "cheminee_prise_en_charge")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data and self.coordinator.data.fire_takeover)

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data
        if not data:
            return {}
        fire_zone = next((z for z in self.coordinator.zones if z.fire_room), None)
        return {
            "zone": fire_zone.name if fire_zone else None,
            "temperature_piece": data.zones.get(fire_zone.uid, {}).get("temp")
            if fire_zone
            else None,
            "seuil_prise_en_charge": self.coordinator.options.get("fire_temp_min"),
            "seuil_desarmement": self.coordinator.options.get("fire_temp_off"),
            "force_manuelle": self.coordinator.fire_force,
        }
