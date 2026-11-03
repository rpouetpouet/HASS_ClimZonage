"""Boutons du zonage : recalibration des clapets."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_CYCLE_SECONDS, DOMAIN, NAME
from .coordinator import ZonageCoordinator


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator: ZonageCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([RecalibrationButton(coordinator, entry)])


class RecalibrationButton(CoordinatorEntity[ZonageCoordinator], ButtonEntity):
    """Réaffirme la position voulue sur tous les clapets, sans rien inverser.

    Un clapet ne renvoie aucune position : son état dans HA n'est qu'une
    croyance. Après un déplacement manuel, une coupure de courant pendant une
    course ou un ordre Stop, le réel peut avoir divergé. Ce bouton demande à
    renvoyer l'ordre à chaque clapet au cycle suivant — dans la position déjà
    voulue, qu'il y ait changement d'état ou non. Aucun chauffage n'est
    interrompu, et un clapet réellement bien positionné ne bouge pas.
    """

    _attr_has_entity_name = True
    _attr_name = "Recalibrer les clapets"
    _attr_icon = "mdi:valve"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: ZonageCoordinator, entry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_recalibrer_clapets"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=NAME,
            manufacturer="rpouetpouet",
            model="Zonage gainable réversible",
        )

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data
        return {
            "demande_en_attente": self.coordinator.recalibration_demandee,
            "delai_max_s": int(self.coordinator.options.get(CONF_CYCLE_SECONDS, 30)),
            "zones_ouvertes_avant": sorted(
                z["name"] for z in (data.zones.values() if data else []) if z.get("open")
            ),
            "effet": (
                "Renvoie l'ordre open/close à tous les clapets au prochain cycle, "
                "dans la position voulue : rien n'est inversé, aucun chauffage interrompu."
            ),
        }

    async def async_press(self) -> None:
        await self.coordinator.async_recalibrate_dampers()
        self.async_write_ha_state()
