"""The line at the top of each item issue that says what to do next, with a link that starts it."""

# %% imports
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from string import Template

from github_client import GitHubClient
from plan_board import IssueFields
from plans import ITEM_MARKER
from pull_requests import CheckRollup

TEMPLATE = Path(__file__).parent / "templates" / "next_step.md"
"""Template of the block, between its two markers."""

BLOCK = re.compile(r"<!-- github-native-next-step -->\n.*?\n<!-- /github-native-next-step -->", re.DOTALL)
"""The block as it stands in an issue body."""


# %% the block
@dataclass
class ItemNextStep:
    """Keeps the next-step block of item issues current; the rest of the body is never touched."""

    client: GitHubClient
    """Client with ``issues: write`` on the repository."""
    repository: str
    """``owner/name`` of the repository."""

    def write(self, item: IssueFields) -> bool:
        """Rewrite the block of ``item``'s issue if it changed; return whether it did."""
        body = self.body_with_block(item)
        if body == item.body:
            return False
        self.client.rest("PATCH", f"/repos/{self.repository}/issues/{item.number}", {"body": body})
        return True

    def body_with_block(self, item: IssueFields) -> str:
        """The issue body with the block replaced where it stands, else placed below the item marker or at the top."""
        block = Template(TEMPLATE.read_text()).substitute(line=self.line(item)).strip()
        if BLOCK.search(item.body):
            return BLOCK.sub(lambda _: block, item.body, count=1)
        marker = ITEM_MARKER.search(item.body)
        if marker is None:
            return block + "\n\n" + item.body
        return item.body[: marker.end()] + "\n" + block + item.body[marker.end() :]

    @staticmethod
    def line(item: IssueFields) -> str:
        """The visible line: the step, why, the session link, then the pull request and its checks unless *Why* says they fail."""
        parts = [f"**Next: {item.next_step}**" + (f" — {item.reason}" if item.reason else "")]
        if item.session_link:
            parts.append(f"[▶ Open in Claude]({item.session_link})")
        if item.pull_request_url:
            parts.append(f"[Pull request #{item.pull_request}]({item.pull_request_url})")
        if item.checks and item.checks != CheckRollup.FAILURE.title:
            parts.append(f"CI {item.checks.lower()}")
        return " · ".join(parts)
