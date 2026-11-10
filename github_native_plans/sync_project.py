"""Make a GitHub Project show the sandbox's issues, with fields derived from the issues.

The issues are the store: every field value is computed from an issue's labels, state, body,
sub-issue order and blockers, so a sync can be repeated at any time and rebuilds anything that drifted.
"""

# %% imports
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from claude_session import ClaudeSessionLink
from github_client import GitHubClient
from item_next_step import ItemNextStep
from plan_board import IssueFields, PlanBoard
from plans import (
    NEXT_STEP_COLORS,
    SANDBOX_LABEL,
    STATUS_COLORS,
    TRACK_LABEL_PREFIX,
    ItemStatus,
    NextStep,
)
from project_views import VIEWS_API_VERSION, ProjectViews
from pull_requests import CHECK_COLORS
from up_next_issue import UP_NEXT_SECTION, UpNextIssue

QUERIES = Path(__file__).parent / "queries"
"""Directory of the GraphQL documents."""


# %% fields
@dataclass
class FieldDefinition:
    """One project field and how an issue's desired values fill it."""

    name: str
    """The field's name in the project."""
    data_type: str
    """``SINGLE_SELECT``, ``TEXT`` or ``NUMBER``."""
    attribute: str
    """The :class:`IssueFields` attribute that holds the value."""

    def value_of(self, desired: IssueFields) -> Any:
        """The value ``desired`` gives this field, ``None`` for empty."""
        value = getattr(desired, self.attribute)
        if self.data_type == "NUMBER":
            return None if value is None else float(value)
        return value


FIELDS = [
    FieldDefinition("Branch", "TEXT", "branch"),
    FieldDefinition("Plan", "SINGLE_SELECT", "plan"),
    FieldDefinition("Order", "NUMBER", "order"),
    FieldDefinition("Rank", "NUMBER", "rank"),
    FieldDefinition("Unblocks", "NUMBER", "unblocks_shown"),
    FieldDefinition("Command", "TEXT", "command"),
    FieldDefinition("Next", "SINGLE_SELECT", "next_step"),
    FieldDefinition("Why", "TEXT", "reason"),
    FieldDefinition("Session", "TEXT", "session_link"),
    FieldDefinition("Track", "SINGLE_SELECT", "track"),
    FieldDefinition("CI", "SINGLE_SELECT", "checks"),
    FieldDefinition("Pull request", "TEXT", "pull_request_url"),
    FieldDefinition("Plan status", "SINGLE_SELECT", "status"),
]
"""Every field the sync owns, in creation order, which is the order a view shows them in after the title."""


