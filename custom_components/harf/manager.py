"""Persistent library and Home Assistant transports."""

import asyncio
import json
import time
from collections import deque
from copy import deepcopy
from uuid import uuid4

from homeassistant.components.radio_frequency import ModulationType, RadioFrequencyCommand, async_send_command
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store

from .const import CHANGED, DOMAIN, RECEIVED
from .core import (
    CaptureFilter,
    Dispatcher,
    Signal,
    empty_library,
    identifier,
    number,
    payload_hex,
    validate_library,
)


class RawCommand(RadioFrequencyCommand):
    def __init__(self, signal):
        super().__init__(frequency=signal.frequency, modulation=ModulationType.OOK, repeat_count=0)
        self.timings = list(signal.timings)

    def get_raw_timings(self):
        return self.timings


class Manager:
    def __init__(self, hass):
        self.hass = hass
        self.store = Store(hass, 1, DOMAIN)
        self.library = empty_library()
        self.capture = None
        self.sniffer = deque(maxlen=50)
        self.history = deque(maxlen=50)
        self.filter = CaptureFilter()
        self.mutation_lock = asyncio.Lock()
        self.dispatcher = Dispatcher(self._send, self.online)
        self.last_receive = {}

    async def load(self):
        saved = await self.store.async_load()
        if saved:
            self.library = validate_library(saved)
        else:
            self.library = empty_library()
            self.library["effects"] = {
                "rainbow": {"name": "Rainbow", "payload": "E100E90C000F0F5D465BF005323748B0", "wake": True},
                "color_cycle": {
                    "name": "Color cycle",
                    "payload": "E100E90C000F0FB1B9B5B1A2307B7DB0",
                    "wake": True,
                },
                "white_blink": {
                    "name": "White blink",
                    "payload": "E100E90C000F0F5D465BF00532374895",
                    "wake": True,
                },
            }
            await self.store.async_save(self.library)

    def changed(self):
        async_dispatcher_send(self.hass, CHANGED)

    async def mutate(self, bucket, key, record=None):
        if bucket not in ("nodes", "groups", "commands", "devices", "effects"):
            raise ValueError("Unknown library section")
        identifier(key)
        async with self.mutation_lock:
            candidate = deepcopy(self.library)
            if record is None:
                candidate[bucket].pop(key, None)
            else:
                candidate[bucket][key] = record
            validated = validate_library(candidate)
            await self.store.async_save(validated)
            self.library = validated
        self.changed()

    async def import_library(self, raw):
        # Bounded replace is atomic and never sends imported commands.
        if len(json.dumps(raw)) > 2_000_000:
            raise ValueError("Import exceeds 2 MB")
        validated = validate_library(raw)
        async with self.mutation_lock:
            await self.store.async_save(validated)
            self.library = validated
        self.changed()

    def online(self, kind, target):
        if kind == "rf":
            state = self.hass.states.get(target)
            return state is not None and state.state != "unavailable"
        domain, action = target.split(".", 1)
        return self.hass.services.has_service(domain, action)

    def group_nodes(self, group_id, kind):
        group = self.library["groups"].get(group_id)
        if not group or group["kind"] != kind:
            raise ValueError(f"Select a {kind} proxy group")
        return [(key, self.library["nodes"][key]) for key in group["nodes"]]

    async def _send(self, kind, target, body):
        if kind == "magicband":
            domain, action = target.split(".", 1)
            await self.hass.services.async_call(domain, action, body, blocking=True)
            return
        signal = Signal.parse(body)
        self.filter.guard(signal, signal.airtime)
        # Explicit per-frame sends preserve requested gaps, and keep native RF compatibility.
        command = RawCommand(signal)
        for index in range(signal.repeats):
            await async_send_command(self.hass, target, command)
            # Native submission returns before RF finishes. Hold the per-node lock for airtime.
            await asyncio.sleep(sum(abs(v) for v in signal.timings) / 1e6 + signal.gap_ms / 1000)

    async def send_command(self, key, group_id=None, mode="concurrent", spacing_ms=100):
        command = self.library["commands"].get(key)
        if not command:
            raise ValueError("Unknown command")
        nodes = self.group_nodes(group_id or command["group"], "rf")
        signal = Signal.parse(command["signal"])
        active = [n for n in nodes if n[1]["enabled"] and n[1]["rf_enabled"]]
        targets = {n[1]["tx"] for n in active if n[1]["tx"]}
        if command["repeat_sensitive"] and (len(targets) > 1 or signal.repeats > 1):
            raise ValueError("Repeat-sensitive command requires one transmitter and one send")
        report = await self.dispatcher.dispatch(nodes, "rf", signal.json(), mode, spacing_ms)
        report.update(command_id=key, time=time.time(), kind="rf")
        self.history.appendleft(report)
        self.changed()
        if not any(n["status"] == "submitted" for n in report["nodes"].values()):
            raise HomeAssistantError("No proxy accepted the command; check HARF history")
        return report

    async def magic(self, group_id, effect_id=None, duration_ms=5000, stop=False):
        nodes = self.group_nodes(group_id, "magicband")
        number(duration_ms, 100, 60000)
        effect = self.library["effects"].get(effect_id) if not stop else None
        if not stop and not effect:
            raise ValueError("Choose a saved MagicBand effect")
        body = {
            "payload": "" if stop else payload_hex(effect["payload"]),
            "duration_ms": int(duration_ms),
            "wake": False if stop else effect["wake"],
            "stop": bool(stop),
        }
        # Stop reaches configured nodes even if their manager enable switch has since been disabled.
        if stop:
            nodes = [(key, {**record, "enabled": True, "magic_enabled": True}) for key, record in nodes]
        report = await self.dispatcher.dispatch(nodes, "magicband", body)
        report.update(time=time.time(), kind="magicband", stop=stop)
        self.history.appendleft(report)
        self.changed()
        return report

    def arm_capture(self, rx, seconds=30):
        identifier(rx)
        if not any(n["rx"] == rx and n["enabled"] for n in self.library["nodes"].values()):
            raise ValueError("Choose a configured, enabled receiver node")
        number(seconds, 5, 60)
        self.capture = {"rx": rx, "until": time.monotonic() + seconds}
        self.changed()

    def received(self, data):
        node = data.get("node")
        if not any(
            n["rx"] == node and n["enabled"] and n["rf_enabled"] for n in self.library["nodes"].values()
        ):
            return
        try:
            signal = Signal.parse(
                {"timings": data.get("timings"), "frequency": int(data.get("frequency", 433920000))}
            )
        except (ValueError, TypeError):
            return
        if not self.filter.accept(signal):
            return
        capture = self.capture
        if capture and capture["until"] <= time.monotonic():
            self.capture = None
        if capture and capture["until"] > time.monotonic() and capture["rx"] == node:
            self.sniffer.appendleft(
                {"id": uuid4().hex, "node": node, "time": time.time(), "signal": signal.json()}
            )
        for key, command in self.library["commands"].items():
            if command["trigger"] and signal.matches(Signal.parse(command["signal"])):
                self.last_receive[key] = time.time()
                event = {"command_id": key, "name": command["name"], "node": node}
                self.hass.bus.async_fire(RECEIVED, event)
                async_dispatcher_send(self.hass, RECEIVED, event)
        self.changed()

    def snapshot(self):
        services = self.hass.services.async_services().get("esphome", {})
        return {
            "library": deepcopy(self.library),
            "sniffer": list(self.sniffer),
            "history": list(self.history),
            "capture": {
                "rx": self.capture["rx"],
                "remaining": max(0, self.capture["until"] - time.monotonic()),
            }
            if self.capture
            else None,
            "rf_transmitters": [s.entity_id for s in self.hass.states.async_all("radio_frequency")],
            "magic_actions": ["esphome." + s for s in services if s.endswith("_magicband")],
            "nodes_online": {
                key: self.online("rf", n["tx"]) if n["tx"] else False
                for key, n in self.library["nodes"].items()
            },
        }
