"""Turn basstler plans into issues: one issue per plan, one sub-issue per item.

Creates only what is missing, so issues stay the store once imported; ``--refresh-bodies``
rewrites existing issues from ``plan.yaml`` again.
"""

# %% imports
from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from string import Template
from typing import Any

from github_client import GitHubClient
from plans import (
    ITEM_MARKER,
    PLAN_LABEL,
    PLAN_MARKER,
    SANDBOX_LABEL,
    ItemStatus,
    Plan,
    PlanItem,
)

TEMPLATES = Path(__file__).parent / "templates"
"""Directory of the issue body templates."""

BARE_REFERENCE = re.compile(r"(?<![\w/])#(\d+)\b")
"""An issue or pull request reference without a repository."""

LABEL_COLORS = {"sandbox": "0e8a16", "plan": "1d76db", "status": "fbca04", "track": "c5def5"}
"""Hex colour of each label family."""


# %% issue registry
@dataclass
class SandboxIssues:
    """The sandbox's issues in one repository, keyed by the plan or item they stand for."""

    client: GitHubClient | None
    """Client for the repository; ``None`` renders without writing."""
    repository: str
    """``owner/name`` of the repository the issues live in."""
    by_key: dict[str, dict[str, Any]] = field(default_factory=dict)
    """Issue of each plan id and each ``plan/item`` key."""
    created: set[str] = field(default_factory=set)
    """Keys whose issue this run created."""

    def load(self) -> None:
        """Read every existing sandbox issue."""
        if self.client is None:
            return
        for issue in self.client.paginate(f"/repos/{self.repository}/issues?labels={SANDBOX_LABEL}&state=all&per_page=100"):
            body = issue.get("body") or ""
            match = ITEM_MARKER.search(body) or PLAN_MARKER.search(body)
            if match:
                self.by_key[match.group(1)] = issue

    def ensure(self, key: str, title: str, labels: list[str], closed: bool) -> dict[str, Any]:
        """Return the issue for ``key``, creating it if it is missing."""
        if key in self.by_key:
            return self.by_key[key]
        if self.client is None:
            issue = {"number": 1000 + len(self.by_key), "id": 0, "title": title, "labels": labels}
        else:
            issue = self.client.rest("POST", f"/repos/{self.repository}/issues", {"title": title, "labels": labels, "body": ""})
            if closed:
                self.client.rest("PATCH", f"/repos/{self.repository}/issues/{issue['number']}", {"state": "closed", "state_reason": "completed"})
        self.by_key[key] = issue
        self.created.add(key)
        return issue

    def write(self, key: str, title: str, labels: list[str], body: str) -> None:
        """Set the title, labels and body of the issue for ``key``."""
        issue = self.by_key[key]
        if self.client is None:
            print(f"--- #{issue['number']} {title}  {labels}\n{body}\n")
            return
        self.client.rest("PATCH", f"/repos/{self.repository}/issues/{issue['number']}", {"title": title, "labels": labels, "body": body})

    def link(self, path: str, field_name: str, linked_id: int) -> None:
        """Add the issue ``linked_id`` to the list at ``path`` unless it is on it."""
        if self.client is None:
            return
        if any(entry["id"] == linked_id for entry in self.client.paginate(f"/repos/{self.repository}/{path}?per_page=100")):
            return
        self.client.rest("POST", f"/repos/{self.repository}/{path}", {field_name: linked_id})