# %% project
@dataclass
class ProjectSync:
    """Brings one user-owned project in line with the sandbox issues of one repository."""

    project_client: GitHubClient
    """Client whose token may write the project."""
    views_client: GitHubClient
    """Client for the project views endpoint, with the same token."""
    repository_client: GitHubClient
    """Client whose token may read and write the repository's issues."""
    repository: str
    """``owner/name`` of the repository."""
    code_repository: str
    """``owner/name`` of the repository the items' pull requests are in, which sessions open with."""
    project_title: str
    """Title the project is found or created by."""
    session_environment: str | None = None
    """Cloud environment a session link starts in; ``None`` for the one last used."""
    recreate_views: bool = False
    """Delete and recreate the views this sync owns, discarding edits made to them."""

    def run(self) -> None:
        """Create the project, fields and views if missing, set the values of every item and of *Up next*, then rewrite the next steps and *Up next*."""
        issues = self.repository_client.paginate(f"/repos/{self.repository}/issues?labels={SANDBOX_LABEL}&state=all&per_page=100")
        labels = self.repository_client.paginate(f"/repos/{self.repository}/labels?per_page=100")
        track_names = {label["name"]: label.get("description") or label["name"].removeprefix(TRACK_LABEL_PREFIX) for label in labels if label["name"].startswith(TRACK_LABEL_PREFIX)}
        board = PlanBoard(self.repository_client, self.repository, self.code_repository, ClaudeSessionLink(self.code_repository, self.session_environment))
        board.read(issues, track_names)
        up_next = UpNextIssue(self.repository_client, self.repository)
        up_next_issue = up_next.ensure()
        viewer, project = self.ensure_project()
        project, fields_created = self.ensure_fields(project, self.options(board))
        fields = {entry["name"]: entry for entry in project["fields"]["nodes"] if entry}
        current = self.current_values(project["id"])
        writes = 0
        up_next_row = IssueFields(up_next_issue["node_id"], up_next_issue["number"], up_next_issue["title"], up_next_issue.get("body") or "", None, 0, track=UP_NEXT_SECTION)
        for desired in [up_next_row, *board.fields_by_number.values()]:
            item_id, values = current.get(desired.node_id) or (self.add_item(project["id"], desired.node_id), {})
            writes += self.set_values(project["id"], item_id, fields, values, desired)
        next_steps = ItemNextStep(self.repository_client, self.repository)
        rewritten = sum(next_steps.write(entry) for entry in board.fields_by_number.values() if entry.next_step)
        up_next.write(up_next_issue, board, project["url"])
        views = ProjectViews(self.views_client, viewer["login"]).ensure(project, self.query, self.recreate_views or fields_created)
        print(f"{len(issues)} issue(s) in {project['url']}; {writes} field value(s) written; {rewritten} next step(s) rewritten; {views} view(s) created; {len(board.recommended)} item(s) recommended.")

    @staticmethod
    def options(board: PlanBoard) -> dict[str, list[tuple[str, str]]]:
        """Options and colours of each single-select field, in display order."""
        return {
            "Plan": [(name, "GRAY") for name in board.plan_names],
            "Plan status": [(status.title, STATUS_COLORS[status]) for status in ItemStatus],
            "Next": [(step.value, NEXT_STEP_COLORS[step]) for step in NextStep],
            "Track": [(UP_NEXT_SECTION, "GREEN"), *((name, "BLUE") for name in board.tracks)],
            "CI": list(CHECK_COLORS.items()),
        }

    def query(self, document: str, **variables: Any) -> Any:
        """Run one GraphQL document from :data:`QUERIES` with the project token."""
        return self.project_client.graphql((QUERIES / f"{document}.graphql").read_text(), **variables)

    def find_project(self) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """The token's user, and its project titled :attr:`project_title` if it has one."""
        viewer = self.query("projects")["viewer"]
        projects = [project for project in viewer["projectsV2"]["nodes"] if project["title"] == self.project_title]
        return viewer, projects[0] if projects else None

    def ensure_project(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """The token's user and the project, created if needed."""
        viewer, project = self.find_project()
        if project is not None:
            return viewer, project
        self.query("create_project", owner=viewer["id"], title=self.project_title)
        return self.find_project()

    def ensure_fields(self, project: dict[str, Any], options: dict[str, list[tuple[str, str]]]) -> tuple[dict[str, Any], bool]:
        """The project with every field, and whether any was created, which drops it from the views.

        A field is recreated when its type differs or when it is older than a field before it in
        :data:`FIELDS`; a single-select field whose options differ gets them in place.
        """
        fields = {entry["name"]: entry for entry in project["fields"]["nodes"] if entry}
        created = False
        options_changed = False
        newest = 0
        for definition in FIELDS:
            existing = fields.get(definition.name)
            wanted = options.get(definition.name)
            option_inputs = [{"name": option, "color": color, "description": ""} for option, color in wanted] if wanted is not None else None
            if existing is not None and not created and existing["databaseId"] > newest and existing["dataType"] == definition.data_type:
                newest = existing["databaseId"]
                if wanted is not None and [option["name"] for option in existing["options"]] != [option for option, _ in wanted]:
                    self.query("update_field_options", field=existing["id"], options=option_inputs)
                    options_changed = True
                continue
            if existing:
                self.query("delete_field", field=existing["id"])
            self.query("create_field", project=project["id"], name=definition.name, dataType=definition.data_type, options=option_inputs)
            created = True
        return (self.find_project()[1] if created or options_changed else project), created

    def current_values(self, project_id: str) -> dict[str, tuple[str, dict[str, Any]]]:
        """Item id and field values (by field id) of each issue already in the project."""
        values: dict[str, tuple[str, dict[str, Any]]] = {}
        after = None
        while True:
            items = self.query("project_items", project=project_id, after=after)["node"]["items"]
            for item in items["nodes"]:
                if not item["content"]:
                    continue
                field_values = {}
                for value in item["fieldValues"]["nodes"]:
                    if value and value.get("field"):
                        field_values[value["field"]["id"]] = next(value[key] for key in ("optionId", "text", "number") if key in value)
                values[item["content"]["id"]] = (item["id"], field_values)
            if not items["pageInfo"]["hasNextPage"]:
                return values
            after = items["pageInfo"]["endCursor"]

    def add_item(self, project_id: str, content_id: str) -> str:
        """Add an issue to the project and return its item id."""
        return self.query("add_item", project=project_id, content=content_id)["addProjectV2ItemById"]["item"]["id"]

    def set_values(self, project_id: str, item_id: str, fields: dict[str, Any], current: dict[str, Any], desired: IssueFields) -> int:
        """Write the values of ``desired`` that differ from ``current``; return how many were written."""
        writes = 0
        for definition in FIELDS:
            project_field = fields[definition.name]
            value = definition.value_of(desired)
            if definition.data_type == "SINGLE_SELECT":
                value = {option["name"]: option["id"] for option in project_field["options"]}.get(value)
            if current.get(project_field["id"]) == value:
                continue
            if value is None:
                self.query("clear_value", project=project_id, item=item_id, field=project_field["id"])
            else:
                key = {"SINGLE_SELECT": "singleSelectOptionId", "TEXT": "text", "NUMBER": "number"}[definition.data_type]
                self.query("set_value", project=project_id, item=item_id, field=project_field["id"], value={key: value})
            writes += 1
        return writes


# %% command line
def main() -> None:
    """Sync the project named on the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-title", required=True)
    parser.add_argument("--code-repository", required=True)
    parser.add_argument("--session-environment")
    parser.add_argument("--recreate-views", action="store_true")
    arguments = parser.parse_args()
    ProjectSync(
        project_client=GitHubClient(os.environ["PROJECTS_TOKEN"], write_interval_seconds=0.0),
        views_client=GitHubClient(os.environ["PROJECTS_TOKEN"], api_version=VIEWS_API_VERSION),
        repository_client=GitHubClient(os.environ["GITHUB_TOKEN"]),
        repository=os.environ["GITHUB_REPOSITORY"],
        code_repository=arguments.code_repository,
        project_title=arguments.project_title,
        session_environment=arguments.session_environment,
        recreate_views=arguments.recreate_views,
    ).run()


if __name__ == "__main__":
    main()
