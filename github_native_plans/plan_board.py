"""What every sandbox issue should show: its plan, its place in the plan, its next step and rank."""

# %% imports
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from github_client import GitHubClient
from plans import ITEM_MARKER, PLAN_LABEL, ItemStatus, NextStep

BRANCH_LINE = re.compile(r"^- \*\*Branch:\*\* \[`([^`]+)`\]", re.MULTILINE)
"""The branch line of an item issue's body."""

PULL_REQUEST_LINE = re.compile(r"^- \*\*Pull request:\*\* (?:[\w.-]+/[\w.-]+)?#(\d+)", re.MULTILINE)
"""The pull request line of an item issue's body."""

PLAN_TITLE_PREFIX = "Plan: "
"""Prefix of a plan issue's title."""


# %% one issue
@dataclass
class IssueFields:
    """The project field values one issue should show."""

    node_id: str
    """GraphQL id of the issue."""
    number: int
    """The issue's number."""
    title: str
    """The issue's title."""
    plan: str | None
    """Name of the plan the issue belongs to."""
    order: int | None
    """Position in its plan: 0 for the plan issue, then the sub-issue order from 1."""
    status: str | None = None
    """Option name of the item's status."""
    track: str | None = None
    """Option name of the item's track."""
    branch: str | None = None
    """The item's branch."""
    pull_request: int | None = None
    """The item's pull request number."""
    next_step: NextStep | None = None
    """What to do next with the item."""
    command: str | None = None
    """The basstler command that takes :attr:`next_step`."""
    blocker_numbers: list[int] = field(default_factory=list)
    """Numbers of the open issues this item waits for."""
    unblocks: int = 0
    """How many open items wait for this one."""
    rank: int | None = None
    """Place in the recommendation, from 1; ``None`` when not recommended."""

    @property
    def unblocks_shown(self) -> int | None:
        """:attr:`unblocks`, or ``None`` when it unblocks nothing, so the cell stays empty."""
        return self.unblocks or None


# %% the whole board
@dataclass
class PlanBoard:
    """The sandbox's plans in order, each with its items in sub-issue order and their blockers."""

    client: GitHubClient
    """Client that reads the repository's issues."""
    repository: str
    """``owner/name`` of the repository."""
    plan_issues: list[dict[str, Any]] = field(default_factory=list)
    """Plan issues in plan order (issue number)."""
    fields_by_number: dict[int, IssueFields] = field(default_factory=dict)
    """Desired values of every sandbox issue, by issue number."""

    @property
    def plan_names(self) -> list[str]:
        """Plan names in plan order."""
        return [issue["title"].removeprefix(PLAN_TITLE_PREFIX) for issue in self.plan_issues]

    @property
    def recommended(self) -> list[IssueFields]:
        """The recommended items, best first."""
        return sorted((entry for entry in self.fields_by_number.values() if entry.rank), key=lambda entry: entry.rank)

    def read(self, issues: list[dict[str, Any]], track_names: dict[str, str]) -> None:
        """Compute the desired values of ``issues``."""
        by_number = {issue["number"]: issue for issue in issues}
        self.plan_issues = sorted((issue for issue in issues if self.is_plan(issue)), key=lambda issue: issue["number"])
        for plan_issue, plan_name in zip(self.plan_issues, self.plan_names):
            self.fields_by_number[plan_issue["number"]] = IssueFields(plan_issue["node_id"], plan_issue["number"], plan_issue["title"], plan_name, 0)
            children = self.client.paginate(f"/repos/{self.repository}/issues/{plan_issue['number']}/sub_issues?per_page=100")
            for position, child in enumerate(children, start=1):
                if child["number"] in by_number:
                    self.fields_by_number[child["number"]] = self.item_fields(by_number[child["number"]], plan_name, position, track_names)
        for issue in issues:
            if issue["number"] not in self.fields_by_number:
                self.fields_by_number[issue["number"]] = self.item_fields(issue, None, None, track_names)
        self.rank()

    def item_fields(self, issue: dict[str, Any], plan: str | None, order: int | None, track_names: dict[str, str]) -> IssueFields:
        """The desired values of one item issue."""
        labels = [label["name"] for label in issue["labels"]]
        body = issue.get("body") or ""
        status = self.status_of(issue)
        tracks = [track_names[label] for label in labels if label in track_names]
        branch = BRANCH_LINE.search(body)
        pull_request = PULL_REQUEST_LINE.search(body)
        entry = IssueFields(
            node_id=issue["node_id"],
            number=issue["number"],
            title=issue["title"],
            plan=plan,
            order=order,
            status=status.title if status else None,
            track=tracks[0] if len(tracks) == 1 else None,
            branch=branch.group(1) if branch else None,
            pull_request=int(pull_request.group(1)) if pull_request else None,
        )
        if status is None:
            return entry
        open_blockers = []
        if status is ItemStatus.NOT_STARTED:
            blockers = self.client.paginate(f"/repos/{self.repository}/issues/{issue['number']}/dependencies/blocked_by?per_page=100")
            open_blockers = [blocker for blocker in blockers if self.status_of(blocker) is not ItemStatus.DONE]
        entry.next_step = NextStep.of(status, waits_for_blockers=bool(open_blockers))
        key = ITEM_MARKER.search(body)
        if entry.next_step.skill and key:
            entry.command = f"{entry.next_step.skill} {key.group(1).replace('/', ' ', 1)}"
        entry.blocker_numbers = [blocker["number"] for blocker in open_blockers]
        return entry

    def rank(self) -> None:
        """Rank the items worth doing now: started work first, then the ones that unblock the most, then plan order."""
        for entry in self.fields_by_number.values():
            for blocker in entry.blocker_numbers:
                if blocker in self.fields_by_number:
                    self.fields_by_number[blocker].unblocks += 1
        plan_position = {name: index for index, name in enumerate(self.plan_names)}
        candidates = [entry for entry in self.fields_by_number.values() if entry.next_step and entry.next_step.recommendation_priority]
        candidates.sort(key=lambda entry: (entry.next_step.recommendation_priority, -entry.unblocks, plan_position.get(entry.plan, len(plan_position)), entry.order or 0))
        for rank, entry in enumerate(candidates, start=1):
            entry.rank = rank

    @staticmethod
    def is_plan(issue: dict[str, Any]) -> bool:
        """Whether ``issue`` stands for a whole plan."""
        return any(label["name"] == PLAN_LABEL for label in issue["labels"])

    @staticmethod
    def status_of(issue: dict[str, Any]) -> ItemStatus | None:
        """The status an issue carries; a closed issue is done."""
        if issue["state"] == "closed":
            return ItemStatus.DONE
        return ItemStatus.from_labels([label["name"] for label in issue["labels"]])
