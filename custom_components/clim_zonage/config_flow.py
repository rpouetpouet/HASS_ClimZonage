"""Config flow et options flow du zonage."""

from __future__ import annotations

import logging
import uuid
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.util import slugify

from .const import (
    CONF_CYCLE_SECONDS,
    CONF_DAMPER_COURSE,
    CONF_SENSOR_FROZEN_H,
    CONF_TEMP_SOURCE_SELECT,
    CONF_SENSOR_GRACE_S,
    CONF_SENSOR_TIMEOUT_MIN,
    CONF_DEADBAND,
    CONF_ENGINE,
    CONF_FALLBACK_COOL,
    CONF_FALLBACK_HEAT,
    CONF_FAN_THRESHOLDS,
    CONF_FIRE_DELTA_OFF,
    CONF_FIRE_DELTA_ON,
    CONF_FIRE_TEMP_MIN,
    CONF_FIRE_TEMP_OFF,
    CONF_FIREPLACE,
    CONF_MARGIN,
    CONF_MIN_CYCLE,
    CONF_MIN_VENTS,
    CONF_STRATEGY,
    CONF_ZONE_DAMPERS,
    CONF_ZONE_DUMP,
    CONF_ZONE_FIRE_ROOM,
    CONF_ZONE_OFFSET,
    CONF_ZONE_NAME,
    CONF_ZONE_SENSOR,
    CONF_ZONE_UID,
    CONF_ZONES,
    DEFAULT_CYCLE_SECONDS,
    DEFAULT_DAMPER_COURSE,
    DEFAULT_DEADBAND,
    DEFAULT_FALLBACK_COOL,
    DEFAULT_FALLBACK_HEAT,
    DEFAULT_FAN_THRESHOLDS,
    DEFAULT_FIRE_DELTA_OFF,
    DEFAULT_FIRE_DELTA_ON,
    DEFAULT_FIRE_TEMP_MIN,
    DEFAULT_FIRE_TEMP_OFF,
    DEFAULT_MARGIN,
    DEFAULT_MIN_CYCLE,
    DEFAULT_MIN_VENTS,
    DEFAULT_SENSOR_FROZEN_H,
    DEFAULT_SENSOR_GRACE_S,
    DEFAULT_SENSOR_TIMEOUT_MIN,
    DEFAULT_STRATEGY,
    DOMAIN,
    NAME,
    STRATEGIES,
)

_LOGGER = logging.getLogger(__name__)

GLOBAL_DEFAULTS: dict[str, Any] = {
    CONF_STRATEGY: DEFAULT_STRATEGY,
    CONF_DEADBAND: DEFAULT_DEADBAND,
    CONF_MIN_CYCLE: DEFAULT_MIN_CYCLE,
    CONF_MIN_VENTS: DEFAULT_MIN_VENTS,
    CONF_MARGIN: DEFAULT_MARGIN,
    CONF_FALLBACK_HEAT: DEFAULT_FALLBACK_HEAT,
    CONF_FALLBACK_COOL: DEFAULT_FALLBACK_COOL,
    CONF_FIRE_DELTA_ON: DEFAULT_FIRE_DELTA_ON,
    CONF_FIRE_DELTA_OFF: DEFAULT_FIRE_DELTA_OFF,
    CONF_FIRE_TEMP_MIN: DEFAULT_FIRE_TEMP_MIN,
    CONF_FIRE_TEMP_OFF: DEFAULT_FIRE_TEMP_OFF,
    CONF_FAN_THRESHOLDS: DEFAULT_FAN_THRESHOLDS,
    CONF_CYCLE_SECONDS: DEFAULT_CYCLE_SECONDS,
    CONF_DAMPER_COURSE: DEFAULT_DAMPER_COURSE,
    CONF_SENSOR_TIMEOUT_MIN: DEFAULT_SENSOR_TIMEOUT_MIN,
    CONF_SENSOR_GRACE_S: DEFAULT_SENSOR_GRACE_S,
    CONF_SENSOR_FROZEN_H: DEFAULT_SENSOR_FROZEN_H,
    CONF_TEMP_SOURCE_SELECT: "",
}


def _zone_schema(defaults: dict | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_ZONE_NAME, default=defaults.get(CONF_ZONE_NAME, "")
            ): selector.TextSelector(),
            vol.Required(
                CONF_ZONE_SENSOR, default=defaults.get(CONF_ZONE_SENSOR, "")
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor", device_class="temperature"
                )
            ),
            vol.Required(
                CONF_ZONE_DAMPERS, default=defaults.get(CONF_ZONE_DAMPERS, [])
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="cover", multiple=True)
            ),
            vol.Optional(
                CONF_ZONE_FIRE_ROOM, default=defaults.get(CONF_ZONE_FIRE_ROOM, False)
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_ZONE_DUMP, default=defaults.get(CONF_ZONE_DUMP, False)
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_ZONE_OFFSET, default=defaults.get(CONF_ZONE_OFFSET, 0.0)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=-5, max=5, step=0.1, mode=selector.NumberSelectorMode.BOX
                )
            ),
        }
    )


