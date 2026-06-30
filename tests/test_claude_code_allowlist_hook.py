"""Deny-by-default allowlist hook (driver-bench Plan 10 / DEC-083 / INS-045).

Under ``--permission-mode=bypassPermissions`` the ``--allowedTools`` flag is a no-op and only a
``--disallowedTools`` denylist enforces — which is allow-by-default, so an unenumerated/new tool
(e.g. ``Workflow``) slips through. The fix is a deny-by-default ``PreToolUse`` hook that permits
ONLY the declared ``tool_allowlist`` and denies everything else. These tests assert the emitted
setup command AND execute the generated hook to prove its decision logic (no Docker, no model).
"""

import base64
import json
import subprocess
import sys
from pathlib import Path

from pier.agents.installed.claude_code import ClaudeCode


def _decode_for(path: str, cmd: str) -> bytes:
    """Decode the base64 blob written to ``path`` (segments are `printf %s <b64> | base64 -d > <path>`)."""
    for seg in cmd.split(" && "):
        if seg.strip().endswith(path):
            b64 = seg.split("printf %s ", 1)[1].split(" ", 1)[0]
            return base64.b64decode(b64)
    raise AssertionError(f"no write segment for {path} in: {cmd}")


def test_no_allowlist_means_no_settings_command(tmp_path: Path):
    agent = ClaudeCode(logs_dir=tmp_path, model_name="anthropic/claude-sonnet-4-5")
    assert agent._build_register_settings_command() is None
    assert "settings.json" not in agent._build_setup_command()


def test_allowlist_emits_settings_and_hook(tmp_path: Path):
    agent = ClaudeCode(
        logs_dir=tmp_path,
        model_name="anthropic/claude-sonnet-4-5",
        tool_allowlist=["Read", "Write"],
    )
    cmd = agent._build_register_settings_command()
    assert cmd is not None
    assert "$CLAUDE_CONFIG_DIR/hooks/allowlist.py" in cmd
    assert "$CLAUDE_CONFIG_DIR/settings.json" in cmd
    # The settings.json wires a PreToolUse hook for every tool.
    settings = json.loads(_decode_for("$CLAUDE_CONFIG_DIR/settings.json", cmd))
    hook = settings["hooks"]["PreToolUse"][0]
    assert hook["matcher"] == "*"
    assert hook["hooks"][0]["command"] == "python3 $CLAUDE_CONFIG_DIR/hooks/allowlist.py"
    # And the setup command actually chains it in.
    assert "settings.json" in agent._build_setup_command()


def _run_hook(tmp_path: Path, allowlist: list[str], stdin: str) -> subprocess.CompletedProcess:
    agent = ClaudeCode(
        logs_dir=tmp_path, model_name="anthropic/claude-sonnet-4-5", tool_allowlist=allowlist
    )
    cmd = agent._build_register_settings_command()
    hook_src = _decode_for("$CLAUDE_CONFIG_DIR/hooks/allowlist.py", cmd).decode()
    hook_path = tmp_path / "allowlist.py"
    hook_path.write_text(hook_src)
    return subprocess.run(
        [sys.executable, str(hook_path)], input=stdin, capture_output=True, text=True
    )


def test_generated_hook_permits_allowlisted(tmp_path: Path):
    proc = _run_hook(tmp_path, ["Read", "Write"], json.dumps({"tool_name": "Read"}))
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""  # no deny payload ⇒ defers to normal flow (allowed)


def test_generated_hook_denies_unenumerated_tool(tmp_path: Path):
    # `Workflow` is the exact escape the denylist missed — the hook must deny it.
    proc = _run_hook(tmp_path, ["Read", "Write"], json.dumps({"tool_name": "Workflow"}))
    out = json.loads(proc.stdout)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "Workflow" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_generated_hook_fails_closed_on_bad_stdin(tmp_path: Path):
    proc = _run_hook(tmp_path, ["Read", "Write"], "not-json{{{")
    out = json.loads(proc.stdout)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
