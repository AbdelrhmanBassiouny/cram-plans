"""What every sandbox issue should show: its plan, its place in the plan, its next step and rank."""

# %% imports
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from claude_session import ClaudeSessionLink
from github_client import GitHubClient
from plans import ITEM_MARKER, PLAN_LABEL, ItemStatus, NextStep
from pull_requests import PullRequest, PullRequestState

BRANCH_LINE = re.compile(r"^- \*\*Branch:\*\* \[`([^`]+)`\]", re.MULTILINE)
"""The branch line of an item issue's body."""

PULL_REQUEST_LINE = re.compile(r"^- \*\*Pull request:\*\* ([\w.-]+/[\w.-]+)?#(\d+)", re.MULTILINE)
"""The pull request line of an item issue's body; the repository is optional."""

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
    body: str
    """The issue's body as read."""
    plan: str | None
    """Name of the plan the issue belongs to."""
    order: int | None
    """Position in its plan: 0 for the plan issue, then the sub-issue order from 1."""
    item_status: ItemStatus | None = None
    """Where the item stands; a merged pull request makes it done."""
    track: str | None = None
    """Option name of the item's track."""
    branch: str | None = None
    """The item's branch."""
    pull_request: int | None = None
    """The item's pull request number."""
    pull_request_state: PullRequest | None = None
    """What the item's pull request says, read live."""
    next_step: NextStep | None = None
    """What to do next with the item."""
    reasons: list[str] = field(default_factory=list)
    """Why :attr:`next_step` is the next step, as people read it."""
    command: str | None = None
    """The basstler command that takes :attr:`next_step`."""
    session_link: str | None = None
    """Link that opens a Claude session with :attr:`command` typed in."""
    blocker_numbers: list[int] = field(default_factory=list)
    """Numbers of the open issues this item waits for."""
    unblocks: int = 0
    """How many open items wait for this one."""
    rank: int | None = None
    """Place in the recommendation, from 1; ``None`` when not recommended."""

    @property
    def status(self) -> str | None:
        """Option name of :attr:`item_status`."""
        return self.item_status.title if self.item_status else None

    @property
    def reason(self) -> str | None:
        """:attr:`reasons` on one line, ``None`` when there are none."""
        return " · ".join(self.reasons) or None

    @property
    def unblocks_shown(self) -> int | None:
        """:attr:`unblocks`, or ``None`` when it unblocks nothing, so the cell stays empty."""
        return self.unblocks or None


