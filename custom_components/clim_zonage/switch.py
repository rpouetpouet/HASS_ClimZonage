"""Switches du zonage : la prise en charge cheminée.

Le master switch ON/OFF a été remplacé en 0.13.0 par le sélecteur à trois
positions `select.clim_zonage_mode_du_systeme` (Auto / Manuel / Arrêt) : deux
états ne suffisaient plus à distinguer « le zonage régule », « l'utilisateur a
la main, vannes ouvertes » et « tout est arrêté ».
"""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_ON
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, NAME
from .coordinator import ZonageCoordinator


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator: ZonageCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ChemineeForceSwitch(coordinator, entry)])


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
            self.coordinator.fire_force = last.state == STATE_ON

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
