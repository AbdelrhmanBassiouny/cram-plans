"""The project's views, created once each with the layout, grouping and sort the plan site shows."""

# %% imports
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from github_client import GitHubClient

VIEWS_API_VERSION = "2026-03-10"
"""First REST API version with the project views endpoint."""

DEFAULT_VIEW_NAME = "View 1"
"""Name GitHub gives the view of a new project."""


# %% view definitions
@dataclass
class ViewDefinition:
    """One view, in field names; the REST API takes field ids."""

    name: str
    """The view's tab name."""
    layout: str
    """``table`` or ``board``."""
    visible_fields: list[str]
    """Fields shown, in order."""
    sort_by: list[str]
    """Fields sorted by, ascending."""
    group_by: str | None = None
    """Field the rows (or board swimlanes) are grouped by."""
    columns_by: str | None = None
    """Field a board's columns are made of."""
    filter: str = ""
    """The view's filter query."""

    def payload(self, field_ids: dict[str, int]) -> dict[str, Any]:
        """The REST body that creates this view."""
        body: dict[str, Any] = {
            "name": self.name,
            "layout": self.layout,
            "visible_fields": [field_ids[name] for name in self.visible_fields],
            "sort_by": [[field_ids[name], "asc"] for name in self.sort_by],
        }
        if self.filter:
            body["filter"] = self.filter
        if self.group_by:
            body["group_by"] = [field_ids[self.group_by]]
        if self.columns_by:
            body["vertical_group_by"] = [field_ids[self.columns_by]]
        return body


VIEWS = [
    ViewDefinition(
        name="Plan",
        layout="board",
        visible_fields=["Next", "Session", "CI", "Pull request", "Why", "Plan status"],
        sort_by=["Order"],
        columns_by="Track",
        filter="-label:plan",
    ),
]
"""The views every project gets, in tab order."""


# %% creating them
@dataclass
class ProjectViews:
    """Creates the missing views of one user-owned project; a view that exists is changed only on request."""

    client: GitHubClient
    """Client whose token may write the project, on :data:`VIEWS_API_VERSION`."""
    owner_login: str
    """Login of the project's owner."""

    def ensure(self, project: dict[str, Any], query: Any, recreate: bool) -> int:
        """Create the missing views, then drop GitHub's untouched first view; return how many were created.

        With ``recreate``, every view is created anew and every view the project had is deleted.
        """
        existing = {view["name"]: view for view in project["views"]["nodes"]}
        field_ids = {entry["name"]: entry["databaseId"] for entry in project["fields"]["nodes"] if entry}
        missing = [view for view in VIEWS if recreate or view.name not in existing]
        for view in missing:
            self.client.rest("POST", f"/users/{self.owner_login}/projectsV2/{project['number']}/views", view.payload(field_ids))
        if recreate:
            for view in existing.values():
                query("delete_view", view=view["id"])
            return len(missing)
        default = existing.get(DEFAULT_VIEW_NAME)
        if missing and default and self.is_untouched(default):
            query("delete_view", view=default["id"])
        return len(missing)

    @staticmethod
    def is_untouched(view: dict[str, Any]) -> bool:
        """Whether ``view`` is still the plain table GitHub created."""
        return view["layout"] == "TABLE_LAYOUT" and not view["filter"] and not view["groupByFields"]["totalCount"] and not view["sortByFields"]["totalCount"]
