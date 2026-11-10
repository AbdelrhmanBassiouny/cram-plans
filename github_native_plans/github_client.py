"""Minimal GitHub REST and GraphQL client on the standard library."""

# %% imports
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

API_ROOT = "https://api.github.com"
"""Base URL of the GitHub API."""

NEXT_PAGE_LINK = re.compile(r'<([^>]+)>;\s*rel="next"')
"""Matches the next-page URL in a REST ``Link`` header."""


# %% errors
@dataclass
class GitHubRequestRefused(Exception):
    """GitHub answered a request with an error."""

    method: str
    """HTTP method of the refused request."""
    url: str
    """URL of the refused request."""
    status: int
    """HTTP status GitHub answered with."""
    body: str
    """Response body, which names the reason."""

    def __str__(self) -> str:
        return f"{self.method} {self.url} -> {self.status}: {self.body}"


# %% client
@dataclass
class GitHubClient:
    """Sends authenticated requests to the GitHub API with one token."""

    token: str
    """Token every request is sent with."""
    write_interval_seconds: float = 1.0
    """Pause after each write, to stay under GitHub's content-creation limit."""

    def request(self, method: str, path_or_url: str, payload: Any = None) -> tuple[Any, dict[str, str]]:
        """Send one REST request and return its parsed body and headers."""
        url = path_or_url if path_or_url.startswith("https://") else API_ROOT + path_or_url
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(url, data=data, method=method, headers=self.headers())
        try:
            with urllib.request.urlopen(request) as response:
                text = response.read().decode()
                headers = dict(response.headers)
        except urllib.error.HTTPError as error:
            raise GitHubRequestRefused(method, url, error.code, error.read().decode()) from error
        if method != "GET":
            time.sleep(self.write_interval_seconds)
        return (json.loads(text) if text else None), headers

    def rest(self, method: str, path: str, payload: Any = None) -> Any:
        """Send one REST request and return its parsed body."""
        return self.request(method, path, payload)[0]

    def paginate(self, path: str) -> list[Any]:
        """Return every element of a paginated REST list."""
        elements: list[Any] = []
        url: str | None = path
        while url:
            page, headers = self.request("GET", url)
            elements.extend(page)
            match = NEXT_PAGE_LINK.search(headers.get("Link", ""))
            url = match.group(1) if match else None
        return elements

    def graphql(self, query: str, **variables: Any) -> Any:
        """Run one GraphQL query or mutation and return its ``data``."""
        body = self.rest("POST", "/graphql", {"query": query, "variables": variables})
        if body.get("errors"):
            raise GitHubRequestRefused("POST", API_ROOT + "/graphql", 200, json.dumps(body["errors"]))
        return body["data"]

    def headers(self) -> dict[str, str]:
        """Headers every request carries."""
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "github-native-plans-sandbox",
        }
