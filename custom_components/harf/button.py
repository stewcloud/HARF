from homeassistant.components.button import ButtonEntity
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo

from .const import CHANGED, DOMAIN
from .entity import HARFEntity


class CommandButton(HARFEntity, ButtonEntity):
    async def async_press(self):
        await self.manager.send_command(self.key)


class DeviceCommandButton(CommandButton):
    """An extra learned command grouped under its assigned HARF device."""

    def __init__(self, manager, device_id, command_id):
        super().__init__(manager, "commands", command_id)
        self.device_id = device_id
        self._attr_unique_id = f"device_action:{device_id}:{command_id}"
        self._stage_predicate = lambda record: True

    @property
    def record(self):
        device = self.manager.library["devices"].get(self.device_id, {})
        return super().record if self.key in device.get("actions", []) else None

    @property
    def device_info(self):
        device = self.manager.library["devices"].get(self.device_id, {})
        return DeviceInfo(
            identifiers={(DOMAIN, f"devices_{self.device_id}")},
            name=device.get("name", self.device_id),
            manufacturer="HARF",
            model="Learned RF control",
        )

    async def async_press(self):
        if self.record is None:
            raise HomeAssistantError("This command is no longer assigned to the device")
        await super().async_press()


async def async_setup_entry(hass, entry, async_add_entities):
    manager = hass.data[DOMAIN]
    tracked = set()

    @callback
    def refresh_actions():
        selected = {
            (device_id, command_id)
            for device_id, record in manager.library["devices"].items()
            for command_id in record.get("actions", [])
        }
        added = selected - tracked
        if added:
            async_add_entities([DeviceCommandButton(manager, *pair) for pair in sorted(added)])
        tracked.intersection_update(selected)
        tracked.update(added)

    refresh_actions()
    entry.async_on_unload(async_dispatcher_connect(hass, CHANGED, refresh_actions))
