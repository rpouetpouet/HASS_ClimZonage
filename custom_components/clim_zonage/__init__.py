"""Mise en place de l'intégration clim_zonage."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import CONF_ZONES, DOMAIN, NAME
from .coordinator import ZonageCoordinator, build_zones

_LOGGER = logging.getLogger(__name__)

PLATFORMS_LIST = ["climate", "switch", "select", "sensor", "binary_sensor"]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Rien à faire en YAML : tout passe par l'entrée de configuration."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Crée le coordinateur et les entités d'une entrée."""
    hass.data.setdefault(DOMAIN, {})

    zones = build_zones(entry.options.get(CONF_ZONES, entry.data.get(CONF_ZONES, [])))
    options = {**entry.data, **entry.options}

    coordinator = ZonageCoordinator(hass, entry, zones, options)
    await coordinator.async_setup()
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS_LIST)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    _LOGGER.info(
        "%s : %d zone(s) pilotée(s), moteur %s", NAME, len(zones), coordinator.engine
    )
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Une modification d'options recharge l'entrée (aucun redémarrage HA)."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Décharge l'entrée."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS_LIST)
    if unload_ok:
        coordinator: ZonageCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()
    return unload_ok
