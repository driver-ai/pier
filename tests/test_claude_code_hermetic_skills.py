"""Hermetic-skills regression (driver-bench Plan 10 / INS-044, upstreamable).

The claude-code adapter MUST NOT copy the operator's host ``~/.claude/skills`` into the
sandbox — that made a run depend on whoever launched it (non-reproducible) and added
capability back-doors (a web-search skill rode in). The benchmark-declared ``skills_dir``
copy (``_build_register_skills_command``) is the ONLY sanctioned skills source and stays.

``_build_setup_command`` is the extracted, container-free setup-command builder so these are
real assertions on the emitted string — no Docker, no live run.
"""

from pathlib import Path

from pier.agents.installed.claude_code import ClaudeCode


def test_setup_command_omits_host_skills(tmp_path: Path):
    agent = ClaudeCode(logs_dir=tmp_path, model_name="anthropic/claude-sonnet-4-5")
    cmd = agent._build_setup_command()
    assert "~/.claude/skills" not in cmd
    assert "~/.claude" not in cmd  # no host-config inheritance at all


def test_setup_command_still_makes_config_dirs(tmp_path: Path):
    agent = ClaudeCode(logs_dir=tmp_path, model_name="anthropic/claude-sonnet-4-5")
    cmd = agent._build_setup_command()
    # The standard config skeleton is still created (incl. an empty skills dir).
    assert "mkdir -p $CLAUDE_CONFIG_DIR/debug" in cmd
    assert "$CLAUDE_CONFIG_DIR/skills" in cmd


def test_setup_command_copies_declared_skills_dir(tmp_path: Path):
    skills = tmp_path / "declared-skills"
    skills.mkdir()
    agent = ClaudeCode(
        logs_dir=tmp_path,
        model_name="anthropic/claude-sonnet-4-5",
        skills_dir=str(skills),
    )
    cmd = agent._build_setup_command()
    # The declared-dir copy (the sanctioned source) is retained.
    assert str(skills) in cmd
    assert "$CLAUDE_CONFIG_DIR/skills/" in cmd
    # Still no host inheritance even with a declared dir.
    assert "~/.claude/skills" not in cmd


def test_setup_command_no_declared_skills_dir_means_no_copy(tmp_path: Path):
    agent = ClaudeCode(logs_dir=tmp_path, model_name="anthropic/claude-sonnet-4-5")
    # No declared skills_dir ⇒ the skills-copy builder returns None — nothing is copied. This
    # is the repo's "absent when unset" idiom (cf. tests/test_claude_code_agents_mount.py); the
    # prior `"cp -r" not in cmd or ...` assertion was a tautology (the disjunct was always True).
    assert agent._build_register_skills_command() is None
    # The empty skills dir is still created (also covered by test_setup_command_still_makes_config_dirs).
    cmd = agent._build_setup_command()
    assert "$CLAUDE_CONFIG_DIR/skills" in cmd
