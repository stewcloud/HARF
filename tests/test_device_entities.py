"""Exercise actual entity adapter methods with a small HA transport/lifecycle harness."""
import ast
from enum import IntFlag
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from rf_core import color_rgb, nearest_color

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
        'ColorMode': SimpleNamespace(ONOFF='onoff', RGB='rgb'),
        'ATTR_RGB_COLOR': 'rgb_color', 'ATTR_BRIGHTNESS': 'brightness',
        'color_rgb': color_rgb, 'nearest_color': nearest_color, 'HomeAssistantError': RuntimeError,
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
    assert len(buttons) == len(added) == 1
    manager.library['devices']['puck']['actions'].append('smooth')
    for refresh in listeners:
        refresh()
    assert len([b for b in added if isinstance(b, ns['DeviceCommandButton'])]) == 2
    for refresh in listeners:
        refresh()
    assert len([b for b in added if isinstance(b, ns['DeviceCommandButton'])]) == 2


async def test_color_request_transmits_nearest_mapped_color_and_reports_actual_swatch(adapter):
    ns, manager, _, _ = adapter
    manager.library['commands']['red'] = {'name': 'Red', 'group': 'room', 'color': '#ff0000'}
    manager.library['commands']['blue'] = {'name': 'Blue', 'group': 'room', 'color': '#0000ff'}
    manager.library['devices']['puck']['colors'] = ['red', 'blue']
    light = ns['RFLight'](manager, 'devices', 'puck')
    assert light.supported_color_modes == {'rgb'} and light.color_mode == 'rgb'
    await light.async_turn_on(rgb_color=(250, 10, 5))
    manager.send_command.assert_awaited_once_with('red')
    assert light.rgb_color == (255, 0, 0) and light._attr_is_on is True
    assert light.effect is None
    await light.async_turn_on(effect='Smooth')
    assert light.rgb_color is None and light.effect == 'Smooth'
    manager.library['devices']['puck']['colors'] = []
    assert light.color_mode == 'onoff' and light.supported_color_modes == {'onoff'}


async def test_unmapped_color_or_brightness_does_not_transmit_or_change_assumed_state(adapter):
    ns, manager, _, _ = adapter
    light = ns['RFLight'](manager, 'devices', 'puck')
    with pytest.raises(RuntimeError, match='No captured colors'):
        await light.async_turn_on(rgb_color=(255, 0, 0))
    with pytest.raises(RuntimeError, match='brightness mappings'):
        await light.async_turn_on(brightness=100)
    manager.send_command.assert_not_awaited()
    assert light._attr_is_on is None


async def test_failed_color_transmission_preserves_previous_assumed_color(adapter):
    ns, manager, _, _ = adapter
    manager.library['commands']['red'] = {'color': '#ff0000', 'name': 'Red', 'group': 'room'}
    manager.library['devices']['puck']['colors'] = ['red']
    light = ns['RFLight'](manager, 'devices', 'puck')
    manager.send_command.side_effect = RuntimeError('Transport failed')
    with pytest.raises(RuntimeError, match='Transport failed'):
        await light.async_turn_on(rgb_color=(255, 0, 0))
    assert light.rgb_color is None and light._attr_is_on is None


def test_upgrade_removes_only_old_automatic_command_entities_and_empty_command_devices(adapter):
    ns, manager, _, _ = adapter
    def entity(eid, domain, uid, device, platform='harf', config='entry'):
        return SimpleNamespace(entity_id=eid, domain=domain, unique_id=uid, device_id=device,
                               platform=platform, config_entry_id=config)
    entries = {
        e.entity_id: e for e in [
            entity('button.on', 'button', 'commands_on', 'old'),
            entity('event.on', 'event', 'receive_on', 'old'),
            entity('button.disabled', 'button', 'commands_deleted', 'orphan'),
            entity('light.puck', 'light', 'devices_puck', 'puck'),
            entity('button.flash', 'button', 'device_action:puck:flash', 'puck'),
            entity('sensor.foreign', 'sensor', 'foreign', 'shared', platform='other', config='other'),
            entity('button.other', 'button', 'commands_on', 'other', config='other'),
        ]
    }
    er = SimpleNamespace(
        async_get=lambda hass: er,
        async_entries_for_config_entry=lambda registry, entry: [e for e in entries.values() if e.config_entry_id == entry],
        async_entries_for_device=lambda registry, device, include_disabled_entities: [e for e in entries.values() if e.device_id == device],
        async_remove=lambda eid: entries.pop(eid),
    )
    devices = {key: SimpleNamespace(id=key, identifiers={('harf', identifier)}) for key, identifier in
               [('old', 'commands_on'), ('orphan', 'commands_deleted'), ('puck', 'devices_puck'), ('shared', 'commands_shared')]}
    dr = SimpleNamespace(
        async_get=lambda hass: dr,
        async_entries_for_config_entry=lambda registry, entry: list(devices.values()),
        async_remove_device=lambda key: devices.pop(key),
    )
    ns.update(er=er, dr=dr)
    ns['cleanup_legacy_command_entities'](SimpleNamespace(), SimpleNamespace(entry_id='entry'))
    assert set(entries) == {'light.puck', 'button.flash', 'sensor.foreign', 'button.other'}
    assert set(devices) == {'puck', 'shared'}
    assert 'on' in manager.library['commands']  # Library data is untouched.
