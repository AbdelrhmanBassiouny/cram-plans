"""A pinned issue that lists the recommended work with its commands, readable on a phone."""

# %% imports
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any

from github_client import GitHubClient
from plan_board import IssueFields, PlanBoard
from plans import NextStep

UP_NEXT_LABEL = "up-next"
"""Label of the recommendation issue; it carries no sandbox label, so its edits start no sync."""

UP_NEXT_TITLE = "Up next"
"""Title of the recommendation issue."""

TEMPLATE = Path(__file__).parent / "templates" / "up_next.md"
"""Body template of the recommendation issue."""

WORKFLOW_FILE = "github-native-plans.yml"
"""The workflow that runs the sync, which *Refresh now* opens."""


# %% the issue
@dataclass
class UpNextIssue:
    """Writes the recommendation issue of one repository, creating and pinning it once."""

    client: GitHubClient
    """Client with ``issues: write`` on the repository."""
    repository: str
    """``owner/name`` of the repository."""

    def write(self, board: PlanBoard, project_url: str) -> None:
        """Rewrite the issue from ``board`` if its body changed."""
        steps = [entry.next_step for entry in board.fields_by_number.values()]
        body = Template(TEMPLATE.read_text()).substitute(
            project_url=project_url,
            refresh_url=f"https://github.com/{self.repository}/actions/workflows/{WORKFLOW_FILE}",
            in_review=steps.count(NextStep.IN_REVIEW),
            waiting=steps.count(NextStep.WAITING),
            done=steps.count(NextStep.DONE),
            items="\n\n".join(self.entry(item) for item in board.recommended) or "Nothing to do now.",
        )
        issue = self.find() or self.create()
        if (issue.get("body") or "").strip() != body.strip():
            self.client.rest("PATCH", f"/repos/{self.repository}/issues/{issue['number']}", {"body": body})

    @staticmethod
    def entry(item: IssueFields) -> str:
        """One recommended item: its rank, step, issue, why, plan, session link and command."""
        why = f" — {item.reason}" if item.reason else ""
        unblocks = f" · unblocks {item.unblocks}" if item.unblocks else ""
        return f"**{item.rank}. {item.next_step}** #{item.number}{why}\n{item.plan}{unblocks} · [▶ Open in Claude]({item.session_link})\n```text\n{item.command}\n```"

    def find(self) -> dict[str, Any] | None:
        """The open recommendation issue, if there is one."""
        issues = self.client.paginate(f"/repos/{self.repository}/issues?labels={UP_NEXT_LABEL}&state=open&per_page=100")
        return issues[0] if issues else None

    def create(self) -> dict[str, Any]:
        """Create the label and the issue, and pin it."""
        labels = {label["name"] for label in self.client.paginate(f"/repos/{self.repository}/labels?per_page=100")}
        if UP_NEXT_LABEL not in labels:
            self.client.rest("POST", f"/repos/{self.repository}/labels", {"name": UP_NEXT_LABEL, "color": "0e8a16", "description": "The recommended work, kept current by the sync"})
        issue = self.client.rest("POST", f"/repos/{self.repository}/issues", {"title": UP_NEXT_TITLE, "labels": [UP_NEXT_LABEL], "body": ""})
        self.client.graphql((Path(__file__).parent / "queries" / "pin_issue.graphql").read_text(), issue=issue["node_id"])
        return issue
