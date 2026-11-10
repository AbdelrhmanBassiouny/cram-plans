"""The plans read from basstler's ``plan.yaml`` files, and the issues they become."""

# %% imports
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import yaml

SANDBOX_LABEL = "github-native-sandbox"
"""Label on every issue this sandbox owns."""

PLAN_LABEL = "plan"
"""Label on the issue that stands for a whole plan."""

TRACK_LABEL_PREFIX = "track:"
"""Prefix of the label that names an item's track."""

PLAN_MARKER = re.compile(r"<!-- github-native-plan: (\S+) -->")
"""Hidden marker that ties a plan issue to its plan."""

ITEM_MARKER = re.compile(r"<!-- github-native-plan-item: (\S+) -->")
"""Hidden marker that ties an item issue to its plan item."""


# %% status
class ItemStatus(StrEnum):
    """Where a plan item stands; each value is also the suffix of its status label."""

    NOT_STARTED = "not-started"
    IN_PROGRESS = "in-progress"
    BLOCKED = "blocked"
    DEFERRED = "deferred"
    DONE = "done"

    @classmethod
    def from_plan_yaml(cls, spelling: str) -> ItemStatus:
        """The status a ``plan.yaml`` spelling (``not started``, ``in_progress``) means."""
        normalized = spelling.strip().lower().replace("_", "-").replace(" ", "-")
        return cls("done" if normalized == "merged" else normalized)

    @classmethod
    def from_labels(cls, labels: list[str]) -> ItemStatus | None:
        """The status a set of issue labels carries, if any."""
        statuses = [cls(label.removeprefix(STATUS_LABEL_PREFIX)) for label in labels if label.startswith(STATUS_LABEL_PREFIX)]
        return statuses[0] if len(statuses) == 1 else None

    @property
    def label(self) -> str:
        """The issue label that carries this status."""
        return STATUS_LABEL_PREFIX + self.value

    @property
    def title(self) -> str:
        """The status as people read it."""
        return self.value.replace("-", " ").capitalize()


STATUS_LABEL_PREFIX = "status:"
"""Prefix of the label that carries an item's status."""

STATUS_COLORS = {
    ItemStatus.NOT_STARTED: "GRAY",
    ItemStatus.IN_PROGRESS: "YELLOW",
    ItemStatus.BLOCKED: "RED",
    ItemStatus.DEFERRED: "PURPLE",
    ItemStatus.DONE: "GREEN",
}
"""Project colour of each status option."""


# %% plan model
@dataclass
class Track:
    """A track groups the items of one plan that share a topic."""

    identifier: str
    """The track's id in ``plan.yaml``."""
    name: str
    """The track's name as people read it."""
    wave: str
    """Name of the wave the track belongs to."""

    @property
    def label(self) -> str:
        """The issue label that puts an item on this track."""
        return TRACK_LABEL_PREFIX + self.identifier


@dataclass
class PlanItem:
    """One item of a plan, which becomes one sub-issue of the plan's issue."""

    plan_identifier: str
    """Id of the plan the item belongs to."""
    identifier: str
    """The item's id in ``plan.yaml``."""
    title: str
    """The item's title."""
    status: ItemStatus
    """Where the item stands."""
    track: Track
    """The track the item is on."""
    branch: str | None
    """The item's branch, once it has one."""
    pull_request_number: int | None
    """The item's pull request, once it has one."""
    session: str | None
    """The Claude Code session that last worked on the item."""
    notes: str
    """What is true about the item now."""
    blockers: list[str]
    """What stops the item from moving on."""
    dependencies: list[str]
    """Keys (``plan/item``) of the items this one waits for."""

    @property
    def key(self) -> str:
        """The item's key across every plan, ``plan/item``."""
        return f"{self.plan_identifier}/{self.identifier}"

    @property
    def marker(self) -> str:
        """The hidden marker that ties an issue to this item."""
        return f"<!-- github-native-plan-item: {self.key} -->"


@dataclass
class Plan:
    """One plan, which becomes one issue whose sub-issues are its items."""

    identifier: str
    """The plan's id."""
    title: str
    """The plan's title."""
    description: str
    """What the plan delivers."""
    former_tracking_issue: int | None
    """The issue basstler tracked the plan in."""
    tracks: list[Track]
    """The plan's tracks, in order."""
    items: list[PlanItem] = field(default_factory=list)
    """The plan's items, in order."""

    @property
    def marker(self) -> str:
        """The hidden marker that ties an issue to this plan."""
        return f"<!-- github-native-plan: {self.identifier} -->"

    @classmethod
    def read(cls, plans_directory: Path, identifier: str) -> Plan:
        """Read one plan from ``<plans_directory>/<identifier>/plan.yaml``."""
        document = yaml.safe_load((plans_directory / identifier / "plan.yaml").read_text())
        waves = {wave["id"]: wave["name"] for wave in document.get("waves", [])}
        tracks = {
            track["id"]: Track(track["id"], track["name"], waves.get(track.get("wave"), ""))
            for track in document.get("tracks", [])
        }
        plan = cls(
            identifier=document["id"],
            title=document["title"],
            description=document.get("description", "").strip(),
            former_tracking_issue=document.get("tracking_issue"),
            tracks=list(tracks.values()),
        )
        plan.items = [plan.item_from_plan_yaml(entry, tracks) for entry in document["items"]]
        return plan

    def item_from_plan_yaml(self, entry: dict, tracks: dict[str, Track]) -> PlanItem:
        """The item one ``items`` entry of ``plan.yaml`` describes."""
        return PlanItem(
            plan_identifier=self.identifier,
            identifier=entry["id"],
            title=entry["title"],
            status=ItemStatus.from_plan_yaml(entry["status"]),
            track=tracks[entry["track"]],
            branch=entry.get("branch"),
            pull_request_number=entry.get("pull_request_number"),
            session=entry.get("session"),
            notes=" ".join(str(entry.get("notes") or "").split()),
            blockers=[" ".join(str(blocker).split()) for blocker in entry.get("blockers") or []],
            dependencies=[
                dependency if "/" in dependency else f"{self.identifier}/{dependency}"
                for dependency in entry.get("depends_on") or []
            ],
        )
