"""Unit tests for sweep preflight validation of manifest tasks."""

from pathlib import Path

import toml

from pier.trial.sweep import (
    ManifestTask,
    TaskPreflight,
    all_green,
    preflight_tasks,
)


def _make_task(
    base: Path,
    *,
    task: str,
    docker_image: str,
    write_dir: bool = True,
    write_patch: bool = True,
    write_toml: bool = True,
    write_environment: bool = True,
    write_tests: bool = True,
) -> ManifestTask:
    """Synthesize a task on disk and return its ManifestTask entry.

    ``docker_image`` is also used as the manifest ``strace_image`` only when it
    is meant to match; callers pass an explicit ``strace_image`` via the
    returned entry when testing a mismatch.
    """
    task_dir = base / task
    if write_dir:
        task_dir.mkdir(parents=True)
        if write_patch:
            (task_dir / "solution").mkdir()
            (task_dir / "solution" / "solution.patch").write_text("diff\n")
        if write_toml:
            doc = {"environment": {"docker_image": docker_image}}
            (task_dir / "task.toml").write_text(toml.dumps(doc))
        if write_environment:
            (task_dir / "environment").mkdir()
        if write_tests:
            (task_dir / "tests").mkdir()
    return ManifestTask(
        task=task,
        task_dir=str(task_dir),
        lang="go",
        arch="arm64",
        strace_image=docker_image,
        repo_root=str(base),
        task_commit="0" * 40,
    )


def test_preflight_passes_on_well_formed_task(tmp_path):
    entry = _make_task(
        tmp_path,
        task="good-task",
        docker_image="deepswe-good:arm64-strace",
    )

    report = preflight_tasks([entry])

    assert len(report) == 1
    p = report[0]
    assert isinstance(p, TaskPreflight)
    assert p.task == "good-task"
    assert p.ok is True
    assert p.problems == []
    assert all_green(report) is True


def test_preflight_reports_missing_dir_missing_patch_or_non_strace_image(tmp_path):
    # 1) task_dir does not exist at all.
    missing_dir = _make_task(
        tmp_path,
        task="missing-dir",
        docker_image="deepswe-x:arm64-strace",
        write_dir=False,
    )

    # 2) dir exists but solution/solution.patch is absent.
    missing_patch = _make_task(
        tmp_path,
        task="missing-patch",
        docker_image="deepswe-y:arm64-strace",
        write_patch=False,
    )

    # 3) task.toml [environment].docker_image is a prebuilt non-strace image
    #    that does NOT match the manifest entry's strace_image.
    bad_image_dir = tmp_path / "bad-image"
    bad_image_dir.mkdir()
    (bad_image_dir / "solution").mkdir()
    (bad_image_dir / "solution" / "solution.patch").write_text("diff\n")
    (bad_image_dir / "environment").mkdir()
    (bad_image_dir / "tests").mkdir()
    (bad_image_dir / "task.toml").write_text(
        toml.dumps({"environment": {"docker_image": "deepswe-z:arm64-prebuilt"}})
    )
    bad_image = ManifestTask(
        task="bad-image",
        task_dir=str(bad_image_dir),
        lang="go",
        arch="arm64",
        strace_image="deepswe-z:arm64-strace",
        repo_root=str(tmp_path),
        task_commit="0" * 40,
    )

    report = preflight_tasks([missing_dir, missing_patch, bad_image])

    by_task = {p.task: p for p in report}

    assert by_task["missing-dir"].ok is False
    assert any("task_dir" in m for m in by_task["missing-dir"].problems)

    assert by_task["missing-patch"].ok is False
    assert any("solution.patch" in m for m in by_task["missing-patch"].problems)

    assert by_task["bad-image"].ok is False
    image_problem = " ".join(by_task["bad-image"].problems)
    assert "docker_image" in image_problem
    assert "deepswe-z:arm64-strace" in image_problem
    assert "deepswe-z:arm64-prebuilt" in image_problem

    assert all_green(report) is False
