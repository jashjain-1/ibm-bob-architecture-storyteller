"""
archival_miner.py
~~~~~~~~~~~~~~~~~
Sub-Agent 5: 3-Tiered Historical PR & Git Context Miner.

Discovers the human backstory behind complex code:
  - Tier 1: Live GitHub API / `gh` CLI (PR discussions, review threads, issue links)
  - Tier 2: Local `.git` analysis (git log, git blame, PR merge commits)
  - Tier 3: Demo fixture cache (.context-cache/archival_fixtures.json) for offline hackathon demos
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, List, Optional

# `git log -L` appends the patch for each revision after the --format output, so
# the body field swallows the diff. Cut the prose at the first patch marker.
_PATCH_MARKER_RE = re.compile(
    r'^(?:diff --git |index [0-9a-f]{7,}\.\.|--- |\+\+\+ |@@ )',
    re.MULTILINE,
)


def strip_patch_text(text: str) -> str:
    """Returns only the human-written prose preceding any diff content."""
    match = _PATCH_MARKER_RE.search(text)
    return text[:match.start()] if match else text


@dataclass
class ArchivalBackstory:
    symbol_name: str
    pr_number: Optional[int]
    pr_title: str
    author: str
    date: str
    commit_sha: str
    discussion_summary: str
    why_it_was_written: str
    data_source_tier: str  # "Tier 1: GitHub API", "Tier 2: Local Git", "Tier 3: Fixture Cache"
    raw_discussion_excerpts: List[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ArchivalMiner:
    """Mines historical human discussions from GitHub API, local git, or demo fixtures."""

    def __init__(self, root_dir: str):
        self.root_dir = Path(root_dir).resolve()
        self.cache_dir = self.root_dir / ".context-cache"
        self.fixtures_file = self.cache_dir / "archival_fixtures.json"

    def get_backstory(
        self,
        symbol_name: str,
        file_path: str,
        line_start: int,
        line_end: int,
        unusual_flags: Optional[List[str]] = None,
    ) -> ArchivalBackstory:
        """Retrieves backstory using the 3-tiered fallback strategy."""
        # Tier 1: Try GitHub API / gh CLI if available
        tier1_result = self._try_tier1_github(symbol_name, file_path, line_start, line_end)
        if tier1_result:
            return tier1_result

        # Tier 2: Try Local Git Log / Blame
        tier2_result = self._try_tier2_local_git(symbol_name, file_path, line_start, line_end, unusual_flags)
        if tier2_result:
            return tier2_result

        # Tier 3: Fallback to Fixture Cache
        return self._try_tier3_fixture_cache(symbol_name, file_path, unusual_flags)

    def _try_tier1_github(
        self, symbol_name: str, file_path: str, line_start: int, line_end: int
    ) -> Optional[ArchivalBackstory]:
        """Queries gh CLI or GitHub REST API for PR review comments."""
        try:
            # Check if gh is authenticated
            res = subprocess.run(
                ["gh", "auth", "status"],
                cwd=self.root_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=3,
            )
            if res.returncode != 0:
                return None

            # Get latest commit sha for this line
            blame = subprocess.run(
                ["git", "blame", "-L", f"{line_start},{line_start}", "--porcelain", file_path],
                cwd=self.root_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=3,
            )
            if blame.returncode != 0:
                return None

            commit_sha = blame.stdout.splitlines()[0].split()[0]

            # Query PR associated with this commit
            pr_res = subprocess.run(
                ["gh", "pr", "list", "--search", commit_sha, "--state", "all", "--json", "number,title,author,body,comments"],
                cwd=self.root_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
            if pr_res.returncode == 0 and pr_res.stdout.strip():
                prs = json.loads(pr_res.stdout)
                if prs:
                    pr = prs[0]
                    comments = [c.get("body", "") for c in pr.get("comments", []) if c.get("body")]
                    why = pr.get("body", "").split("\n\n")[0] or f"Implemented in PR #{pr.get('number')} to address core architecture requirements."
                    return ArchivalBackstory(
                        symbol_name=symbol_name,
                        pr_number=pr.get("number"),
                        pr_title=pr.get("title", ""),
                        author=pr.get("author", {}).get("login", "teammate"),
                        date="",
                        commit_sha=commit_sha[:8],
                        discussion_summary=f"Reviewed and merged in PR #{pr.get('number')}: {pr.get('title')}",
                        why_it_was_written=why,
                        data_source_tier="Tier 1: Live GitHub API",
                        raw_discussion_excerpts=comments[:3],
                    )
        except Exception:
            pass
        return None

    def _try_tier2_local_git(
        self,
        symbol_name: str,
        file_path: str,
        line_start: int,
        line_end: int,
        unusual_flags: Optional[List[str]] = None,
    ) -> Optional[ArchivalBackstory]:
        """Extracts commit messages, PR merge commit references, and git blame locally."""
        try:
            abs_file = self.root_dir / file_path
            if not abs_file.exists():
                return None

            # Run git log on the line range
            cmd = ["git", "log", "-n", "3", "--format=%H%x00%an%x00%ad%x00%s%x00%b", "-L", f"{line_start},{min(line_end, line_start+10)}:{file_path}"]
            res = subprocess.run(cmd, cwd=self.root_dir, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5)

            if res.returncode == 0 and res.stdout.strip():
                entries = res.stdout.split("\x00")
                if len(entries) >= 5:
                    sha = entries[0].strip()[:8]
                    author = entries[1].strip()
                    date = entries[2].strip()
                    subject = entries[3].strip()
                    body = strip_patch_text(entries[4]).strip()

                    # Detect PR merge commit: "Merge pull request #104 from ..."
                    pr_num = None
                    pr_match = re.search(r'Merge pull request #(\d+)', subject + " " + body)
                    if pr_match:
                        pr_num = int(pr_match.group(1))

                    why = f"Added by {author} ({subject})."
                    if body:
                        why += f" {body[:150]}"
                    if unusual_flags:
                        why += f" Note: Contains {', '.join(unusual_flags)}."

                    return ArchivalBackstory(
                        symbol_name=symbol_name,
                        pr_number=pr_num,
                        pr_title=subject,
                        author=author,
                        date=date,
                        commit_sha=sha,
                        discussion_summary=f"Commit {sha} by {author}: {subject}",
                        why_it_was_written=why,
                        data_source_tier="Tier 2: Local Git History",
                        raw_discussion_excerpts=[subject, body[:200]] if body else [subject],
                    )
        except Exception:
            pass
        return None

    def _try_tier3_fixture_cache(
        self, symbol_name: str, file_path: str, unusual_flags: Optional[List[str]] = None
    ) -> ArchivalBackstory:
        """Falls back to the curated fixture cache, then to an explicit 'unknown'.

        Nothing here invents history. A missing fixture field stays empty and the
        final fallback says plainly that no record was found — presenting a
        synthesised PR number as mined history would misrepresent the evidence.
        """
        if self.fixtures_file.exists():
            try:
                data = json.loads(self.fixtures_file.read_text(encoding="utf-8"))
                if symbol_name in data:
                    item = data[symbol_name]
                    return ArchivalBackstory(
                        symbol_name=symbol_name,
                        pr_number=item.get("pr_number"),
                        pr_title=item.get("pr_title", ""),
                        author=item.get("author", ""),
                        date=item.get("date", ""),
                        commit_sha=item.get("commit_sha", ""),
                        discussion_summary=item.get("discussion_summary", ""),
                        why_it_was_written=item.get("why_it_was_written", ""),
                        data_source_tier="Tier 3: Fixture Cache",
                        raw_discussion_excerpts=item.get("raw_discussion_excerpts", []),
                    )
            except Exception:
                pass

        flags_text = f" It carries {', '.join(unusual_flags)}." if unusual_flags else ""
        return ArchivalBackstory(
            symbol_name=symbol_name,
            pr_number=None,
            pr_title="",
            author="",
            date="",
            commit_sha="",
            discussion_summary="No commit or pull-request history found for this symbol.",
            why_it_was_written=(
                f"No recorded history for '{symbol_name}' — the defining lines predate this "
                f"repository's history, or the file is untracked.{flags_text}"
            ),
            data_source_tier="Tier 3: No History Found",
            raw_discussion_excerpts=[],
        )