# %% importer
@dataclass
class PlanImporter:
    """Writes plans into a repository's issues."""

    issues: SandboxIssues
    """The repository's sandbox issues."""
    code_repository: str
    """``owner/name`` of the repository the plans' branches, pull requests and notes live in."""
    notes_branch: str
    """Branch the plans' roadmaps are read from."""
    refresh_bodies: bool
    """Rewrite existing issues from ``plan.yaml`` instead of only filling new ones."""

    def run(self, plans: list[Plan]) -> None:
        """Import ``plans``: issues, their bodies, sub-issues, then dependencies."""
        self.issues.load()
        self.ensure_labels(plans)
        for plan in plans:
            self.issues.ensure(plan.identifier, self.plan_title(plan), [SANDBOX_LABEL, PLAN_LABEL], closed=False)
            for item in plan.items:
                self.issues.ensure(item.key, item.title, self.item_labels(item), closed=item.status is ItemStatus.DONE)
        for plan in plans:
            self.write_plan(plan)
            for item in plan.items:
                self.write_item(item)
        for plan in plans:
            parent = self.issues.by_key[plan.identifier]["number"]
            for item in plan.items:
                self.issues.link(f"issues/{parent}/sub_issues", "sub_issue_id", self.issues.by_key[item.key]["id"])
        for plan in plans:
            for item in plan.items:
                for dependency in self.known_dependencies(item):
                    number = self.issues.by_key[item.key]["number"]
                    self.issues.link(f"issues/{number}/dependencies/blocked_by", "issue_id", self.issues.by_key[dependency]["id"])
        print(f"{len(self.issues.created)} issue(s) created; {len(self.issues.by_key)} sandbox issue(s) in total.")

    def ensure_labels(self, plans: list[Plan]) -> None:
        """Create every label the plans use that the repository lacks."""
        wanted = {
            SANDBOX_LABEL: (LABEL_COLORS["sandbox"], "Issue of the GitHub-native plans sandbox"),
            PLAN_LABEL: (LABEL_COLORS["plan"], "Issue that stands for a whole plan; its sub-issues are the items"),
        }
        wanted |= {status.label: (LABEL_COLORS["status"], status.title) for status in ItemStatus}
        wanted |= {track.label: (LABEL_COLORS["track"], track.name) for plan in plans for track in plan.tracks}
        client = self.issues.client
        if client is None:
            return
        existing = {label["name"] for label in client.paginate(f"/repos/{self.issues.repository}/labels?per_page=100")}
        for name, (color, description) in wanted.items():
            if name not in existing:
                client.rest("POST", f"/repos/{self.issues.repository}/labels", {"name": name, "color": color, "description": description})

    def should_write(self, key: str) -> bool:
        """Whether this run writes the issue for ``key``."""
        return self.refresh_bodies or key in self.issues.created

    def write_plan(self, plan: Plan) -> None:
        """Render and write the plan issue's body."""
        if not self.should_write(plan.identifier):
            return
        repository = self.issues.repository
        tracks = "\n".join(f"- `{track.label}` - {track.name} ({track.wave})" for track in plan.tracks)
        former = f"{self.code_repository}#{plan.former_tracking_issue}" if plan.former_tracking_issue else "-"
        body = Template((TEMPLATES / "plan_issue.md").read_text()).substitute(
            marker=plan.marker,
            description=self.qualify_references(plan.description),
            roadmap_url=f"https://github.com/{self.code_repository}/blob/{self.notes_branch}/.claude/personal/plans/{plan.identifier}/roadmap.md",
            former_tracking_issue=former,
            tracks=tracks,
            repository=repository,
            number=self.issues.by_key[plan.identifier]["number"],
        )
        self.issues.write(plan.identifier, self.plan_title(plan), [SANDBOX_LABEL, PLAN_LABEL], body)

    def write_item(self, item: PlanItem) -> None:
        """Render and write the item issue's body."""
        if not self.should_write(item.key):
            return
        repository = self.issues.repository
        blocked_by = [f"#{self.issues.by_key[dependency]['number']}" for dependency in self.known_dependencies(item)]
        blocked_by += [f"`{dependency}` (not imported)" for dependency in item.dependencies if dependency not in self.issues.by_key]
        branch = f"[`{item.branch}`](https://github.com/{self.code_repository}/tree/{item.branch})" if item.branch else "-"
        body = Template((TEMPLATES / "item_issue.md").read_text()).substitute(
            marker=item.marker,
            branch=branch,
            pull_request=f"{self.code_repository}#{item.pull_request_number}" if item.pull_request_number else "-",
            blocked_by=", ".join(blocked_by) or "-",
            session=f"[session]({item.session})" if item.session else "-",
            notes=self.qualify_references(item.notes) or "-",
            blockers="\n".join(f"- {self.qualify_references(blocker)}" for blocker in item.blockers) or "-",
            repository=repository,
            number=self.issues.by_key[item.key]["number"],
            plan_identifier=item.plan_identifier,
            item_identifier=item.identifier,
        )
        self.issues.write(item.key, item.title, self.item_labels(item), body)

    def qualify_references(self, text: str) -> str:
        """``text`` with each bare ``#123`` pointed at the code repository, where it was written."""
        return BARE_REFERENCE.sub(lambda match: f"{self.code_repository}#{match.group(1)}", text)

    def known_dependencies(self, item: PlanItem) -> list[str]:
        """The item's dependencies that have an issue."""
        return [dependency for dependency in item.dependencies if dependency in self.issues.by_key]

    @staticmethod
    def plan_title(plan: Plan) -> str:
        """Title of the plan's issue."""
        return f"Plan: {plan.title}"

    @staticmethod
    def item_labels(item: PlanItem) -> list[str]:
        """Labels of the item's issue."""
        return [SANDBOX_LABEL, item.status.label, item.track.label]


# %% command line
def main() -> None:
    """Import the plans named on the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plans", nargs="+", help="plan ids to import")
    parser.add_argument("--plans-directory", type=Path, required=True)
    parser.add_argument("--code-repository", required=True, help="owner/name the plans' branches and pull requests live in")
    parser.add_argument("--notes-branch", default="claude/personal-notes")
    parser.add_argument("--refresh-bodies", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="print the issues instead of writing them")
    arguments = parser.parse_args()
    client = None if arguments.dry_run else GitHubClient(os.environ["GITHUB_TOKEN"])
    issues = SandboxIssues(client, os.environ.get("GITHUB_REPOSITORY", "owner/repository"))
    plans = [Plan.read(arguments.plans_directory, identifier) for identifier in arguments.plans]
    PlanImporter(issues, arguments.code_repository, arguments.notes_branch, arguments.refresh_bodies).run(plans)


if __name__ == "__main__":
    main()