# %% the whole board
@dataclass
class PlanBoard:
    """The sandbox's plans in order, each with its items in sub-issue order, their blockers and pull requests."""

    client: GitHubClient
    """Client that reads the repository's issues and the code repository's pull requests."""
    repository: str
    """``owner/name`` of the repository."""
    code_repository: str
    """``owner/name`` of the repository a pull request line without one points into."""
    session_link: ClaudeSessionLink
    """Builds the link that starts a session for an item."""
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
            self.fields_by_number[plan_issue["number"]] = IssueFields(plan_issue["node_id"], plan_issue["number"], plan_issue["title"], plan_issue.get("body") or "", plan_name, 0)
            children = self.client.paginate(f"/repos/{self.repository}/issues/{plan_issue['number']}/sub_issues?per_page=100")
            for position, child in enumerate(children, start=1):
                if child["number"] in by_number:
                    self.fields_by_number[child["number"]] = self.item_fields(by_number[child["number"]], plan_name, position, track_names)
        for issue in issues:
            if issue["number"] not in self.fields_by_number:
                self.fields_by_number[issue["number"]] = self.item_fields(issue, None, None, track_names)
        for entry in self.fields_by_number.values():
            self.decide_next_step(entry)
        self.rank()

    def item_fields(self, issue: dict[str, Any], plan: str | None, order: int | None, track_names: dict[str, str]) -> IssueFields:
        """The values of one item issue that its own labels, body and pull request give."""
        labels = [label["name"] for label in issue["labels"]]
        body = issue.get("body") or ""
        tracks = [track_names[label] for label in labels if label in track_names]
        branch = BRANCH_LINE.search(body)
        pull_request = PULL_REQUEST_LINE.search(body)
        entry = IssueFields(
            node_id=issue["node_id"],
            number=issue["number"],
            title=issue["title"],
            body=body,
            plan=plan,
            order=order,
            item_status=self.status_of(issue),
            track=tracks[0] if len(tracks) == 1 else None,
            branch=branch.group(1) if branch else None,
            pull_request=int(pull_request.group(2)) if pull_request else None,
        )
        if pull_request and entry.item_status not in (None, ItemStatus.DONE):
            entry.pull_request_state = PullRequest.read(self.client, pull_request.group(1) or self.code_repository, entry.pull_request)
            if entry.pull_request_state.state is PullRequestState.MERGED:
                entry.item_status = ItemStatus.DONE
        return entry

    def decide_next_step(self, entry: IssueFields) -> None:
        """Fill in one item's next step, why, its command and its session link."""
        if entry.item_status is None:
            return
        if entry.item_status is ItemStatus.NOT_STARTED and entry.pull_request_state is None:
            blockers = self.client.paginate(f"/repos/{self.repository}/issues/{entry.number}/dependencies/blocked_by?per_page=100")
            entry.blocker_numbers = [blocker["number"] for blocker in blockers if self.board_status_of(blocker) is not ItemStatus.DONE]
        entry.next_step, entry.reasons = self.next_step_of(entry)
        key = ITEM_MARKER.search(entry.body)
        if entry.next_step.skill and key:
            entry.command = f"{entry.next_step.skill} {key.group(1).replace('/', ' ', 1)}"
            entry.session_link = self.session_link.to(entry.command)

    @staticmethod
    def next_step_of(entry: IssueFields) -> tuple[NextStep, list[str]]:
        """The next step of one item and why: whatever waits on its author comes before its own status."""
        pull_request = entry.pull_request_state
        if pull_request and pull_request.state is PullRequestState.MERGED:
            return NextStep.DONE, ["pull request merged"]
        if entry.item_status is ItemStatus.DONE:
            return NextStep.DONE, []
        if entry.item_status is ItemStatus.DEFERRED:
            return NextStep.RECONSIDER, []
        if pull_request and pull_request.state is PullRequestState.CLOSED:
            return NextStep.RECONSIDER, ["pull request closed unmerged"]
        if pull_request is None and entry.item_status is ItemStatus.NOT_STARTED:
            if entry.blocker_numbers:
                return NextStep.WAITING, ["waits for " + ", ".join(f"#{number}" for number in entry.blocker_numbers)]
            return NextStep.START_NOW, []
        author_tasks = pull_request.author_tasks if pull_request else []
        if entry.item_status is ItemStatus.BLOCKED:
            return NextStep.RESOLVE, ["marked blocked", *author_tasks]
        if author_tasks:
            return NextStep.RESOLVE, author_tasks
        if pull_request is None:
            return NextStep.RESUME, ["no pull request yet"]
        if pull_request.draft:
            return NextStep.RESUME, ["draft pull request"]
        return NextStep.IN_REVIEW, ["waiting for review"]

    def rank(self) -> None:
        """Rank the items worth doing now: by step, then the ones that unblock the most, then plan order."""
        for entry in self.fields_by_number.values():
            for blocker in entry.blocker_numbers:
                if blocker in self.fields_by_number:
                    self.fields_by_number[blocker].unblocks += 1
        plan_position = {name: index for index, name in enumerate(self.plan_names)}
        candidates = [entry for entry in self.fields_by_number.values() if entry.next_step and entry.next_step.recommendation_priority]
        candidates.sort(key=lambda entry: (entry.next_step.recommendation_priority, -entry.unblocks, plan_position.get(entry.plan, len(plan_position)), entry.order or 0))
        for rank, entry in enumerate(candidates, start=1):
            entry.rank = rank

    def board_status_of(self, issue: dict[str, Any]) -> ItemStatus | None:
        """The status of ``issue`` on this board, which counts a merged pull request, else from its labels."""
        entry = self.fields_by_number.get(issue["number"])
        return entry.item_status if entry else self.status_of(issue)

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
