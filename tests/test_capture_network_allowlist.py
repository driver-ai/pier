from pathlib import Path

import pytest

from pier.agents.installed.claude_code import ClaudeCode
from pier.models.task.config import MCPServerConfig


def test_network_allowlist_includes_mcp_hosts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """Under capture, a driver-condition agent reaches its MCP host."""
    monkeypatch.setenv("PIER_CAPTURE_STRACE", "1")
    server = MCPServerConfig(
        name="driver",
        transport="streamable-http",
        url="https://mcp.driverai.com/v1/sse",
    )
    agent = ClaudeCode(logs_dir=tmp_path, mcp_servers=[server])

    allowlist = agent.network_allowlist()
    # NetworkAllowlist normalizes domains to lowercase.
    assert "mcp.driverai.com" in allowlist.domains


def test_network_allowlist_mcp_hosts_gated_on_capture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """With capture OFF, an MCP-configured agent does NOT widen the allowlist.

    This is the DEC-030 byte-identical guarantee for MCP-configured runs (the
    case the disabled-identity test could not cover before MCP gating).
    """
    monkeypatch.delenv("PIER_CAPTURE_STRACE", raising=False)
    server = MCPServerConfig(
        name="driver",
        transport="streamable-http",
        url="https://mcp.driverai.com/v1/sse",
    )
    with_mcp = ClaudeCode(logs_dir=tmp_path, mcp_servers=[server]).network_allowlist()
    baseline = ClaudeCode(logs_dir=tmp_path).network_allowlist()

    assert with_mcp.domains == baseline.domains
    assert "mcp.driverai.com" not in with_mcp.domains


def test_network_allowlist_unchanged_without_mcp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """The explore condition (no MCP) gets the exact pre-change baseline."""
    monkeypatch.setenv("PIER_CAPTURE_STRACE", "1")
    baseline = ClaudeCode(logs_dir=tmp_path).network_allowlist()
    no_mcp = ClaudeCode(logs_dir=tmp_path, mcp_servers=[]).network_allowlist()

    assert no_mcp.domains == baseline.domains
    # No MCP hosts leaked into the baseline.
    assert "mcp.driverai.com" not in no_mcp.domains