def _global_schema(current: dict) -> vol.Schema:
    cur = {**GLOBAL_DEFAULTS, **{k: v for k, v in current.items() if k in GLOBAL_DEFAULTS}}
    return vol.Schema(
        {
            vol.Required(CONF_STRATEGY, default=cur[CONF_STRATEGY]): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=STRATEGIES,
                    translation_key="strategy",
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
            vol.Required(CONF_DEADBAND, default=cur[CONF_DEADBAND]): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.1, max=3.0, step=0.1, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Required(CONF_MIN_CYCLE, default=cur[CONF_MIN_CYCLE]): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=60, max=1800, step=30, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Required(CONF_MIN_VENTS, default=cur[CONF_MIN_VENTS]): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=7, step=1, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Required(CONF_MARGIN, default=cur[CONF_MARGIN]): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.5, max=6.0, step=0.5, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Required(
                CONF_FALLBACK_HEAT, default=cur[CONF_FALLBACK_HEAT]
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=10, max=20, step=0.5, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Required(
                CONF_FALLBACK_COOL, default=cur[CONF_FALLBACK_COOL]
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=24, max=31, step=0.5, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Required(
                CONF_FIRE_DELTA_ON, default=cur[CONF_FIRE_DELTA_ON]
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1.0, max=20.0, step=0.5, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Required(
                CONF_FIRE_DELTA_OFF, default=cur[CONF_FIRE_DELTA_OFF]
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.5, max=10.0, step=0.5, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Required(
                CONF_FIRE_TEMP_MIN, default=cur[CONF_FIRE_TEMP_MIN]
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=14, max=24, step=0.5, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Required(
                CONF_FIRE_TEMP_OFF, default=cur[CONF_FIRE_TEMP_OFF]
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=12, max=23, step=0.5, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Required(
                CONF_CYCLE_SECONDS, default=cur[CONF_CYCLE_SECONDS]
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=10, max=900, step=5, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Required(
                CONF_DAMPER_COURSE, default=cur[CONF_DAMPER_COURSE]
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=30, max=300, step=5, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Required(
                CONF_SENSOR_TIMEOUT_MIN, default=cur[CONF_SENSOR_TIMEOUT_MIN]
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=120, step=1, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Required(
                CONF_SENSOR_GRACE_S, default=cur[CONF_SENSOR_GRACE_S]
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=1800, step=10, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Required(
                CONF_SENSOR_FROZEN_H, default=cur[CONF_SENSOR_FROZEN_H]
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=48, step=1, mode=selector.NumberSelectorMode.BOX
                )
            ),
            # Facultatif : entité `select` du réglage 102 de l'unité (source de
            # température). Sans elle, le mode MANUEL laisse l'unité sur la
            # température déportée au lieu du thermostat de la télécommande.
            vol.Optional(
                CONF_TEMP_SOURCE_SELECT,
                description={"suggested_value": cur[CONF_TEMP_SOURCE_SELECT] or None},
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="select")
            ),
        }
    )


class ClimZonageConfigFlow(ConfigFlow, domain=DOMAIN):
    """Création de l'entrée : moteur, sonde de cheminée, puis les zones."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._zones: list[dict] = []

    async def async_step_user(self, user_input: dict | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            engine = user_input[CONF_ENGINE]
            if self.hass.states.get(engine) is None:
                errors["base"] = "engine_not_found"
            else:
                self._data[CONF_ENGINE] = engine
                self._data[CONF_FIREPLACE] = user_input.get(CONF_FIREPLACE) or None
                return await self.async_step_zone_menu()

        schema = vol.Schema(
            {
                vol.Required(CONF_ENGINE): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="climate")
                ),
                vol.Optional(CONF_FIREPLACE): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor", device_class="temperature"
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

    async def async_step_zone_menu(self, user_input: dict | None = None):
        if user_input is not None:
            if user_input.get("next") == "add":
                return await self.async_step_add_zone()
            if not self._zones:
                return self.async_show_form(
                    step_id="zone_menu",
                    data_schema=vol.Schema(
                        {
                            vol.Required("next", default="add"): selector.SelectSelector(
                                selector.SelectSelectorConfig(
                                    options=["add", "finish"],
                                    translation_key="zone_menu",
                                    mode=selector.SelectSelectorMode.LIST,
                                )
                            )
                        }
                    ),
                    errors={"base": "need_one_zone"},
                    description_placeholders={"count": str(len(self._zones))},
                )
            return self.async_create_entry(
                title=NAME,
                data={**self._data, CONF_ZONES: self._zones, **GLOBAL_DEFAULTS},
            )

        return self.async_show_form(
            step_id="zone_menu",
            data_schema=vol.Schema(
                {
                    vol.Required("next", default="add"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=["add", "finish"],
                            translation_key="zone_menu",
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
            description_placeholders={"count": str(len(self._zones))},
        )

    async def async_step_add_zone(self, user_input: dict | None = None):
        if user_input is not None:
            zone = dict(user_input)
            zone[CONF_ZONE_UID] = slugify(zone[CONF_ZONE_NAME]) or uuid.uuid4().hex[:8]
            self._zones.append(zone)
            return await self.async_step_zone_menu()
        return self.async_show_form(step_id="add_zone", data_schema=_zone_schema())

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return ClimZonageOptionsFlow(config_entry)


class ClimZonageOptionsFlow(OptionsFlow):
    """Réglages globaux et gestion des zones, sans toucher au YAML."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self.entry = config_entry
        self._pending: dict[str, Any] = {}

    def _zones(self) -> list[dict]:
        return list(
            self.entry.options.get(CONF_ZONES, self.entry.data.get(CONF_ZONES, []))
        )

    async def async_step_init(self, user_input: dict | None = None):
        return self.async_show_menu(
            step_id="init",
            menu_options=["global", "add_zone", "edit_zone", "delete_zone"],
        )

    async def async_step_global(self, user_input: dict | None = None):
        if user_input is not None:
            data = {**self.entry.options}
            data.pop(CONF_ZONES, None)
            data.update(user_input)
            # Une entité facultative laissée vide revient à None : on stocke une
            # chaîne vide, sinon `options.get(...)` rend None et le test `if not
            # entity` du coordinateur se comporte différemment d'une absence.
            data[CONF_TEMP_SOURCE_SELECT] = data.get(CONF_TEMP_SOURCE_SELECT) or ""
            data[CONF_ZONES] = self._zones()
            return self.async_create_entry(title="", data=data)
        current = {**self.entry.data, **self.entry.options}
        return self.async_show_form(step_id="global", data_schema=_global_schema(current))

    async def async_step_add_zone(self, user_input: dict | None = None):
        if user_input is not None:
            zone = dict(user_input)
            zone[CONF_ZONE_UID] = slugify(zone[CONF_ZONE_NAME]) or uuid.uuid4().hex[:8]
            data = {**self.entry.options, **self.entry.data}
            data.pop(CONF_ZONES, None)
            data[CONF_ZONES] = self._zones() + [zone]
            return self.async_create_entry(title="", data=data)
        return self.async_show_form(step_id="add_zone", data_schema=_zone_schema())

    async def async_step_edit_zone(self, user_input: dict | None = None):
        zones = self._zones()
        if not zones:
            return self.async_abort(reason="no_zone")

        # 3e etape : le formulaire complet a ete soumis -> on applique.
        # On teste la presence du nom, car l'etape de selection ne renvoie que l'uid.
        if user_input is not None and CONF_ZONE_NAME in user_input:
            uid = user_input[CONF_ZONE_UID]
            if uid == "__new__":
                return await self.async_step_add_zone()
            for zone in zones:
                if zone[CONF_ZONE_UID] == uid:
                    for key in (
                        CONF_ZONE_NAME,
                        CONF_ZONE_SENSOR,
                        CONF_ZONE_DAMPERS,
                        CONF_ZONE_FIRE_ROOM,
                        CONF_ZONE_DUMP,
                        CONF_ZONE_OFFSET,
                    ):
                        zone[key] = user_input[key]
                    break
            data = {**self.entry.options, **self.entry.data}
            data.pop(CONF_ZONES, None)
            data[CONF_ZONES] = zones
            return self.async_create_entry(title="", data=data)

        # 2e etape : une zone a ete choisie -> on affiche ses reglages, pre-remplis.
        if user_input is not None:
            uid = user_input[CONF_ZONE_UID]
            if uid == "__new__":
                return await self.async_step_add_zone()
            zone = next((z for z in zones if z[CONF_ZONE_UID] == uid), None)
            if zone is None:
                return self.async_abort(reason="no_zone")
            return self.async_show_form(
                step_id="edit_zone",
                data_schema=_zone_schema(zone).extend(
                    {
                        vol.Required(CONF_ZONE_UID, default=uid): selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=[
                                    {
                                        "value": uid,
                                        "label": zone[CONF_ZONE_NAME],
                                    }
                                ],
                                mode=selector.SelectSelectorMode.LIST,
                            )
                        )
                    }
                ),
            )

        # 1re etape : choix de la zone a modifier.
        return self.async_show_form(
            step_id="edit_zone",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ZONE_UID, default=zones[0][CONF_ZONE_UID]): (
                        selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=[
                                    {"value": z[CONF_ZONE_UID], "label": z[CONF_ZONE_NAME]}
                                    for z in zones
                                ],
                                mode=selector.SelectSelectorMode.LIST,
                            )
                        )
                    )
                }
            ),
        )

    async def async_step_delete_zone(self, user_input: dict | None = None):
        zones = self._zones()
        if not zones:
            return self.async_abort(reason="no_zone")
        if user_input is not None:
            uid = user_input[CONF_ZONE_UID]
            data = {**self.entry.options, **self.entry.data}
            data.pop(CONF_ZONES, None)
            data[CONF_ZONES] = [z for z in zones if z[CONF_ZONE_UID] != uid]
            return self.async_create_entry(title="", data=data)

        return self.async_show_form(
            step_id="delete_zone",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ZONE_UID): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {"value": z[CONF_ZONE_UID], "label": z[CONF_ZONE_NAME]}
                                for z in zones
                            ],
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )
