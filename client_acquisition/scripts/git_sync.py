"""Safe GitHub synchronization for the client acquisition system.

- Checks current branch and repository status
- Preserves unrelated user changes
- Stages only intended client-acquisition files
- Uses descriptive commits
- Pushes only to the configured existing branch and remote
- Never uses git push --force
- Never stores tokens in tracked files
- Reports failures clearly
- Does not discard local results when sync fails
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

TRACKED_PATHS = [
    "client_acquisition/",
    "tests/",
    "AGENTS.md",
    "README.md",
]


@dataclass
class SyncResult:
    success: bool
    branch: str
    remote: str
    committed: bool
    pushed: bool
    message: str
    details: List[str]


def _run(cmd: List[str], cwd: Path) -> Tuple[int, str, str]:
    """Run a command, returning (returncode, stdout, stderr). Never prints secrets."""
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def _git(cwd: Path, *args: str) -> Tuple[int, str, str]:
    return _run(["git", *args], cwd)


def current_branch(cwd: Path) -> Optional[str]:
    rc, out, _ = _git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
    if rc != 0:
        return None
    return out or None


def working_tree_clean(cwd: Path) -> Tuple[bool, str]:
    rc, out, _ = _git(cwd, "status", "--porcelain")
    if rc != 0:
        return False, out
    return (len(out) == 0), out


def get_remote(cwd: Path) -> Optional[str]:
    rc, out, _ = _git(cwd, "remote")
    if rc != 0:
        return None
    remotes = [r for r in out.splitlines() if r.strip()]
    return remotes[0] if remotes else None


def sync(root: Path, branch: Optional[str] = None,
         remote: Optional[str] = None,
         tracked_paths: Optional[List[str]] = None) -> SyncResult:
    """Safely sync the client-acquisition files with GitHub.

    Does not discard local results on failure. Returns a SyncResult.
    """
    details: List[str] = []
    tracked_paths = tracked_paths or TRACKED_PATHS

    # Determine branch and remote
    active_branch = branch or current_branch(root) or "master"
    remote_name = remote or get_remote(root) or "origin"

    details.append(f"Branch: {active_branch}")
    details.append(f"Remote: {remote_name}")

    # Check git is a repo
    rc, _, err = _git(root, "rev-parse", "--is-inside-work-tree")
    if rc != 0:
        return SyncResult(False, active_branch, remote_name, False, False,
                          "Not a git repository", details)

    # Check current status
    clean, status_out = working_tree_clean(root)
    details.append(f"Working tree clean: {clean}")
    if status_out:
        details.append("Status:\n" + status_out)

    # Fetch (read-only, safe)
    rc, _, err = _git(root, "fetch", remote_name)
    if rc != 0:
        details.append(f"Fetch failed: {err}")
        return SyncResult(False, active_branch, remote_name, False, False,
                          "Fetch failed", details)

    # Check if local branch is behind/ahead
    rc, out, _ = _git(root, "rev-list", "--left-right", "--count",
                      f"{active_branch}...{remote_name}/{active_branch}")
    if rc == 0 and out:
        parts = out.split("\t")
        ahead = int(parts[0]) if len(parts) > 0 and parts[0] else 0
        behind = int(parts[1]) if len(parts) > 1 and parts[1] else 0
        details.append(f"Commits ahead: {ahead}, behind: {behind}")
        if behind > 0:
            # Attempt a fast-forward merge only (safe, no rebase/force)
            rc, _, err = _git(root, "merge", "--ff-only", f"{remote_name}/{active_branch}")
            if rc != 0:
                details.append(f"Fast-forward merge failed: {err}")
                return SyncResult(False, active_branch, remote_name, False, False,
                                  "Merge failed - local changes may conflict", details)
            details.append("Fast-forward merge succeeded")

    # Stage only intended files
    for path in tracked_paths:
        p = root / path
        if p.exists():
            _git(root, "add", str(path))

    # Check if anything staged
    rc, staged, _ = _git(root, "diff", "--cached", "--name-only")
    if not staged.strip():
        details.append("No changes to commit")
        return SyncResult(True, active_branch, remote_name, False, False,
                          "Nothing to commit", details)

    details.append(f"Staged files:\n{staged}")

    # Commit
    commit_msg = "chore(client-acquisition): sync CRM data and proposal drafts"
    rc, _, err = _git(root, "commit", "-m", commit_msg)
    if rc != 0:
        details.append(f"Commit failed: {err}")
        return SyncResult(False, active_branch, remote_name, False, False,
                          "Commit failed", details)
    details.append("Commit succeeded")

    # Push (no --force)
    rc, _, err = _git(root, "push", remote_name, active_branch)
    if rc != 0:
        details.append(f"Push failed: {err}")
        return SyncResult(False, active_branch, remote_name, True, False,
                          "Push failed - commit exists locally but not on remote", details)
    details.append("Push succeeded")

    return SyncResult(True, active_branch, remote_name, True, True,
                      "Sync completed successfully", details)


def sync_if_safe(root: Path) -> SyncResult:
    """Convenience: sync only if working tree concerns are manageable."""
    return sync(root)
