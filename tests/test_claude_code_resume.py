from pathlib import Path

import pytest

from pier.agents.installed.claude_code import ClaudeCode


def test_resume_flag_emitted(tmp_path: Path):
    """The --resume flag is emitted only when resume_session_id is set."""
    session_id = "abc123-session"

    with_resume = ClaudeCode(logs_dir=tmp_path, resume_session_id=session_id)
    flags = with_resume.build_cli_flags()
    assert f"--resume {session_id}" in flags

    without_resume = ClaudeCode(logs_dir=tmp_path)
    assert "--resume" not in without_resume.build_cli_flags()


def test_seed_command_targets_slug(tmp_path: Path):
    """The seeding step copies the staged session jsonl to projects/<slug>/<id>.jsonl."""
    seed_dir = "/staged/session-seed"
    session_id = "abc123-session"

    agent = ClaudeCode(
        logs_dir=tmp_path,
        seed_session_dir=seed_dir,
        resume_session_id=session_id,
    )

    # Default cwd (None) resolves to the /app slug.
    command = agent._build_register_session_seed_command(cwd=None)
    assert command is not None

    # Targets the URL-encoded cwd slug for /app and the resume id.
    expected_target = f"$CLAUDE_CONFIG_DIR/projects/-app/{session_id}.jsonl"
    assert expected_target in command
    # Copies from the already-staged seed dir (not host-side fetched).
    assert seed_dir in command
    # Creates the project dir so the copy is idempotent/safe.
    assert "projects/-app" in command
    assert "mkdir -p" in command

    # No seed -> no command.
    no_seed = ClaudeCode(logs_dir=tmp_path, resume_session_id=session_id)
    assert no_seed._build_register_session_seed_command(cwd=None) is None

    # Seed without an id -> no command (nothing to name the target file).
    no_id = ClaudeCode(logs_dir=tmp_path, seed_session_dir=seed_dir)
    assert no_id._build_register_session_seed_command(cwd=None) is None


@pytest.mark.parametrize(
    "cwd, slug",
    [
        ("/app", "-app"),
        ("/work", "-work"),
        (None, "-app"),
        ("/home/user/app", "-home-user-app"),
    ],
)
def test_seed_command_targets_slug_from_cwd(tmp_path: Path, cwd: str | None, slug: str):
    """The seed cp target slug derives from the run's actual cwd."""
    seed_dir = "/seed"
    session_id = "abc123-session"

    agent = ClaudeCode(
        logs_dir=tmp_path,
        seed_session_dir=seed_dir,
        resume_session_id=session_id,
    )

    command = agent._build_register_session_seed_command(cwd=cwd)
    assert command is not None

    expected_target = f"$CLAUDE_CONFIG_DIR/projects/{slug}/{session_id}.jsonl"
    assert expected_target in command
    assert f"projects/{slug}" in command
