import shlex
import subprocess

from pier.agents.installed.base import build_capture_command
from pier.utils.env import STRACE_TRACE_FLAGS

_EXPECTED_FLAGS = (
    "-f -y -s 4096 -e trace=openat,renameat2,rename,renameat,unlink,unlinkat,"
    "execve,clone,clone3"
)


def test_strace_flags_include_process_lifecycle():
    # Actor provenance (Plan 09) needs execve (names each PID) and clone/clone3
    # (links the process tree). -s 4096 keeps argv/paths from truncating.
    assert STRACE_TRACE_FLAGS == _EXPECTED_FLAGS
    assert "-s 4096" in STRACE_TRACE_FLAGS
    for syscall in ("execve", "clone", "clone3"):
        assert syscall in STRACE_TRACE_FLAGS
    # fork/vfork are intentionally OMITTED (absent on aarch64 -> preflight fail).
    assert "fork" not in STRACE_TRACE_FLAGS
    assert "vfork" not in STRACE_TRACE_FLAGS
    # The flags reach the wrapped command.
    wrapped = build_capture_command("claude --print", "/logs/agent/strace.log", enabled=True)
    assert _EXPECTED_FLAGS in wrapped


def test_build_capture_command_wraps_with_strace_when_enabled():
    command = "claude --print < /tmp/x.txt 2>&1 | tee /logs/agent/claude-code.txt"
    strace_log_path = "/logs/agent/strace.log"

    wrapped = build_capture_command(command, strace_log_path, enabled=True)

    assert _EXPECTED_FLAGS in wrapped
    assert f"strace {_EXPECTED_FLAGS} -o {strace_log_path} bash -o pipefail -c " in wrapped
    # The original command survives, shlex-quoted.
    assert shlex.quote(command) in wrapped


def test_build_capture_command_uses_inner_pipefail():
    command = "claude --print < /tmp/x.txt 2>&1 | tee /logs/agent/claude-code.txt"
    strace_log_path = "/logs/agent/strace.log"

    wrapped = build_capture_command(command, strace_log_path, enabled=True)

    # Inner shell must be pipefail-enabled, NOT a bare `bash -c`.
    assert "bash -o pipefail -c" in wrapped
    assert "bash -c " not in wrapped
    # The original command (with pipe + quotes) survives intact inside the quoted segment.
    assert shlex.quote(command) in wrapped


def test_capture_command_does_not_mask_pipeline_failure():
    command = "false | tee /tmp/pier_capture_test_x"
    strace_log_path = "/logs/agent/strace.log"

    wrapped = build_capture_command(command, strace_log_path, enabled=True)
    # Sanity: the build produced the strace-wrapped form.
    assert wrapped.startswith(f"strace {_EXPECTED_FLAGS} -o {strace_log_path} ")

    # strace is not available on the test host (macOS); execute just the inner
    # `bash -o pipefail -c '<command>'` part directly. This proves the inner
    # `-o pipefail` makes `false | tee` fail (non-zero exit).
    result = subprocess.run(
        ["bash", "-o", "pipefail", "-c", command],
        capture_output=True,
    )
    assert result.returncode != 0


def test_build_capture_command_disabled_is_identity():
    command = "claude --print < /tmp/x.txt 2>&1 | tee /logs/agent/claude-code.txt"
    strace_log_path = "/logs/agent/strace.log"

    assert build_capture_command(command, strace_log_path, enabled=False) == command
