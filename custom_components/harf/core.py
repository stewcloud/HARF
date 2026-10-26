"""Hardware-independent HARF models, validation and group dispatch."""

from __future__ import annotations

import asyncio
import math
import re
import time
from collections import deque
from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Awaitable, Callable
from uuid import uuid4

VERSION = 1
MAX_COMMANDS = 1000
MAX_TIMINGS = 1024
MAX_GROUP_NODES = 32
ID = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
ENTITY = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")


def identifier(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError("IDs must be 1–64 letters, digits, underscores or hyphens")
    return value


def number(value, low, high):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not low <= value <= high
    ):
        raise ValueError(f"Number must be between {low} and {high}")
    return value


def text(value, limit=100):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"Text must be 1–{limit} characters")
    return value.strip()


def flag(value):
    if not isinstance(value, bool):
        raise ValueError("Expected true or false")
    return value


def entity(value, domain=None, optional=False):
    if optional and not value:
        return ""
    if (
        not isinstance(value, str)
        or not ENTITY.fullmatch(value)
        or (domain and not value.startswith(domain + "."))
    ):
        raise ValueError("Invalid entity/action ID")
    return value


@dataclass(frozen=True)
class Signal:
    timings: tuple[int, ...]
    frequency: int = 433920000
    repeats: int = 3  # Total sends, including the first.
    gap_ms: int = 15

    @classmethod
    def parse(cls, data):
        values = data.get("timings")
        if isinstance(values, str):
            if len(values) > 16000:
                raise ValueError("Capture is too large")
            try:
                values = [int(v) for v in values.split(",")]
            except ValueError as err:
                raise ValueError("Expected signed pulse timings") from err
        if not isinstance(values, (list, tuple)) or not 6 <= len(values) <= MAX_TIMINGS:
            raise ValueError("Expected 6–1024 signed pulse timings")
        for i, v in enumerate(values):
            if type(v) is not int or not 50 <= abs(v) <= 100000:
                raise ValueError("Pulse durations must be integer microseconds, 50–100000")
            if (v > 0) != (i % 2 == 0):
                raise ValueError("Timings must alternate positive pulse / negative space")
        if sum(abs(v) for v in values) > 500000:
            raise ValueError("One frame must be at most 500 ms")
        frequency = int(number(data.get("frequency", 433920000), 433050000, 434790000))
        repeats = data.get("repeats", 3)
        gap = data.get("gap_ms", 15)
        if type(repeats) is not int or type(gap) is not int:
            raise ValueError("Repeat count and gap must be integers")
        number(repeats, 1, 10)
        number(gap, 0, 1000)
        return cls(tuple(values), frequency, repeats, gap)

    def json(self):
        return {**asdict(self), "timings": list(self.timings)}

    @property
    def airtime(self):
        return (sum(abs(v) for v in self.timings) / 1e6 + self.gap_ms / 1000) * self.repeats

    def matches(self, other):
        if abs(self.frequency - other.frequency) > 10000 or len(self.timings) != len(other.timings):
            return False
        # Ignore variable trailing idle gap; compare pulses with bounded jitter.
        return all(
            a * b > 0 and abs(a - b) <= max(100, abs(a) * 0.20)
            for a, b in zip(self.timings[:-1], other.timings[:-1])
        )


def payload_hex(value):
    if not isinstance(value, str):
        raise ValueError("Payload must be hex text")
    try:
        data = bytes.fromhex(value)
    except ValueError as err:
        raise ValueError("Invalid hex payload") from err
    if not 1 <= len(data) <= 24:
        raise ValueError("Payload must contain 1–24 bytes, excluding manufacturer ID")
    return data.hex().upper()


def empty_library():
    return {"version": VERSION, "nodes": {}, "groups": {}, "commands": {}, "devices": {}, "effects": {}}


