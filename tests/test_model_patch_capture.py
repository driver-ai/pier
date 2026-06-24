import asyncio
from unittest import mock

import pytest

from pier.agents.installed.base import NonZeroAgentExitCodeError
from pier.trial.capture import derive_model_patch
from pier.trial.execution import AgentTimeoutError
from pier.trial.trial import Trial

_FAKE_STAGED_DIFF = (
    "diff --git a/new.txt b/new.txt\n"
    "new file mode 100644\n"
    "index 0000000..e69de29\n"
    "--- /dev/null\n"
    "+++ b/new.txt\n"
    "@@ -0,0 +1 @@\n"
    "+hello\n"
)


def test_derive_model_patch_includes_untracked():
    calls: list[list[str]] = []

    def fake_run_git(args: list[str]) -> str:
        calls.append(args)
        if args[:2] == ["diff", "--cached"]:
            return _FAKE_STAGED_DIFF
        return ""

    patch = derive_model_patch(fake_run_git)

    # (a) `git add -A` runs before the diff so untracked files are staged.
    assert calls[0] == ["add", "-A"]
    add_index = calls.index(["add", "-A"])
    diff_index = calls.index(["diff", "--cached", "HEAD"])
    assert add_index < diff_index

    # (b) the staged-diff stdout is returned verbatim.
    assert patch == _FAKE_STAGED_DIFF
    # The untracked-inclusion intent: a brand-new file shows in the staged diff.
    assert "new file mode" in patch
    assert "--- /dev/null" in patch


def _make_trial_for_run_ordering(execute_side_effect=None):
    """Build a Trial that records lifecycle call order without real __init__.

    All lifecycle methods the success / handled-failure run paths touch are
    replaced with children of one shared Mock parent so ``mock_calls`` records
    a single global ordering across them.
    """
    trial = Trial.__new__(Trial)

    parent = mock.Mock()

    # Minimal attrs the run() path reads directly.
    trial._task = mock.Mock()
    trial._task.has_steps = False
    trial._task.name = "t"
    trial._task.checksum = "x"
    trial._task.config = mock.Mock()
    trial._task.config.source = None

    trial.config = mock.Mock()
    trial.config.trial_name = "trial-1"
    trial.config.verifier.disable = True  # skip verification branch
    trial.config.task.get_task_id.return_value = "id"
    trial.config.task.source = None

    trial._agent = mock.Mock()
    trial._environment = mock.Mock()
    trial._environment.env_paths.agent_dir.as_posix.return_value = "/logs/agent"

    trial._trial_paths = mock.Mock()
    trial._logger = mock.Mock()

    # Wire lifecycle methods as async children of the shared parent so call
    # order is recorded in parent.mock_calls.
    async def _async_child(name, side_effect=None):
        child = getattr(parent, name)

        async def _coro(*args, **kwargs):
            child(*args, **kwargs)
            if side_effect is not None:
                raise side_effect

        return _coro

    loop = asyncio.new_event_loop()
    try:
        trial._setup_environment = loop.run_until_complete(
            _async_child("_setup_environment")
        )
        trial._setup_agent = loop.run_until_complete(_async_child("_setup_agent"))
        trial._upload_input_artifacts = loop.run_until_complete(
            _async_child("_upload_input_artifacts")
        )
        trial._execute_agent = loop.run_until_complete(
            _async_child("_execute_agent", side_effect=execute_side_effect)
        )
        trial._finalize_capture = loop.run_until_complete(
            _async_child("_finalize_capture")
        )
        trial._maybe_download_logs = loop.run_until_complete(
            _async_child("_maybe_download_logs")
        )
        trial._maybe_upload_agent_logs = loop.run_until_complete(
            _async_child("_maybe_upload_agent_logs")
        )
        trial._run_verification = loop.run_until_complete(
            _async_child("_run_verification")
        )
        trial._download_artifacts = loop.run_until_complete(
            _async_child("_download_artifacts")
        )
        trial._cleanup_and_finalize = loop.run_until_complete(
            _async_child("_cleanup_and_finalize")
        )
    finally:
        loop.close()

    # Synchronous helpers used by run() that we do not care to order.
    trial._invoke_hooks = mock.AsyncMock()
    trial._maybe_populate_agent_context = mock.Mock()
    trial._close_logger_handler = mock.Mock()
    trial._environment.run_healthcheck = mock.AsyncMock()

    return trial, parent


def _ordered_method_names(parent):
    return [c[0] for c in parent.mock_calls]


def test_finalize_capture_before_download_logs_success_path():
    trial, parent = _make_trial_for_run_ordering()

    with mock.patch("pier.trial.trial.TrialResult", mock.Mock()), mock.patch(
        "pier.trial.trial.ExceptionInfo", mock.Mock()
    ):
        asyncio.run(trial.run())

    names = _ordered_method_names(parent)
    assert "_finalize_capture" in names
    assert "_maybe_download_logs" in names
    first_download = names.index("_maybe_download_logs")
    finalize = names.index("_finalize_capture")
    assert finalize < first_download


@pytest.mark.parametrize(
    "exc",
    [
        NonZeroAgentExitCodeError("boom"),
        AgentTimeoutError("slow"),
    ],
)
def test_finalize_capture_before_download_logs_failure_path(exc):
    trial, parent = _make_trial_for_run_ordering(execute_side_effect=exc)

    with mock.patch("pier.trial.trial.TrialResult", mock.Mock()), mock.patch(
        "pier.trial.trial.ExceptionInfo", mock.Mock()
    ):
        asyncio.run(trial.run())

    names = _ordered_method_names(parent)
    assert "_finalize_capture" in names
    assert "_maybe_download_logs" in names
    first_download = names.index("_maybe_download_logs")
    finalize = names.index("_finalize_capture")
    # The handled-failure branch must finalize capture before downloading logs.
    assert finalize < first_download
