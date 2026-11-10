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
| The board | The user project *CRAM plans (GitHub-native sandbox)*, built from the issues |

Every issue this sandbox owns carries the `github-native-sandbox` label, so
`label:github-native-sandbox` finds them all and deleting them ends the trial.

## How it runs

The workflow `.github/workflows/github-native-plans.yml` has two steps:

1. **Import** (`import_plans.py`, runs with the workflow's own token): creates the issues,
   sub-issue links and dependencies that are missing. It never rewrites an existing issue
   unless `refresh_bodies` is set, so once imported the issues are the store.
2. **Sync** (`sync_project.py`, needs the `PROJECTS_TOKEN` secret): creates the project and
   its fields if missing, adds every sandbox issue and sets *Plan status*, *Track*,
   *Branch* and *Pull request* from the issue. It writes only values that differ, so it
   can be re-run at any time.

A push to `main` runs both. Every change to a sandbox issue (opened, edited, labelled,
closed, reopened) runs the sync, so the project follows the issues within a minute or
so. *sync-only* and *import-and-sync* can also be started from the Actions tab.

## Working with it

- Change an item's status: swap its `status:*` label (or close it), then sync.
- Add an item: use the *Add work to this plan* prompt in the plan issue.
- Turn an experimental branch into items: use the *Split an experimental branch* prompt.
- Continue an item: copy the *Continue this item* prompt from its issue into a session.
