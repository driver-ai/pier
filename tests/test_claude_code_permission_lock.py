"""Optional deny-by-default permission lock for ClaudeCode (the ``permission_allow`` arg).

When ``permission_allow`` is set, the agent writes ``settings.json`` with
``permissions.defaultMode="dontAsk"`` + ``permissions.allow=[...]`` and runs under
``--permission-mode=dontAsk``, so any tool not in the allow-list is denied. When unset, no
settings.json is written and the default permission mode is used. These tests assert the emitted
settings command with no Docker or model.
"""

import base64
import json
from pathlib import Path

from pier.agents.installed.claude_code import ClaudeCode


def _decode_settings(cmd: str) -> dict:
    """Decode the base64 settings.json blob (`printf %s <b64> | base64 -d > <path>`)."""
    assert "$CLAUDE_CONFIG_DIR/settings.json" in cmd
    b64 = cmd.split("printf %s ", 1)[1].split(" ", 1)[0]
    return json.loads(base64.b64decode(b64))


def test_no_permission_allow_means_no_settings_command(tmp_path: Path):
    agent = ClaudeCode(logs_dir=tmp_path, model_name="anthropic/claude-sonnet-4-5")
    assert agent._build_register_settings_command() is None
    assert "settings.json" not in agent._build_setup_command()


def test_permission_allow_emits_dontask_settings(tmp_path: Path):
    agent = ClaudeCode(
        logs_dir=tmp_path,
        model_name="anthropic/claude-sonnet-4-5",
        permission_allow=["Read", "Write"],
    )
    cmd = agent._build_register_settings_command()
    assert cmd is not None
    # Enforced natively via permissions settings, not a PreToolUse hook.
    assert "hooks" not in cmd
    assert "allowlist.py" not in cmd
    settings = _decode_settings(cmd)
    assert settings == {
        "permissions": {"defaultMode": "dontAsk", "allow": ["Read", "Write"]}
    }
    # And the setup command actually chains the settings write in.
    assert "settings.json" in agent._build_setup_command()


def test_permission_allow_is_sorted(tmp_path: Path):
    """Allow-list is emitted sorted so the settings blob is deterministic regardless of caller order."""
    agent = ClaudeCode(
        logs_dir=tmp_path,
        model_name="anthropic/claude-sonnet-4-5",
        permission_allow=["Write", "Read"],
    )
    settings = _decode_settings(agent._build_register_settings_command())
    assert settings["permissions"]["allow"] == ["Read", "Write"]
