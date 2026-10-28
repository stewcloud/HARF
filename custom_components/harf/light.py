from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.exceptions import HomeAssistantError

from .core import color_rgb, nearest_color
from .entity import HARFEntity, setup_dynamic


class RFLight(HARFEntity, LightEntity):
    _attr_assumed_state = True
    _attr_is_on = None
    _attr_effect = None
    _attr_rgb_color = None
    _attr_brightness = 255

    @property
    def color_commands(self):
        commands = self.manager.library["commands"]
        return {
            key: commands[key]["color"]
            for key in (self.record or {}).get("colors", [])
            if commands.get(key, {}).get("color")
        }

    @property
    def supported_color_modes(self):
        return {ColorMode.RGB} if self.color_commands else {ColorMode.ONOFF}

    @property
    def color_mode(self):
        return ColorMode.RGB if self.color_commands else ColorMode.ONOFF

    @property
    def rgb_color(self):
        palette = [color_rgb(value) for value in self.color_commands.values()]
        return self._attr_rgb_color if self._attr_rgb_color in palette else None

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
        rgb = kwargs.get(ATTR_RGB_COLOR)
        if kwargs.get(ATTR_BRIGHTNESS, 255) != 255:
            raise HomeAssistantError("This RF light has no brightness mappings")
        if effect is not None and rgb is not None:
            raise HomeAssistantError("Choose a captured color or an effect, one at a time")
        if effect is not None and effect not in self.effect_commands:
            raise HomeAssistantError(f"Unknown RF light effect: {effect}")
        selected_rgb = None
        if rgb is not None:
            try:
                command = nearest_color(self.color_commands, rgb)
            except ValueError as err:
                raise HomeAssistantError(str(err)) from err
            selected_rgb = color_rgb(self.color_commands[command])
        else:
            command = self.effect_commands[effect] if effect is not None else self.record["on"]
        # Send the effect alone: an additional On command could reset the remote's mode.
        await self.manager.send_command(command)
        self._attr_is_on = True
        self._attr_effect = effect
        self._attr_rgb_color = selected_rgb
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        await self.manager.send_command(self.record["off"])
        self._attr_is_on = False
        self._attr_effect = None
        self.async_write_ha_state()


async def async_setup_entry(hass, entry, async_add_entities):
    setup_dynamic(hass, entry, async_add_entities, "devices", RFLight, lambda r: r["kind"] == "light")
