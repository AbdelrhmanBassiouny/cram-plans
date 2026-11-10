# GitHub-native plans (sandbox)

A trial of keeping plans in GitHub itself instead of `plan.yaml` and the plan site, using
the five RDR plans. Nothing here touches `main`, the code branches, the
`claude/personal-notes` branch or basstler: `plan.yaml` stays as it is and basstler keeps
working from it.

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

A push to this branch runs both. After an issue changes, run *sync-only* from the Actions
tab or ask Claude to dispatch it. Issue events cannot start this workflow, because GitHub
starts `issues` workflows only from the default branch.

## Working with it

- Change an item's status: swap its `status:*` label (or close it), then sync.
- Add an item: use the *Add work to this plan* prompt in the plan issue.
- Turn an experimental branch into items: use the *Split an experimental branch* prompt.
- Continue an item: copy the *Continue this item* prompt from its issue into a session.
