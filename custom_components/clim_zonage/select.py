"""Sélecteur de mode global du zonage (chaud / froid / ventilation seule)."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, HVAC_COOL, HVAC_FAN_ONLY, HVAC_HEAT, NAME
from .coordinator import ZonageCoordinator

OPTIONS = [HVAC_HEAT, HVAC_COOL, HVAC_FAN_ONLY]
LABELS = {HVAC_HEAT: "Chaud", HVAC_COOL: "Froid", HVAC_FAN_ONLY: "Ventilation seule"}


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator: ZonageCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ZonageModeSelect(coordinator, entry)])


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
