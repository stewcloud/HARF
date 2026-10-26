"""Shared dynamic entities backed by the saved library."""

from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, Entity

from .const import CHANGED, DOMAIN


class HARFEntity(Entity):
    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, manager, section, key):
        self.manager, self.section, self.key = manager, section, key
        self._attr_unique_id = f"{section}_{key}"

    @property
    def record(self):
        return self.manager.library[self.section].get(self.key)

    @property
    def name(self):
        return self.record["name"] if self.record else self.key

    @property
    def device_info(self):
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.section}_{self.key}")},
            name=self.name,
            manufacturer="HARF",
            model="Learned RF control",
        )

    @property
    def available(self):
        r = self.record
        if not r:
            return False
        command = r if self.section == "commands" else self.manager.library["commands"].get(r.get("on"))
        if not command:
            return False
        group = self.manager.library["groups"].get(command["group"], {})
        return any(
            n["enabled"] and n["rf_enabled"] and n["tx"] and self.manager.online("rf", n["tx"])
            for key in group.get("nodes", [])
            if (n := self.manager.library["nodes"].get(key))
        )

    async def async_added_to_hass(self):
        self.async_on_remove(async_dispatcher_connect(self.hass, CHANGED, self.refresh))

    @callback
    def refresh(self):
        if self.record is None or not self._stage_predicate(self.record):
            self.hass.async_create_task(self.remove_record())
        else:
            self.async_write_ha_state()

    async def remove_record(self):
        await self.async_remove()
        registry = er.async_get(self.hass)
        if registry.async_get(self.entity_id):
            registry.async_remove(self.entity_id)


def setup_dynamic(hass, entry, add_entities, section, factory, predicate=lambda r: True):
    manager = hass.data[DOMAIN]
    tracked = set()

    @callback
    def refresh():
        selected = {key for key, r in manager.library[section].items() if predicate(r)}
        added = selected - tracked
        if added:
            entities = [factory(manager, section, key) for key in added]
            for entity in entities:
                entity._stage_predicate = predicate
            add_entities(entities)
        tracked.intersection_update(selected)
        tracked.update(added)

    refresh()
    entry.async_on_unload(async_dispatcher_connect(hass, CHANGED, refresh))
