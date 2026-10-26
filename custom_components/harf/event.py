from homeassistant.components.event import EventEntity
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import RECEIVED
from .entity import HARFEntity, setup_dynamic


class RFEvent(HARFEntity, EventEntity):
    _attr_event_types = ["received"]

    @property
    def unique_id(self):
        return "receive_" + self.key

    @property
    def name(self):
        return super().name + " received"

    @property
    def available(self):
        return bool(self.record and self.record["trigger"])

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(async_dispatcher_connect(self.hass, RECEIVED, self.received))

    @callback
    def received(self, data):
        if data["command_id"] == self.key and self.record and self.record["trigger"]:
            self._trigger_event("received", {"node": data["node"], "command_id": self.key})
            self.async_write_ha_state()


async def async_setup_entry(hass, entry, async_add_entities):
    setup_dynamic(hass, entry, async_add_entities, "commands", RFEvent, lambda r: r["trigger"])
