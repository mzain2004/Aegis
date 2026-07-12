from __future__ import annotations

from app.rpc_parser import MCPRequestInfo, OperationType, parse_mcp_request


def test_parse_tools_list_returns_unknown() -> None:
    info = parse_mcp_request(b'{"method":"tools/list"}')

    assert isinstance(info, MCPRequestInfo)
    assert info.operation is OperationType.UNKNOWN
    assert info.method == "tools/list"
    assert info.tool_name is None


def test_parse_read_only_tool_returns_read_only() -> None:
    info = parse_mcp_request(
        b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"kubectl_get"}}'
    )

    assert info.operation is OperationType.READ_ONLY
    assert info.method == "tools/call"
    assert info.tool_name == "kubectl_get"


def test_parse_mutating_tool_returns_mutating() -> None:
    info = parse_mcp_request(
        b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"kubectl_delete"}}'
    )

    assert info.operation is OperationType.MUTATING
    assert info.tool_name == "kubectl_delete"


def test_parse_invalid_json_returns_unknown() -> None:
    info = parse_mcp_request(b"random bytes")

    assert info.operation is OperationType.UNKNOWN
    assert info.method is None
    assert info.tool_name is None


def test_parse_unknown_tool_returns_unknown() -> None:
    info = parse_mcp_request(b'{"name":"kubectl_magic"}')

    assert info.operation is OperationType.UNKNOWN
    assert info.tool_name is None
