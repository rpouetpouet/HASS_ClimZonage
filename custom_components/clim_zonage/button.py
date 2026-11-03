"""Boutons du zonage : recalibration des clapets."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DAMPER_COURSE, DOMAIN, NAME
from .coordinator import ZonageCoordinator


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator: ZonageCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([RecalibrationButton(coordinator, entry)])


class RecalibrationButton(CoordinatorEntity[ZonageCoordinator], ButtonEntity):
    """Cycle forcé : tout fermer, attendre la course, rouvrir selon la demande.

    Nécessaire parce qu'un clapet ne renvoie aucune position : son état dans HA
    n'est qu'une croyance, mise à jour à l'expiration de la course. Après un
    déplacement manuel, une coupure de courant pendant une course ou un ordre
    Stop, seul un cycle complet réaligne le réel sur la croyance.
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
            "en_cours": self.coordinator.recalibrating,
            "duree_course_s": int(
                self.coordinator.options.get(CONF_DAMPER_COURSE, 80)
            ),
            "zones_ouvertes_avant": sorted(
                z["name"] for z in (data.zones.values() if data else []) if z.get("open")
            ),
            "avertissement": (
                "Ferme tous les clapets pendant la durée de course : "
                "aucun chauffage distribué pendant ce temps."
            ),
        }

    async def async_press(self) -> None:
        await self.coordinator.async_recalibrate_dampers()
        self.async_write_ha_state()
