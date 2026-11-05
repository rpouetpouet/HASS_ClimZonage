"""Sélecteur de mode global du zonage (chaud / froid / ventilation seule)."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    HVAC_COOL,
    HVAC_FAN_ONLY,
    HVAC_HEAT,
    NAME,
    SYSTEM_AUTO,
    SYSTEM_FROM_LABEL,
    SYSTEM_LABELS,
    SYSTEM_MODES,
)
from .coordinator import ZonageCoordinator

OPTIONS = [HVAC_HEAT, HVAC_COOL, HVAC_FAN_ONLY]
LABELS = {HVAC_HEAT: "Chaud", HVAC_COOL: "Froid", HVAC_FAN_ONLY: "Ventilation seule"}


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator: ZonageCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [ZonageSystemeSelect(coordinator, entry), ZonageModeSelect(coordinator, entry)]
    )


class ZonageSystemeSelect(CoordinatorEntity[ZonageCoordinator], SelectEntity, RestoreEntity):
    """Mode du système : Auto / Manuel / Arrêt — le seul point d'accroche.

    - **Auto** : le zonage régule (clapets, consigne, vitesse du moteur) ;
    - **Manuel** : toutes les vannes ouvertes une fois, puis plus aucune
      décision — on reprend la main sur le gainable (panneau ou entité
      `climate`), et l'unité régule sur le thermostat de la télécommande filaire ;
    - **Arrêt** : moteur éteint + clapets fermés une fois.
    """

    _attr_has_entity_name = True
    _attr_name = "Mode du système"
    _attr_icon = "mdi:power-settings"

    def __init__(self, coordinator: ZonageCoordinator, entry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_systeme"
        self._attr_options = [SYSTEM_LABELS[m] for m in SYSTEM_MODES]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=NAME,
            manufacturer="rpouetpouet",
            model="Zonage gainable réversible",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in SYSTEM_FROM_LABEL:
            self.coordinator.system_mode = SYSTEM_FROM_LABEL[last.state]
        else:
            self.coordinator.system_mode = SYSTEM_AUTO

    @property
    def current_option(self) -> str:
        return SYSTEM_LABELS.get(self.coordinator.system_mode, SYSTEM_LABELS[SYSTEM_AUTO])

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data
        return {
            "mode_interne": self.coordinator.system_mode,
            "systeme_actif": self.coordinator.system_mode == SYSTEM_AUTO,
            "zones_gerees": data.active if data else None,
        }

    async def async_select_option(self, option: str) -> None:
        mode = SYSTEM_FROM_LABEL.get(option)
        if mode is not None:
            await self.coordinator.async_set_system_mode(mode)
            self.async_write_ha_state()


class ZonageModeSelect(CoordinatorEntity[ZonageCoordinator], SelectEntity, RestoreEntity):
    _attr_has_entity_name = True
    _attr_name = "Mode global"
    _attr_icon = "mdi:hvac"

    def __init__(self, coordinator: ZonageCoordinator, entry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_mode"
        self._attr_options = OPTIONS
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=NAME,
            manufacturer="rpouetpouet",
            model="Zonage gainable réversible",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in OPTIONS:
            self.coordinator.mode = last.state

    @property
    def current_option(self) -> str:
        return self.coordinator.mode

    @property
    def extra_state_attributes(self) -> dict:
        return {"libelles": LABELS}

    async def async_select_option(self, option: str) -> None:
        if option in OPTIONS:
            await self.coordinator.async_set_global_mode(option)
            self.async_write_ha_state()
