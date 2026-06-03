import shlex
from pathlib import Path

from pier.agents.installed.claude_code import ClaudeCode


def test_register_agents_command_none_when_unset(tmp_path: Path):
    agent = ClaudeCode(logs_dir=tmp_path, model_name="anthropic/claude-sonnet-4-5")

    assert agent.agents is None
    assert agent._build_register_agents_command() is None


def test_register_agents_command_writes_content(tmp_path: Path):
    md = (
        "---\n"
        "name: gather-context\n"
        'description: "Gathers context for the trial"\n'
        "---\n\n"
        'You gather context. Use `tools` and "quotes" safely.\n'
    )
    agent = ClaudeCode(
        logs_dir=tmp_path,
        model_name="anthropic/claude-sonnet-4-5",
        agents={"gather-context": md},
    )

    command = agent._build_register_agents_command()

    assert command is not None
    assert "mkdir -p $CLAUDE_CONFIG_DIR/agents" in command
    # Content is shlex-quoted and written to the per-agent markdown path.
    assert (
        f"echo {shlex.quote(md)} > $CLAUDE_CONFIG_DIR/agents/gather-context.md"
        in command
    )


def test_register_agents_command_quotes_multiple_agents(tmp_path: Path):
    agents = {
        "alpha": "---\nname: alpha\n---\nalpha body\n",
        "beta": "---\nname: beta\n---\nbeta body with 'single' quotes\n",
    }
    agent = ClaudeCode(
        logs_dir=tmp_path,
        model_name="anthropic/claude-sonnet-4-5",
        agents=agents,
    )

    command = agent._build_register_agents_command()

    assert command is not None
    for name, content in agents.items():
        assert (
            f"echo {shlex.quote(content)} > $CLAUDE_CONFIG_DIR/agents/{name}.md"
            in command
        )
