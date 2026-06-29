from typing import Callable


def derive_model_patch(
    run_git: "Callable[[list[str]], str]", base_ref: str = "HEAD"
) -> str:
    """Staged diff vs the base ref so untracked new files are included (DEC-019).

    ``base_ref`` is the repo HEAD snapshotted BEFORE the agent ran. Diffing the
    staged index against that base (rather than the current ``HEAD``) captures
    the agent's edits even when the agent ``git commit``s them — after a commit,
    ``HEAD`` already contains the edits, so ``diff --cached HEAD`` would be empty.
    ``git add -A`` stages working-tree changes; after a commit the index equals
    the new HEAD, so ``diff --cached <base>`` yields committed + staged changes
    in both the committed and uncommitted cases.

    run_git is injected (returns stdout) so this is unit-testable without a repo.
    The shell side runs git in the container repo dir via environment.exec.
    """
    run_git(["add", "-A"])
    return run_git(["diff", "--cached", base_ref])
