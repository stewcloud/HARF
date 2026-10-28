"""Exercise actual entity adapter methods with a small HA transport/lifecycle harness."""
import ast
from enum import IntFlag
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

ROOT = Path(__file__).parents[1] / 'custom_components/harf'


class Features(IntFlag):
    EFFECT = 4


class Entity:
    def async_write_ha_state(self):
        self.writes = getattr(self, 'writes', 0) + 1

    def async_on_remove(self, callback):
        pass

    async def async_remove(self):
        self.removed = True


class LightEntity(Entity):
    pass


class ButtonEntity(Entity):
    pass


def load_adapter(filename, namespace):
    tree = ast.parse((ROOT / filename).read_text())
    tree.body = [item for item in tree.body if not isinstance(item, (ast.Import, ast.ImportFrom))]
    exec(compile(tree, str(ROOT / filename), 'exec'), namespace)


@pytest.fixture
def adapter():
    listeners = []
    registry = SimpleNamespace(async_get=lambda _: True, async_remove=Mock())
    namespace = {
        'Entity': Entity, 'LightEntity': LightEntity, 'ButtonEntity': ButtonEntity,
        'LightEntityFeature': Features, 'ATTR_EFFECT': 'effect',
        'ColorMode': SimpleNamespace(ONOFF='onoff'), 'HomeAssistantError': RuntimeError,
        'DeviceInfo': dict, 'DOMAIN': 'harf', 'CHANGED': 'harf_changed',
        'callback': lambda fn: fn,
        'async_dispatcher_connect': lambda hass, signal, fn: listeners.append(fn),
        'er': SimpleNamespace(async_get=lambda hass: registry),
    }
    load_adapter('entity.py', namespace)
    load_adapter('light.py', namespace)
    load_adapter('button.py', namespace)
    manager = SimpleNamespace(
        library={
            'devices': {'puck': {'name': 'Puck Lights', 'kind': 'light', 'on': 'on', 'off': 'off',
                                 'effects': ['smooth', 'flash'], 'actions': ['flash']}},
            'commands': {key: {'name': key.title(), 'group': 'room'} for key in ('on', 'off', 'smooth', 'flash')},
            'groups': {'room': {'nodes': ['one']}},
            'nodes': {'one': {'enabled': True, 'rf_enabled': True, 'tx': 'radio_frequency.one'}},
        },
        send_command=AsyncMock(), online=lambda *args: True,
    )
    return namespace, manager, listeners, registry


async def test_light_effect_sends_only_mapped_command_and_tracks_assumed_effect(adapter):
    ns, manager, _, _ = adapter
    light = ns['RFLight'](manager, 'devices', 'puck')
    assert light.effect_list == ['Smooth', 'Flash']
    assert light.supported_features == Features.EFFECT
    await light.async_turn_on(effect='Smooth')
    manager.send_command.assert_awaited_once_with('smooth')
    assert light.effect == 'Smooth' and light._attr_is_on is True
    await light.async_turn_off()
    assert light.effect is None and light._attr_is_on is False
    await light.async_turn_on()
    assert manager.send_command.await_args.args == ('on',)
    assert light.effect is None


async def test_light_rejects_unknown_effect_without_transmitting(adapter):
    ns, manager, _, _ = adapter
    light = ns['RFLight'](manager, 'devices', 'puck')
    with pytest.raises(RuntimeError, match='Unknown RF light effect'):
        await light.async_turn_on(effect='Missing')
    manager.send_command.assert_not_awaited()


async def test_live_effect_remap_and_plain_legacy_light(adapter):
    ns, manager, _, _ = adapter
    light = ns['RFLight'](manager, 'devices', 'puck')
    await light.async_turn_on(effect='Smooth')
    manager.library['devices']['puck'].pop('effects')
    assert light.effect_list == [] and light.effect is None
    assert light.supported_features == 0
    await light.async_turn_on()
    assert manager.send_command.await_args.args == ('on',)


async def test_extra_button_groups_with_parent_and_becomes_invalid_when_unmapped(adapter):
    ns, manager, _, registry = adapter
    button = ns['DeviceCommandButton'](manager, 'puck', 'flash')
    light = ns['RFLight'](manager, 'devices', 'puck')
    assert button.device_info['identifiers'] == light.device_info['identifiers']
    assert button.device_info['name'] == 'Puck Lights'
    assert button.name == 'Flash' and button.available
    await button.async_press()
    manager.send_command.assert_awaited_once_with('flash')
    manager.library['devices']['puck']['actions'] = []
    assert button.record is None and not button.available
    with pytest.raises(RuntimeError, match='no longer assigned'):
        await button.async_press()
    button.hass = SimpleNamespace()
    button.entity_id = 'button.puck_flash'
    await button.remove_record()
    assert button.removed
    registry.async_remove.assert_called_once_with('button.puck_flash')


async def test_action_buttons_are_added_on_save_without_duplicates(adapter):
    ns, manager, listeners, _ = adapter
    added = []
    hass = SimpleNamespace(data={'harf': manager})
    entry = SimpleNamespace(async_on_unload=lambda fn: None)
    await ns['async_setup_entry'](hass, entry, added.extend)
    buttons = [b for b in added if isinstance(b, ns['DeviceCommandButton'])]
    assert len(buttons) == 1
    manager.library['devices']['puck']['actions'].append('smooth')
    for refresh in listeners:
        refresh()
    assert len([b for b in added if isinstance(b, ns['DeviceCommandButton'])]) == 2
    for refresh in listeners:
        refresh()
    assert len([b for b in added if isinstance(b, ns['DeviceCommandButton'])]) == 2
