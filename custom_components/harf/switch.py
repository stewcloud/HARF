from homeassistant.components.switch import SwitchEntity

from .entity import HARFEntity, setup_dynamic


class RFSwitch(HARFEntity, SwitchEntity):
    _attr_assumed_state = True
    _attr_is_on = None

    async def async_turn_on(self, **kwargs):
        await self.manager.send_command(self.record["on"])
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        await self.manager.send_command(self.record["off"])
        self._attr_is_on = False
        self.async_write_ha_state()


async def async_setup_entry(hass, entry, async_add_entities):
    setup_dynamic(hass, entry, async_add_entities, "devices", RFSwitch, lambda r: r["kind"] == "switch")