def validate_library(raw):
    if not isinstance(raw, dict) or raw.get("version") != VERSION:
        raise ValueError("Unsupported library version")
    result = empty_library()
    for bucket in result:
        if bucket == "version":
            continue
        data = raw.get(bucket, {})
        if not isinstance(data, dict) or len(data) > MAX_COMMANDS:
            raise ValueError("Invalid or oversized library section")
        for key, record in data.items():
            identifier(key)
            if not isinstance(record, dict):
                raise ValueError("Invalid record")
            r = {"name": text(record.get("name"))}
            if bucket == "nodes":
                r.update(
                    tx=entity(record.get("tx", ""), "radio_frequency", True),
                    rx=identifier(record.get("rx", key)),
                    magic_action=entity(record.get("magic_action", ""), "esphome", True),
                    enabled=flag(record.get("enabled", True)),
                    rf_enabled=flag(record.get("rf_enabled", True)),
                    magic_enabled=flag(record.get("magic_enabled", False)),
                )
            elif bucket == "groups":
                kind = record.get("kind", "rf")
                nodes = record.get("nodes", [])
                if (
                    kind not in ("rf", "magicband")
                    or not isinstance(nodes, list)
                    or not 1 <= len(nodes) <= MAX_GROUP_NODES
                ):
                    raise ValueError("Choose RF or MagicBand and 1–32 nodes")
                r.update(kind=kind, nodes=list(dict.fromkeys(identifier(n) for n in nodes)))
            elif bucket == "commands":
                r.update(
                    signal=Signal.parse(record.get("signal", {})).json(),
                    group=identifier(record.get("group")),
                    trigger=flag(record.get("trigger", False)),
                    repeat_sensitive=flag(record.get("repeat_sensitive", False)),
                )
            elif bucket == "devices":
                if record.get("kind") not in ("switch", "light"):
                    raise ValueError("Device kind must be switch or light")
                r.update(
                    kind=record["kind"], on=identifier(record.get("on")), off=identifier(record.get("off"))
                )
            elif bucket == "effects":
                r.update(payload=payload_hex(record.get("payload")), wake=flag(record.get("wake", True)))
            result[bucket][key] = r
    for group in result["groups"].values():
        if any(n not in result["nodes"] for n in group["nodes"]):
            raise ValueError("Group references an unknown node")
    for command in result["commands"].values():
        if result["groups"].get(command["group"], {}).get("kind") != "rf":
            raise ValueError("Command needs an RF group")
    for device in result["devices"].values():
        if device["on"] == device["off"] or any(device[a] not in result["commands"] for a in ("on", "off")):
            raise ValueError("Device needs distinct saved On and Off commands")
    return result


class CaptureFilter:
    """Bounded duplicate cache and own-transmission echo suppression."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.recent = deque(maxlen=128)
        self.echoes = deque(maxlen=64)

    def guard(self, signal, duration):
        self.echoes.append((self.clock() + duration + 0.75, signal))

    def accept(self, signal):
        now = self.clock()
        while self.echoes and self.echoes[0][0] < now:
            self.echoes.popleft()
        if any(until >= now and signal.matches(old) for until, old in self.echoes):
            return False
        if any(now - t < 0.35 and signal.matches(old) for t, old in self.recent):
            return False
        self.recent.append((now, signal))
        return True


class Dispatcher:
    """Concurrent group dispatch with shared per-physical-radio serialization."""

    def __init__(self, send: Callable[..., Awaitable], online: Callable, timeout=30):
        self.send, self.online, self.timeout = send, online, timeout
        self.locks = {}
        self.jobs = set()

    async def dispatch(self, nodes, kind, body, mode="concurrent", spacing_ms=100):
        if mode not in ("concurrent", "staggered"):
            raise ValueError("Unknown dispatch mode")
        number(spacing_ms, 0, 2000)
        results = {}
        token = uuid4().hex

        async def one(index, node):
            nid, record = node
            if not record["enabled"] or not record["rf_enabled" if kind == "rf" else "magic_enabled"]:
                results[nid] = {"status": "disabled"}
                return
            target = record["tx" if kind == "rf" else "magic_action"]
            if not target or not self.online(kind, target):
                results[nid] = {"status": "offline"}
                return
            if mode == "staggered":
                await asyncio.sleep(index * spacing_ms / 1000)
            # Key by actual target, not alias: duplicate aliases cannot overlap.
            lock = self.locks.setdefault((kind, target), asyncio.Lock())
            try:
                async with asyncio.timeout(self.timeout):
                    async with lock:
                        await self.send(kind, target, deepcopy(body))
                results[nid] = {"status": "submitted"}  # Never claims fixture acknowledgement.
            except Exception as err:
                results[nid] = {"status": "failed", "error": str(err)[:200]}

        # One physical transmitter per request, even if aliased in the registry.
        unique, seen = [], set()
        for n in nodes:
            target = n[1]["tx" if kind == "rf" else "magic_action"]
            if not n[1]["enabled"] or not n[1]["rf_enabled" if kind == "rf" else "magic_enabled"]:
                results[n[0]] = {"status": "disabled"}
            elif target and target in seen:
                results[n[0]] = {"status": "duplicate_target"}
            else:
                seen.add(target)
                unique.append(n)
        tasks = [asyncio.create_task(one(i, n)) for i, n in enumerate(unique)]
        self.jobs.update(tasks)
        try:
            await asyncio.gather(*tasks)
        finally:
            self.jobs.difference_update(tasks)
        return {"request_id": token, "nodes": results}

    async def close(self):
        tasks = list(self.jobs)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
