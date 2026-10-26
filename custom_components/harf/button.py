from homeassistant.components.button import ButtonEntity

from .entity import HARFEntity, setup_dynamic


class CommandButton(HARFEntity, ButtonEntity):
    async def async_press(self):
        await self.manager.send_command(self.key)


async def async_setup_entry(hass, entry, async_add_entities):
    setup_dynamic(hass, entry, async_add_entities, "commands", CommandButton)
