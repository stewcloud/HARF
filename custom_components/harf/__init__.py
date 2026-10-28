"""HARF: local learned RF command manager and independent BLE groups."""

from pathlib import Path

try:
    import probatio as vol
except ImportError:
    import voluptuous as vol

from homeassistant.components import frontend, panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import CAPTURE_EVENT, DOMAIN, PLATFORMS
from .manager import Manager

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup_entry(hass, entry):
    manager = Manager(hass)
    await manager.load()
    hass.data[DOMAIN] = manager
    if not hass.data.get(DOMAIN + "_registered"):
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    "/harf_static", str(Path(__file__).parent / "frontend"), cache_headers=False
                )
            ]
        )
        websocket_api.async_register_command(hass, ws_request)

        async def handle_service(call):
            current = hass.data.get(DOMAIN)
            if current is None:
                raise HomeAssistantError("HARF is not loaded")
            return await run_action(current, call.service, call.data)

        for action in ("send", "magicband", "stop_magicband"):
            hass.services.async_register(
                DOMAIN,
                action,
                handle_service,
                schema=vol.Schema(
                    {
                        vol.Optional("command_id"): str,
                        vol.Optional("group_id"): str,
                        vol.Optional("effect_id"): str,
                        vol.Optional("mode", default="concurrent"): str,
                        vol.Optional("spacing_ms", default=100): int,
                        vol.Optional("duration_ms", default=5000): int,
                    }
                ),
                supports_response=SupportsResponse.OPTIONAL,
            )
        hass.data[DOMAIN + "_registered"] = True
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path="harf",
        webcomponent_name="harf-panel",
        sidebar_title="HARF",
        sidebar_icon="mdi:radio-tower",
        module_url="/harf_static/panel.js?v=0.1.5",
        require_admin=True,
    )
    entry.async_on_unload(hass.bus.async_listen(CAPTURE_EVENT, lambda event: manager.received(event.data)))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass, entry):
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        manager = hass.data.pop(DOMAIN)
        await manager.dispatcher.close()
        frontend.async_remove_panel(hass, "harf")
        return True
    return False


async def run_action(manager, action, data):
    try:
        if action == "send":
            return await manager.send_command(
                data["command_id"],
                data.get("group_id"),
                data.get("mode", "concurrent"),
                data.get("spacing_ms", 100),
            )
        return await manager.magic(
            data["group_id"], data.get("effect_id"), data.get("duration_ms", 5000), action == "stop_magicband"
        )
    except (ValueError, KeyError) as err:
        raise HomeAssistantError(str(err)) from err


@websocket_api.websocket_command(
    {
        vol.Required("type"): "harf/request",
        vol.Required("op"): str,
        vol.Optional("data", default={}): dict,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_request(hass, connection, msg):
    manager = hass.data.get(DOMAIN)
    if manager is None:
        connection.send_error(msg["id"], "not_loaded", "HARF is not loaded")
        return
    op, data = msg["op"], msg["data"]
    try:
        if op == "snapshot":
            result = manager.snapshot()
        elif op == "save":
            await manager.mutate(data["section"], data["id"], data["record"])
            result = manager.snapshot()
        elif op == "delete":
            await manager.mutate(data["section"], data["id"])
            result = manager.snapshot()
        elif op == "learn":
            manager.arm_capture(data["rx"], data.get("seconds", 30))
            result = manager.snapshot()
        elif op == "stop_learn":
            manager.capture = None
            result = manager.snapshot()
        elif op == "import":
            await manager.import_library(data["library"])
            result = manager.snapshot()
        elif op == "export":
            result = manager.library
        elif op in ("send", "magicband", "stop_magicband"):
            result = await run_action(manager, op, data)
        else:
            raise ValueError("Unknown operation")
        connection.send_result(msg["id"], result)
    except (ValueError, KeyError, TypeError, HomeAssistantError) as err:
        connection.send_error(msg["id"], "harf_error", str(err))
