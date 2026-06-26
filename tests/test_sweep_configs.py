import json
from pathlib import Path


from pier.models.agent.name import AgentName
from pier.trial.sweep import (
    ManifestTask,
    SweepCell,
    build_sweep_configs,
    cell_id,
    load_manifest,
)


def _write_manifest(tmp_path: Path) -> Path:
    manifest = {
        "tasks": [
            {
                "task": "alpha-task",
                "task_dir": "/abs/tasks/alpha-task",
                "lang": "python",
                "arch": "arm64",
                "strace_image": "deepswe-alpha:arm64-strace",
                "repo_root": "/repo",
                "task_commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            },
            {
                "task": "beta-task",
                "task_dir": "/abs/tasks/beta-task",
                "lang": "go",
                "arch": "arm64",
                "strace_image": "deepswe-beta:arm64-strace",
                "repo_root": "/repo",
                "task_commit": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            },
        ]
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    return path


def test_load_manifest_parses_task_dir_lang_arch_image_repo_root_commit(tmp_path):
    path = _write_manifest(tmp_path)

    tasks = load_manifest(path)

    assert len(tasks) == 2
    assert all(isinstance(t, ManifestTask) for t in tasks)

    alpha = tasks[0]
    assert alpha.task == "alpha-task"
    assert alpha.task_dir == "/abs/tasks/alpha-task"
    assert alpha.lang == "python"
    assert alpha.arch == "arm64"
    assert alpha.strace_image == "deepswe-alpha:arm64-strace"
    assert alpha.repo_root == "/repo"
    assert alpha.task_commit == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def test_cell_id_is_deterministic_and_suffix_free():
    a = cell_id("explore", "alpha-task", "claude-sonnet", 0, "arm64")
    b = cell_id("explore", "alpha-task", "claude-sonnet", 0, "arm64")

    assert a == b
    assert a == "explore/alpha-task/claude-sonnet/0/arm64"


def test_build_sweep_configs_sets_model_task_replicate_and_disables_verification(
    tmp_path,
):
    tasks = load_manifest(_write_manifest(tmp_path))
    models = ["model-x", "model-y"]
    k = 2
    out_root = tmp_path / "out"

    cells = build_sweep_configs(
        tasks, models=models, k=k, arch="arm64", out_root=out_root
    )

    # N tasks (2) x M models (2) x K (2) = 8 cells
    assert len(cells) == len(tasks) * len(models) * k == 8
    assert all(isinstance(c, SweepCell) for c in cells)

    for c in cells:
        assert c.config.agent.model_name == c.model
        assert c.config.agent.name == AgentName.CLAUDE_CODE.value
        assert c.config.verifier.disable is True
        assert c.replicate_index in range(k)

    # Each task path is carried through onto the TaskConfig.
    alpha_cells = [c for c in cells if c.task == "alpha-task"]
    assert alpha_cells
    for c in alpha_cells:
        assert str(c.config.task.path) == "/abs/tasks/alpha-task"

    # Per-cell manifest provenance: each cell carries ITS task's commit/repo_root
    # (a sweep spans multiple tasks with different commits — they must not be
    # stamped once for the whole run).
    for c in alpha_cells:
        assert c.task_commit == "a" * 40
        assert c.repo_root == "/repo"
    beta_cells = [c for c in cells if c.task == "beta-task"]
    assert beta_cells
    for c in beta_cells:
        assert c.task_commit == "b" * 40

    # Models and replicate indices are fully crossed per task.
    by_task = {}
    for c in cells:
        by_task.setdefault(c.task, set()).add((c.model, c.replicate_index))
    for combos in by_task.values():
        assert combos == {(m, r) for m in models for r in range(k)}


def test_build_sweep_configs_names_trials_dir_with_condition_and_arch_and_returns_expected_cells(
    tmp_path,
):
    tasks = load_manifest(_write_manifest(tmp_path))
    out_root = tmp_path / "out"

    cells = build_sweep_configs(
        tasks, models=["model-x"], k=1, arch="arm64", out_root=out_root
    )

    assert len(cells) == 2
    for c in cells:
        trials_dir = str(c.config.trials_dir)
        assert c.task in trials_dir
        assert "explore" in trials_dir
        assert "arm64" in trials_dir
        assert str(out_root) in trials_dir
        # cell_id matches the deterministic helper.
        assert c.cell_id == cell_id(
            "explore", c.task, c.model, c.replicate_index, "arm64"
        )


def test_build_sweep_configs_is_pure(tmp_path, monkeypatch):
    tasks = load_manifest(_write_manifest(tmp_path))
    out_root = tmp_path / "out"

    # No filesystem writes: out_root must not be created by the builder.
    cells = build_sweep_configs(
        tasks, models=["model-x"], k=1, arch="arm64", out_root=out_root
    )

    assert not out_root.exists()
    assert len(cells) == 2

    # Calling twice yields equal configs (deterministic / no side state).
    cells2 = build_sweep_configs(
        tasks, models=["model-x"], k=1, arch="arm64", out_root=out_root
    )
    assert [c.cell_id for c in cells] == [c.cell_id for c in cells2]
    assert [c.config for c in cells] == [c.config for c in cells2]
