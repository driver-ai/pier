import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from pier.models.task.config import ArtifactConfig
from pier.trial.trial import Trial


def _make_trial(input_artifacts, environment):
    """Build a Trial shell with only the attributes the staging path touches."""
    trial = Trial.__new__(Trial)
    trial._environment = environment
    trial._logger = SimpleNamespace(
        debug=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
        info=lambda *a, **k: None,
    )
    trial._task = SimpleNamespace(
        config=SimpleNamespace(
            environment=SimpleNamespace(input_artifacts=input_artifacts)
        )
    )
    return trial


def test_input_artifact_staged_before_launch():
    """input_artifacts trigger upload_file(source, destination) into the container."""
    calls: list[tuple[str, str]] = []

    async def fake_upload_file(source_path, target_path):
        calls.append(("upload_file", target_path))

    async def fake_exec(command, *args, **kwargs):
        calls.append(("exec", command))
        return SimpleNamespace(return_code=0, stdout="", stderr="")

    environment = SimpleNamespace(
        upload_file=AsyncMock(side_effect=fake_upload_file),
        exec=AsyncMock(side_effect=fake_exec),
    )

    input_artifacts = [
        ArtifactConfig(source="/host/abc.jsonl", destination="/seed/abc.jsonl"),
    ]
    trial = _make_trial(input_artifacts, environment)

    asyncio.run(trial._upload_input_artifacts())

    # upload_file was called with the artifact's (source, destination).
    environment.upload_file.assert_awaited_once()
    args, kwargs = environment.upload_file.call_args
    passed = {**kwargs}
    if args:
        passed.setdefault("source_path", args[0])
        if len(args) > 1:
            passed.setdefault("target_path", args[1])
    assert passed["source_path"] == "/host/abc.jsonl"
    assert passed["target_path"] == "/seed/abc.jsonl"

    # The destination parent dir is created before the upload.
    upload_idx = next(i for i, c in enumerate(calls) if c[0] == "upload_file")
    mkdir_calls = [
        i for i, c in enumerate(calls) if c[0] == "exec" and "mkdir -p" in c[1]
    ]
    assert mkdir_calls, "expected a mkdir -p for the destination parent dir"
    assert min(mkdir_calls) < upload_idx
    assert "/seed" in calls[min(mkdir_calls)][1]


def test_no_input_artifacts_is_noop():
    """With no input_artifacts, nothing is uploaded."""
    environment = SimpleNamespace(upload_file=AsyncMock(), exec=AsyncMock())
    trial = _make_trial([], environment)

    asyncio.run(trial._upload_input_artifacts())

    environment.upload_file.assert_not_called()
