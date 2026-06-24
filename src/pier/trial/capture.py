from typing import Callable


def derive_model_patch(run_git: "Callable[[list[str]], str]") -> str:
    """Staged diff so untracked new files are included (DEC-019).

    run_git is injected (returns stdout) so this is unit-testable without a repo.
    The shell side runs git in the container repo dir via environment.exec.
    """
    run_git(["add", "-A"])
    return run_git(["diff", "--cached", "HEAD"])
