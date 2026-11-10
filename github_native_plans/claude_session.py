"""Links that open a new Claude Code session on the web with a prompt already typed in."""

# %% imports
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote, urlencode

SESSION_START_URL = "https://claude.ai/code"
"""Page that starts a new Claude Code session on the web."""


# %% the link
@dataclass
class ClaudeSessionLink:
    """Builds the link that starts a session on one repository."""

    repository: str
    """``owner/name`` of the repository the session opens with."""
    environment: str | None = None
    """Name or id of the cloud environment the session runs in; ``None`` for the last one used."""

    def to(self, prompt: str) -> str:
        """The link that opens a session with ``prompt`` in its input box."""
        parameters = {"prompt": prompt, "repositories": self.repository}
        if self.environment:
            parameters["environment"] = self.environment
        return f"{SESSION_START_URL}?{urlencode(parameters, safe='/', quote_via=quote)}"
