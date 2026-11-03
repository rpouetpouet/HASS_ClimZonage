"""Switches du zonage : le master et la prise en charge cheminée."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, NAME
from .coordinator import ZonageCoordinator


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator: ZonageCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            ZonageActiveSwitch(coordinator, entry),
            ChemineeForceSwitch(coordinator, entry),
        ]
    )


class _Base(CoordinatorEntity[ZonageCoordinator], SwitchEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: ZonageCoordinator, entry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=NAME,
            manufacturer="rpouetpouet",
            model="Zonage gainable réversible",
        )


class ZonageActiveSwitch(_Base, RestoreEntity):
    """Master switch : seul chemin pour éteindre le système.

    OFF = moteur éteint + tous les clapets fermés. C'est le point d'accroche
    unique d'une automatisation de présence (mode manuel / absence).
    """

    _attr_name = "Système actif"
    _attr_icon = "mdi:power"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_actif"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            self.coordinator.active = last.state == "on"

    @property
    def is_on(self) -> bool:
        return self.coordinator.active

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_active(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_active(False)
        self.async_write_ha_state()


class ChemineeForceSwitch(_Base, RestoreEntity):
    """Force manuellement le mode « le feu chauffe la pièce ».

    Utile quand la détection automatique ne se déclenche pas (feu qui couve,
    sonde déplacée) ou quand on veut l'interdire (cheminée à pellets bruyante).
    """

    _attr_name = "Cheminée : chauffage assuré par le feu"
    _attr_icon = "mdi:fireplace"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_cheminee_force"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            self.coordinator.fire_force = last.state == "on"

    @property
    def is_on(self) -> bool:
        return self.coordinator.fire_force

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data
        return {
            "feu_detecte": data.fire if data else None,
            "prise_en_charge_auto": data.fire_takeover if data else None,
        }

    async def async_turn_on(self, **kwargs) -> None:
        self.coordinator.fire_force = True
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self.coordinator.fire_force = False
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()
