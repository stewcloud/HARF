"""Exercise the actual sidebar handler without loading an HA installation."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

SOURCE = Path(__file__).parents[1] / "custom_components/harf/__init__.py"


def handler():
    tree = ast.parse(SOURCE.read_text())
    function = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "ws_request")
    decorators = [ast.unparse(d) for d in function.decorator_list]
    assert decorators[-2:] == ["websocket_api.require_admin", "websocket_api.async_response"]
    function.decorator_list = []
    namespace = {"DOMAIN": "harf", "HomeAssistantError": RuntimeError}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace["ws_request"]


async def test_sidebar_initial_snapshot_uses_supported_connection_interface():
    expected = {"library": {"nodes": {}}, "sniffer": []}
    manager = SimpleNamespace(snapshot=lambda: expected)
    # HA ActiveConnection exposes send_result/send_error, no require_admin method.
    connection = SimpleNamespace(send_result=Mock(), send_error=Mock())
    await handler()(SimpleNamespace(data={"harf": manager}), connection,
                    {"id": 1, "op": "snapshot", "data": {}})
    connection.send_result.assert_called_once_with(1, expected)
    connection.send_error.assert_not_called()


async def test_unloaded_integration_returns_clear_error():
    connection = SimpleNamespace(send_result=Mock(), send_error=Mock())
    await handler()(SimpleNamespace(data={}), connection,
                    {"id": 2, "op": "snapshot", "data": {}})
    connection.send_error.assert_called_once_with(2, "not_loaded", "HARF is not loaded")
