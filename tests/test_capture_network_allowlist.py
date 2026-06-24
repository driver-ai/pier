from pathlib import Path

from pier.agents.installed.claude_code import ClaudeCode, _mcp_url_host
from pier.models.task.config import MCPServerConfig


def test_mcp_url_host_pure_helper():
    """The host-parse helper is a pure function: URL -> host (or None)."""
    assert _mcp_url_host("https://mcp.driverai.com/v1/sse") == "mcp.driverai.com"
    assert _mcp_url_host("https://user:pass@mcp.driverai.com:8443/x") == "mcp.driverai.com"
    # A bare host (no scheme) is accepted, matching the ANTHROPIC_BASE_URL path.
    assert _mcp_url_host("mcp.driverai.com") == "mcp.driverai.com"
    # Defensive: entries without a parseable host return None.
    assert _mcp_url_host(None) is None
    assert _mcp_url_host("") is None
    # A URL with a scheme but no authority has no host.
    assert _mcp_url_host("file:///tmp/socket") is None


def test_network_allowlist_includes_mcp_hosts(tmp_path: Path):
    """A driver-condition agent with an MCP server reaches that MCP host."""
    server = MCPServerConfig(
        name="driver",
        transport="streamable-http",
        url="https://mcp.driverai.com/v1/sse",
    )
    agent = ClaudeCode(logs_dir=tmp_path, mcp_servers=[server])

    allowlist = agent.network_allowlist()
    # NetworkAllowlist normalizes domains to lowercase.
    assert "mcp.driverai.com" in allowlist.domains


def test_network_allowlist_unchanged_without_mcp(tmp_path: Path):
    """The explore condition (no MCP) gets the exact pre-change baseline."""
    baseline = ClaudeCode(logs_dir=tmp_path).network_allowlist()
    no_mcp = ClaudeCode(logs_dir=tmp_path, mcp_servers=[]).network_allowlist()

    assert no_mcp.domains == baseline.domains
    # No MCP hosts leaked into the baseline.
    assert "mcp.driverai.com" not in no_mcp.domains
