"""What an item's pull request says about whose turn it is."""

# %% imports
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from github_client import GitHubClient

QUERY = Path(__file__).parent / "queries" / "pull_request.graphql"
"""GraphQL document that reads one pull request."""


# %% states
class PullRequestState(StrEnum):
    """Whether a pull request is open, merged or closed, as GitHub's GraphQL API spells it."""

    OPEN = "OPEN"
    MERGED = "MERGED"
    CLOSED = "CLOSED"


class CheckRollup(StrEnum):
    """The combined result of a commit's checks, as GitHub's GraphQL API spells it."""

    SUCCESS = "SUCCESS"
    PENDING = "PENDING"
    EXPECTED = "EXPECTED"
    FAILURE = "FAILURE"
    ERROR = "ERROR"


FAILING_ROLLUPS = {CheckRollup.FAILURE, CheckRollup.ERROR}
"""Check results that need the author."""

CHANGES_REQUESTED = "CHANGES_REQUESTED"
"""Review state of a review that asks for changes."""


# %% one pull request
@dataclass
class PullRequest:
    """The parts of a pull request that decide whether its author has something to do."""

    state: PullRequestState
    """Open, merged or closed."""
    draft: bool
    """Whether it is still a draft."""
    changes_requested: bool
    """Whether a reviewer's latest review asks for changes."""
    open_threads: int
    """How many review threads are unresolved."""
    checks: CheckRollup | None
    """Combined result of the head commit's checks; ``None`` when it has none."""

    @classmethod
    def read(cls, client: GitHubClient, repository: str, number: int) -> PullRequest:
        """Read pull request ``number`` of ``repository``."""
        owner, name = repository.split("/")
        node = client.graphql(QUERY.read_text(), owner=owner, name=name, number=number)["repository"]["pullRequest"]
        return cls.from_node(node)

    @classmethod
    def from_node(cls, node: dict[str, Any]) -> PullRequest:
        """Parse the ``pullRequest`` node of :data:`QUERY`."""
        commits = node["commits"]["nodes"]
        rollup = commits[0]["commit"]["statusCheckRollup"] if commits else None
        return cls(
            state=PullRequestState(node["state"]),
            draft=node["isDraft"],
            changes_requested=any(review["state"] == CHANGES_REQUESTED for review in node["latestOpinionatedReviews"]["nodes"]),
            open_threads=sum(not thread["isResolved"] for thread in node["reviewThreads"]["nodes"]),
            checks=CheckRollup(rollup["state"]) if rollup else None,
        )

    @property
    def author_tasks(self) -> list[str]:
        """What waits on the author, as people read it; empty when nothing does."""
        tasks = []
        if self.changes_requested:
            tasks.append("changes requested")
        if self.open_threads:
            tasks.append(f"{self.open_threads} open review thread{'s' if self.open_threads > 1 else ''}")
        if self.checks in FAILING_ROLLUPS:
            tasks.append("CI failing")
        return tasks
