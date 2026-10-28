from homeassistant.components.light import ATTR_EFFECT, ColorMode, LightEntity, LightEntityFeature
from homeassistant.exceptions import HomeAssistantError

from .entity import HARFEntity, setup_dynamic


class RFLight(HARFEntity, LightEntity):
    _attr_assumed_state = True
    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_color_mode = ColorMode.ONOFF
    _attr_is_on = None
    _attr_effect = None

    @property
    def effect_commands(self):
        return {
            self.manager.library["commands"][key]["name"]: key
            for key in (self.record or {}).get("effects", [])
            if key in self.manager.library["commands"]
        }

    @property
    def supported_features(self):
        return LightEntityFeature.EFFECT if self.effect_commands else LightEntityFeature(0)

    @property
    def effect_list(self):
        return list(self.effect_commands)

    @property
    def effect(self):
        return self._attr_effect if self._attr_effect in self.effect_commands else None

    async def async_turn_on(self, **kwargs):
        effect = kwargs.get(ATTR_EFFECT)
        if effect is not None and effect not in self.effect_commands:
            raise HomeAssistantError(f"Unknown RF light effect: {effect}")
        # Send the effect alone: an additional On command could reset the remote's mode.
        await self.manager.send_command(self.effect_commands[effect] if effect is not None else self.record["on"])
        self._attr_is_on = True
        self._attr_effect = effect
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        await self.manager.send_command(self.record["off"])
        self._attr_is_on = False
        self._attr_effect = None
        self.async_write_ha_state()


async def async_setup_entry(hass, entry, async_add_entities):
    setup_dynamic(hass, entry, async_add_entities, "devices", RFLight, lambda r: r["kind"] == "light")
