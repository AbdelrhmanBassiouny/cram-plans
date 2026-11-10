# GitHub-native plans (sandbox)

A trial of keeping plans in GitHub itself instead of `plan.yaml` and the plan site, using
the five RDR plans of
[cognitive_robot_abstract_machine](https://github.com/AbdelrhmanBassiouny/cognitive_robot_abstract_machine).
The plan issues live here; branches and pull requests stay in the code repository. This
repository only reads that repository's `plan.yaml` files, so basstler keeps working from
them unchanged.

## What lives where

| Thing | Where |
|---|---|
| A plan | An issue titled `Plan: …`, labelled `plan` |
| A plan item | A sub-issue of its plan's issue |
| Status | One `status:*` label (`not-started`, `in-progress`, `blocked`, `deferred`, `done`); a closed issue counts as done |
| Track | One `track:*` label; the label's description is the track's name |
| Dependencies | GitHub's native *blocked by* relationship, also listed in the body |
| Branch, pull request, notes, blockers | The issue body |
| Copyable prompts | The issue body, keyed on the issue number, so they never need updating |
| Plan order and item order | The plan issues' numbers, and each plan's sub-issue order (drag sub-issues to reorder) |
| The board | The user project *CRAM plans (GitHub-native sandbox)*, built from the issues |
| What to do next | The pinned *Up next* issue and the project's *Up next* view |

Every issue this sandbox owns carries the `github-native-sandbox` label, so
`label:github-native-sandbox` finds them all and deleting them ends the trial.

## How it runs

The workflow `.github/workflows/github-native-plans.yml` has two steps:

1. **Import** (`import_plans.py`, runs with the workflow's own token): creates the issues,
   sub-issue links and dependencies that are missing. It never rewrites an existing issue
   unless `refresh_bodies` is set, so once imported the issues are the store.
2. **Sync** (`sync_project.py`, needs the `PROJECTS_TOKEN` secret): creates the project, its
   fields and its views if missing, adds every sandbox issue and sets each field from the
   issues. It writes only values that differ, so it can be re-run at any time. A view that
   exists is never changed, so your own edits to a view stay; delete a view to get it back.
   It then rewrites the pinned *Up next* issue.

### Views

- **Up next**: the recommended items, best first, with the command that takes each one.
- **Plans**: every plan in order, its items in sub-issue order, like a plan page.
- **Board**: columns by status, one swimlane per plan.

### The recommendation

Every open item gets a *Next* step, worded like the plan site's buttons, and a *Why*. An
item's pull request in the code repository is read live on every sync:

| Next | When |
|---|---|
| *Resolve* | Something waits on you: a reviewer asked for changes, review threads are open, CI fails, or the item is labelled blocked |
| *Resume* | In progress with a draft pull request, or none yet |
| *Start now* | Not started and nothing it waits for is open |
| *In review* | Its pull request is ready and nothing waits on you; not recommended |
| *Waiting* | Not started and waits for an open item; not recommended |
| *Reconsider* | Deferred, or its pull request was closed unmerged |
| *Done* | Closed, `status:done`, or its pull request merged |

*Resolve*, *Resume* and *Start now* items are ranked in that order; within each, the item
that unblocks the most open items first, then plan order. *Command* holds the basstler
command for the step, and *Session* a link that opens a Claude Code session on the code
repository with that command typed in. Each item issue carries the same step, reason and
link at its top. Set the repository variable `CLAUDE_ENVIRONMENT` to an environment's name
to open the sessions there.

A push to `main` runs both. Every change to a sandbox issue (opened, edited, labelled,
closed, reopened) runs the sync, so the project follows the issues within a minute or
so. Reordering sub-issues, changing *blocked by*, and reviews, CI and merges in the code
repository start no run; the next run picks them up, or press *Refresh now* in *Up next*.
*sync-only* and *import-and-sync* can also be started from the Actions tab, where
*recreate_views* rebuilds the three views.

## Working with it

- Change an item's status: swap its `status:*` label, or close it; the project follows.
- Add an item: use the *Add work to this plan* prompt in the plan issue.
- Turn an experimental branch into items: use the *Split an experimental branch* prompt.
- Continue an item: copy the *Continue this item* prompt from its issue into a session.
