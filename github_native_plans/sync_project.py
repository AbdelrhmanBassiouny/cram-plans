"""Make a GitHub Project show the sandbox's issues, with fields derived from the issues.

The issues are the store: every field value is computed from an issue's labels, state and
body, so a sync can be repeated at any time and rebuilds anything that drifted.
"""

# %% imports
from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from github_client import GitHubClient
from plans import PLAN_LABEL, SANDBOX_LABEL, STATUS_COLORS, TRACK_LABEL_PREFIX, ItemStatus

QUERIES = Path(__file__).parent / "queries"
"""Directory of the GraphQL documents."""

BRANCH_LINE = re.compile(r"^- \*\*Branch:\*\* \[`([^`]+)`\]", re.MULTILINE)
"""The branch line of an item issue's body."""

PULL_REQUEST_LINE = re.compile(r"^- \*\*Pull request:\*\* (?:[\w.-]+/[\w.-]+)?#(\d+)", re.MULTILINE)
"""The pull request line of an item issue's body."""

STATUS_FIELD = "Plan status"
"""Project field that shows an item's status."""

TRACK_FIELD = "Track"
"""Project field that shows an item's track."""

BRANCH_FIELD = "Branch"
"""Project field that shows an item's branch."""

PULL_REQUEST_FIELD = "Pull request"
"""Project field that shows an item's pull request number."""


# %% desired state
@dataclass
class IssueFields:
    """The project field values one issue should show."""

    node_id: str
    """GraphQL id of the issue."""
    number: int
    """The issue's number."""
    status: str | None
    """Option name of the item's status."""
    track: str | None
    """Option name of the item's track."""
    branch: str | None
    """The item's branch."""
    pull_request: int | None
    """The item's pull request number."""

    @classmethod
    def of(cls, issue: dict[str, Any], track_names: dict[str, str]) -> IssueFields:
        """The values ``issue`` should show; a plan issue shows none."""
        labels = [label["name"] for label in issue["labels"]]
        body = issue.get("body") or ""
        if PLAN_LABEL in labels:
            return cls(issue["node_id"], issue["number"], None, None, None, None)
        status = ItemStatus.DONE if issue["state"] == "closed" else ItemStatus.from_labels(labels)
        tracks = [track_names[label] for label in labels if label in track_names]
        branch = BRANCH_LINE.search(body)
        pull_request = PULL_REQUEST_LINE.search(body)
        return cls(
            node_id=issue["node_id"],
            number=issue["number"],
            status=status.title if status else None,
            track=tracks[0] if len(tracks) == 1 else None,
            branch=branch.group(1) if branch else None,
            pull_request=int(pull_request.group(1)) if pull_request else None,
        )


