"""DEC-030 safety guarantee: with PIER_CAPTURE_STRACE unset, the capture-gated
seams behave byte-identically to their pre-capture form.

Each test deletes the env flag, so the shared ``capture_strace_enabled()`` gate
reads falsy regardless of any kwarg or stale attribute, and asserts the seam
produces the documented pre-change output.

Note: MCP-host allowlisting is no longer capture-gated -- a configured MCP server
widens the allowlist regardless of capture (see test_capture_network_allowlist).
The no-MCP allowlist baseline is still asserted below.
"""

import asyncio
from pathlib import Path
from typing import Any

import pytest

from pier.agents.installed.base import BaseInstalledAgent
from pier.agents.installed.claude_code import ClaudeCode
from pier.environments.docker.docker import DockerEnvironment
from pier.models.task.config import MCPServerConfig


class _RecordingEnvironment:
    """Minimal fake environment that records the command string `_exec` dispatches."""

    def __init__(self) -> None:
        self.recorded_command: str | None = None

    def agent_process_env(self, env: dict[str, str] | None) -> dict[str, str] | None:
        return env

    async def exec(
        self,
        command: str,
        user: str | int | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        timeout_sec: int | None = None,
    ) -> Any:
        self.recorded_command = command
        from pier.environments.base import ExecResult

        return ExecResult(return_code=0, stdout="", stderr="")


class _NoOpInstalledAgent(BaseInstalledAgent):
    """Concrete `BaseInstalledAgent` whose only purpose is to exercise `_exec`."""

    @staticmethod
    def name() -> str:
        return "noop-installed-agent"

    async def run(self, instruction: str, environment: Any, context: Any) -> None:  # pragma: no cover
        pass

    def populate_context_post_run(self, context: Any) -> None:  # pragma: no cover
        pass

    def install_spec(self) -> Any:  # pragma: no cover
        raise NotImplementedError


def test_exec_command_is_plain_pipefail_when_env_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With the env flag unset, `_exec` dispatches the plain pipefail form."""
    monkeypatch.delenv("PIER_CAPTURE_STRACE", raising=False)

    agent = _NoOpInstalledAgent(logs_dir=tmp_path)
    env = _RecordingEnvironment()

    # Default kwargs (capture_access=False): no wrapping.
    asyncio.run(agent._exec(env, "echo hi"))

    assert env.recorded_command == "set -o pipefail; echo hi"
    assert "strace" not in env.recorded_command
    assert "bash -o pipefail -c" not in env.recorded_command


def test_exec_env_gate_dominates_capture_kwargs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Opt-in is env-gated: capture kwargs do NOT wrap while the env is unset."""
    monkeypatch.delenv("PIER_CAPTURE_STRACE", raising=False)

    agent = _NoOpInstalledAgent(logs_dir=tmp_path)
    env = _RecordingEnvironment()

    # Caller opts in via kwargs, but the env gate is off -> still plain.
    asyncio.run(
        agent._exec(
            env,
            "echo hi",
            capture_access=True,
            capture_log_path="/logs/agent/strace.log",
        )
    )

    assert env.recorded_command == "set -o pipefail; echo hi"
    assert "strace" not in env.recorded_command
    assert "bash -o pipefail -c" not in env.recorded_command


def _make_docker_env(
    *,
    capabilities_compose_path: Path | None,
    allow_internet: bool = True,
) -> DockerEnvironment:
    """Build a DockerEnvironment shell with just the attrs `_docker_compose_paths` reads."""
    env = DockerEnvironment.__new__(DockerEnvironment)
    # environment_dir backs the `_environment_docker_compose_path` property; point
    # it at a directory with no docker-compose.yaml so that optional path is absent.
    env.environment_dir = Path("/nonexistent-environment-dir")
    env._resources_compose_path = None
    env._capabilities_compose_path = capabilities_compose_path
    env._mounts_compose_path = None
    env._egress_proxy_compose_path = None
    env._is_windows_container = False
    env._use_prebuilt = False

    class _TaskEnvConfig:
        allow_internet = True

    cfg = _TaskEnvConfig()
    cfg.allow_internet = allow_internet
    env.task_env_config = cfg
    return env


def _expected_baseline_paths(env: DockerEnvironment) -> list[Path]:
    """The pre-capture path list: base + build, plus no-network when isolated."""
    paths = [env._DOCKER_COMPOSE_BASE_PATH, env._DOCKER_COMPOSE_BUILD_PATH]
    if not env.task_env_config.allow_internet:
        paths.append(env._DOCKER_COMPOSE_NO_NETWORK_PATH)
    return paths


def test_docker_compose_paths_excludes_capabilities_when_env_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the env unset and no capabilities path set, the list is the baseline."""
    monkeypatch.delenv("PIER_CAPTURE_STRACE", raising=False)

    env = _make_docker_env(capabilities_compose_path=None)
    paths = env._docker_compose_paths

    assert paths == _expected_baseline_paths(env)


def test_docker_compose_paths_gate_excludes_stale_capabilities_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even if a stale capabilities path is set, the env gate keeps it out."""
    monkeypatch.delenv("PIER_CAPTURE_STRACE", raising=False)

    sentinel = Path("/sentinel-docker-compose-capabilities.json")
    env = _make_docker_env(capabilities_compose_path=sentinel)
    paths = env._docker_compose_paths

    assert sentinel not in paths
    assert paths == _expected_baseline_paths(env)


def test_network_allowlist_is_baseline_without_mcp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No mcp_servers + no base URL + non-bedrock -> the documented baseline."""
    monkeypatch.delenv("PIER_CAPTURE_STRACE", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_USE_BEDROCK", raising=False)
    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)

    agent = ClaudeCode(logs_dir=tmp_path)
    allowlist = agent.network_allowlist()

    assert allowlist.domains == ["api.anthropic.com"]


def test_network_allowlist_includes_mcp_when_env_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """MCP-host allowlisting is no longer capture-gated: with capture off, an
    MCP-configured agent still widens the allowlist to reach its MCP host.

    (The no-MCP baseline stays byte-identical to upstream -- see
    test_network_allowlist_is_baseline_without_mcp.)
    """
    monkeypatch.delenv("PIER_CAPTURE_STRACE", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_USE_BEDROCK", raising=False)
    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)

    server = MCPServerConfig(
        name="driver",
        transport="streamable-http",
        url="https://mcp.driverai.com/v1/sse",
    )
    agent = ClaudeCode(logs_dir=tmp_path, mcp_servers=[server])

    assert "mcp.driverai.com" in agent.network_allowlist().domains
