"""Thermostat d'une zone.

L'entité est volontairement mince : toute la décision est dans le coordinateur.
Ici on ne fait que traduire l'état du coordinateur en attributs HA, et les
actions de l'utilisateur en appels au coordinateur.
"""

from __future__ import annotations

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import (
    DOMAIN,
    HVAC_COOL,
    HVAC_FAN_ONLY,
    HVAC_HEAT,
    HVAC_OFF,
    MAX_TEMP,
    MIN_TEMP,
    NAME,
    TEMP_STEP,
)
from .coordinator import ZonageCoordinator

_MODES = {
    HVAC_OFF: HVACMode.OFF,
    HVAC_HEAT: HVACMode.HEAT,
    HVAC_COOL: HVACMode.COOL,
    HVAC_FAN_ONLY: HVACMode.FAN_ONLY,
}
_MODES_REVERSE = {v: k for k, v in _MODES.items()}


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator: ZonageCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [ZoneClimate(coordinator, entry, zone) for zone in coordinator.zones]
    )


class ZoneClimate(CoordinatorEntity[ZonageCoordinator], ClimateEntity, RestoreEntity):
    """Thermostat d'une zone du gainable."""

    _attr_has_entity_name = True
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = TEMP_STEP
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE

    def __init__(self, coordinator: ZonageCoordinator, entry, zone):
        super().__init__(coordinator)
        self._entry = entry
        self.zone = zone
        self._attr_name = zone.name
        self._attr_unique_id = f"{entry.entry_id}_{zone.uid}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=NAME,
            manufacturer="rpouetpouet",
            model="Zonage gainable réversible",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            if last.state in (HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL):
                self.coordinator.zone_modes[self.zone.uid] = _MODES_REVERSE[last.state]
            temp = last.attributes.get(ATTR_TEMPERATURE)
            if temp is not None:
                try:
                    self.coordinator.zone_targets[self.zone.uid] = float(temp)
                except (TypeError, ValueError):
                    pass
            # Hystérésis : on reprend l'état de demande là où on l'avait laissé,
            # sinon une pièce en demande au moment du redémarrage attendrait de
            # repasser sous le seuil de démarrage (0.7 °C plus bas).
            demande = last.attributes.get("demande")
            if isinstance(demande, bool):
                self.coordinator.seed_zone_demand(self.zone.uid, demande)
        self.coordinator.zone_modes.setdefault(self.zone.uid, HVAC_OFF)
        self.coordinator.zone_targets.setdefault(self.zone.uid, 19.5)

    @property
    def _zdata(self) -> dict:
        if not self.coordinator.data or not self.coordinator.data.zones:
            return {}
        return self.coordinator.data.zones.get(self.zone.uid, {})

    @property
    def current_temperature(self) -> float | None:
        return self._zdata.get("temp")

    @property
    def target_temperature(self) -> float | None:
        return self._zdata.get("target")

    @property
    def hvac_mode(self) -> HVACMode:
        return _MODES.get(self._zdata.get("mode", HVAC_OFF), HVACMode.OFF)

    @property
    def hvac_action(self) -> HVACAction | None:
        zdata = self._zdata
        if zdata.get("system_off") or zdata.get("mode") == HVAC_OFF:
            return HVACAction.OFF
        if zdata.get("mode") == HVAC_FAN_ONLY:
            return HVACAction.FAN
        if zdata.get("demand"):
            return (
                HVACAction.HEATING
                if zdata.get("mode") == HVAC_HEAT
                else HVACAction.COOLING
            )
        return HVACAction.IDLE

    @property
    def extra_state_attributes(self) -> dict:
        zdata = self._zdata
        return {
            "demande": zdata.get("demand"),
            "sonde_brute": zdata.get("temp_brute"),
            "offset": zdata.get("offset"),
            "seuil_demarrage": zdata.get("seuil_demarrage"),
            "seuil_arret": zdata.get("seuil_arret"),
            "clapet_ouvert": zdata.get("open"),
            "cheminee_assure_le_chauffage": self.coordinator.data.fire_takeover
            if self.coordinator.data
            else None,
            "clapets": self.zone.dampers,
            "sonde": self.zone.temp_sensor,
        }

    async def async_set_temperature(self, **kwargs) -> None:
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        await self.coordinator.async_set_zone_target(self.zone.uid, float(temp))

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Seuls les modes autorisés par le mode global sont proposés.

        En chaud, une zone ne peut donc pas être réglée en froid : la sélection
        erronée devient impossible au lieu d'être ignorée en silence avec une
        carte qui afficherait « cool » sans rien refroidir.
        """
        return [_MODES[m] for m in self.coordinator.allowed_zone_modes()]

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        mode = _MODES_REVERSE.get(hvac_mode, HVAC_OFF)
        if mode not in self.coordinator.allowed_zone_modes():
            raise HomeAssistantError(
                f"Mode « {hvac_mode} » interdit : la maison est en "
                f"« {self.coordinator.mode} ». Change d'abord le mode global."
            )
        await self.coordinator.async_set_zone_mode(self.zone.uid, mode)
