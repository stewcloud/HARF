import asyncio
from copy import deepcopy

import pytest
from rf_core import CaptureFilter, Dispatcher, Signal, empty_library, payload_hex, validate_library

TIMINGS = [350, -1050, 350, -350, 1050, -10000]


def signal(**changes):
    return Signal.parse({"timings": TIMINGS, **changes})


def node(target="radio_frequency.one", **changes):
    return {
        "name": "Node",
        "enabled": True,
        "rf_enabled": True,
        "magic_enabled": True,
        "tx": target,
        "rx": "node-1",
        "magic_action": "esphome.one_magicband",
        **changes,
    }


def library():
    data = empty_library()
    data["nodes"]["one"] = node()
    data["groups"]["room"] = {"name": "Room", "kind": "rf", "nodes": ["one"]}
    data["commands"]["on"] = {"name": "On", "group": "room", "signal": signal().json()}
    return data


@pytest.mark.parametrize(
    "changes",
    [
        {"timings": [350, 350] * 3},
        {"timings": [True, -350] * 3},
        {"timings": [0, -350] * 3},
        {"timings": [350, -350] * 600},
        {"frequency": 915000000},
        {"frequency": float("nan")},
        {"repeats": True},
        {"repeats": 11},
        {"gap_ms": 1.5},
        {"timings": [100000, -100000] * 3},
    ],
)
def test_reject_malformed_signal(changes):
    with pytest.raises(ValueError):
        signal(**changes)


def test_matches_jitter_but_not_distinct_command():
    assert signal().matches(Signal.parse({"timings": [370, -1000, 345, -340, 1100, -9000]}))
    assert not signal().matches(Signal.parse({"timings": [350, -350, 350, -1050, 1050, -10000]}))


def test_rx_dedup_and_tx_echo_guard_expire():
    now = [10.0]
    filt = CaptureFilter(lambda: now[0])
    assert filt.accept(signal())
    assert not filt.accept(signal())
    now[0] += 0.4
    assert filt.accept(signal())
    filt.guard(signal(), 2)
    now[0] += 1
    assert not filt.accept(signal())
    now[0] += 2
    assert filt.accept(signal())
    for i in range(300):
        now[0] += 1
        filt.accept(signal())
    assert len(filt.recent) == 128


def test_atomic_import_reference_validation():
    original = library()
    assert validate_library(original)["commands"]["on"]["trigger"] is False
    candidate = deepcopy(original)
    del candidate["nodes"]["one"]
    with pytest.raises(ValueError):
        validate_library(candidate)
    assert "one" in original["nodes"]


def test_toggle_cannot_be_mapped_to_on_and_off():
    data = library()
    data["devices"]["lamp"] = {"name": "Lamp", "kind": "light", "on": "on", "off": "on"}
    with pytest.raises(ValueError):
        validate_library(data)


@pytest.mark.parametrize("bad", ["", "GG", "1", "FF" * 25])
def test_ble_payload_bounds(bad):
    with pytest.raises(ValueError):
        payload_hex(bad)


async def test_group_dispatch_really_starts_concurrently():
    entered = []
    gate = asyncio.Event()

    async def send(kind, target, body):
        entered.append(target)
        if len(entered) == 2:
            gate.set()
        await asyncio.wait_for(gate.wait(), 0.2)

    dispatcher = Dispatcher(send, lambda *args: True)
    result = await dispatcher.dispatch([("a", node()), ("b", node("radio_frequency.two"))], "rf", {})
    assert all(r["status"] == "submitted" for r in result["nodes"].values())
    assert len(entered) == 2


async def test_same_physical_radio_serializes_overlapping_requests():
    count = maximum = 0

    async def send(*args):
        nonlocal count, maximum
        count += 1
        maximum = max(maximum, count)
        await asyncio.sleep(0.01)
        count -= 1

    dispatcher = Dispatcher(send, lambda *args: True)
    await asyncio.gather(*[dispatcher.dispatch([("one", node())], "rf", {}) for _ in range(3)])
    assert maximum == 1


async def test_offline_and_failed_nodes_do_not_cancel_others():
    async def send(kind, target, body):
        if target.endswith("bad"):
            raise RuntimeError("failed")

    dispatcher = Dispatcher(send, lambda kind, target: not target.endswith("offline"))
    result = await dispatcher.dispatch(
        [
            ("good", node()),
            ("bad", node("radio_frequency.bad")),
            ("offline", node("radio_frequency.offline")),
            ("disabled", node(enabled=False)),
        ],
        "rf",
        {},
    )
    assert {k: v["status"] for k, v in result["nodes"].items()} == {
        "good": "submitted",
        "bad": "failed",
        "offline": "offline",
        "disabled": "disabled",
    }


async def test_duplicate_alias_only_transmits_once():
    calls = []

    async def send(*args):
        calls.append(args)

    dispatcher = Dispatcher(send, lambda *args: True)
    result = await dispatcher.dispatch([("a", node()), ("b", node())], "rf", {})
    assert len(calls) == 1
    assert result["nodes"]["b"]["status"] == "duplicate_target"


async def test_unload_cancels_pending_transmissions():
    entered = asyncio.Event()

    async def send(*args):
        entered.set()
        await asyncio.Event().wait()

    dispatcher = Dispatcher(send, lambda *args: True)
    task = asyncio.create_task(dispatcher.dispatch([("a", node())], "rf", {}))
    await entered.wait()
    await dispatcher.close()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not dispatcher.jobs


def mapped_library():
    data = library()
    for key in ('off', 'smooth', 'flash', 'fade'):
        data['commands'][key] = {'name': key.title(), 'group': 'room', 'signal': signal().json()}
    data['devices']['puck'] = {'name': 'Puck Lights', 'kind': 'light', 'on': 'on', 'off': 'off'}
    return data


def test_old_device_records_gain_empty_optional_mappings():
    device = validate_library(mapped_library())['devices']['puck']
    assert device['effects'] == device['actions'] == []


def test_device_effects_and_actions_round_trip_and_deduplicate():
    data = mapped_library()
    data['devices']['puck'].update(effects=['smooth', 'flash', 'fade', 'smooth'], actions=['flash'])
    saved = validate_library(data)
    assert saved['devices']['puck']['effects'] == ['smooth', 'flash', 'fade']
    assert saved['devices']['puck']['actions'] == ['flash']
    assert validate_library(saved) == saved


@pytest.mark.parametrize('field', ['effects', 'actions'])
@pytest.mark.parametrize('bad', ['smooth', None, ['missing'], ['smooth'] * 129])
def test_reject_invalid_or_dangling_device_command_mappings(field, bad):
    data = mapped_library()
    data['devices']['puck'][field] = bad
    with pytest.raises(ValueError):
        validate_library(data)


def test_effect_command_names_must_be_distinct_within_a_light():
    data = mapped_library()
    data['commands']['flash']['name'] = 'Smooth'
    data['devices']['puck']['effects'] = ['smooth', 'flash']
    with pytest.raises(ValueError, match='distinct name'):
        validate_library(data)


def test_switch_can_have_action_buttons_but_cannot_have_light_effects():
    data = mapped_library()
    data['devices']['puck'].update(kind='switch', actions=['flash'])
    assert validate_library(data)['devices']['puck']['actions'] == ['flash']
    data['devices']['puck']['effects'] = ['smooth']
    with pytest.raises(ValueError, match='only be assigned to a light'):
        validate_library(data)