# %% project
@dataclass
class ProjectSync:
    """Brings one user-owned project in line with the sandbox issues of one repository."""

    project_client: GitHubClient
    """Client whose token may write the project."""
    repository_client: GitHubClient
    """Client whose token may read the repository's issues."""
    repository: str
    """``owner/name`` of the repository."""
    project_title: str
    """Title the project is found or created by."""

    def run(self) -> None:
        """Create the project and its fields if missing, then set every item's values."""
        issues = self.repository_client.paginate(f"/repos/{self.repository}/issues?labels={SANDBOX_LABEL}&state=all&per_page=100")
        labels = self.repository_client.paginate(f"/repos/{self.repository}/labels?per_page=100")
        track_names = {label["name"]: label.get("description") or label["name"].removeprefix(TRACK_LABEL_PREFIX) for label in labels if label["name"].startswith(TRACK_LABEL_PREFIX)}
        project = self.ensure_project()
        project = self.ensure_fields(project, sorted(set(track_names.values())))
        fields = {field["name"]: field for field in project["fields"]["nodes"] if field}
        current = self.current_values(project["id"])
        writes = 0
        for issue in issues:
            desired = IssueFields.of(issue, track_names)
            item_id, values = current.get(desired.node_id) or (self.add_item(project["id"], desired.node_id), {})
            writes += self.set_values(project["id"], item_id, fields, values, desired)
        print(f"{len(issues)} issue(s) in {project['url']}; {writes} field value(s) written.")

    def query(self, document: str, **variables: Any) -> Any:
        """Run one GraphQL document from :data:`QUERIES` with the project token."""
        return self.project_client.graphql((QUERIES / f"{document}.graphql").read_text(), **variables)

    def find_project(self) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """The token's user, and its project titled :attr:`project_title` if it has one."""
        viewer = self.query("projects")["viewer"]
        projects = [project for project in viewer["projectsV2"]["nodes"] if project["title"] == self.project_title]
        return viewer, projects[0] if projects else None

    def ensure_project(self) -> dict[str, Any]:
        """The project, created if needed."""
        viewer, project = self.find_project()
        if project is not None:
            return project
        self.query("create_project", owner=viewer["id"], title=self.project_title)
        return self.find_project()[1]

    def ensure_fields(self, project: dict[str, Any], track_names: list[str]) -> dict[str, Any]:
        """The project with every field, a single-select one recreated when its options differ."""
        wanted_options = {
            STATUS_FIELD: [(status.title, STATUS_COLORS[status]) for status in ItemStatus],
            TRACK_FIELD: [(name, "BLUE") for name in track_names],
        }
        fields = {field["name"]: field for field in project["fields"]["nodes"] if field}
        changed = False
        for name, options in wanted_options.items():
            existing = fields.get(name)
            if existing and [option["name"] for option in existing.get("options", [])] == [option for option, _ in options]:
                continue
            if existing:
                self.query("delete_field", field=existing["id"])
            option_inputs = [{"name": option, "color": color, "description": ""} for option, color in options]
            self.query("create_field", project=project["id"], name=name, dataType="SINGLE_SELECT", options=option_inputs)
            changed = True
        for name, data_type in [(BRANCH_FIELD, "TEXT"), (PULL_REQUEST_FIELD, "NUMBER")]:
            if name not in fields:
                self.query("create_field", project=project["id"], name=name, dataType=data_type, options=None)
                changed = True
        return self.find_project()[1] if changed else project

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
                        field_values[value["field"]["id"]] = value.get("optionId") or value.get("text") or value.get("number")
                values[item["content"]["id"]] = (item["id"], field_values)
            if not items["pageInfo"]["hasNextPage"]:
                return values
            after = items["pageInfo"]["endCursor"]

    def add_item(self, project_id: str, content_id: str) -> str:
        """Add an issue to the project and return its item id."""
        return self.query("add_item", project=project_id, content=content_id)["addProjectV2ItemById"]["item"]["id"]

    def set_values(self, project_id: str, item_id: str, fields: dict[str, Any], current: dict[str, Any], desired: IssueFields) -> int:
        """Write the values of ``desired`` that differ from ``current``; return how many were written."""
        wanted: list[tuple[dict[str, Any], Any, dict[str, Any] | None]] = []
        for name, option in [(STATUS_FIELD, desired.status), (TRACK_FIELD, desired.track)]:
            option_ids = {entry["name"]: entry["id"] for entry in fields[name]["options"]}
            option_id = option_ids.get(option) if option else None
            wanted.append((fields[name], option_id, {"singleSelectOptionId": option_id} if option_id else None))
        wanted.append((fields[BRANCH_FIELD], desired.branch, {"text": desired.branch} if desired.branch else None))
        number = float(desired.pull_request) if desired.pull_request else None
        wanted.append((fields[PULL_REQUEST_FIELD], number, {"number": number} if number else None))
        writes = 0
        for field, value, value_input in wanted:
            if current.get(field["id"]) == value:
                continue
            if value_input is None:
                self.query("clear_value", project=project_id, item=item_id, field=field["id"])
            else:
                self.query("set_value", project=project_id, item=item_id, field=field["id"], value=value_input)
            writes += 1
        return writes


# %% command line
def main() -> None:
    """Sync the project named on the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-title", required=True)
    arguments = parser.parse_args()
    ProjectSync(
        project_client=GitHubClient(os.environ["PROJECTS_TOKEN"], write_interval_seconds=0.0),
        repository_client=GitHubClient(os.environ["GITHUB_TOKEN"]),
        repository=os.environ["GITHUB_REPOSITORY"],
        project_title=arguments.project_title,
    ).run()


if __name__ == "__main__":
    main()
