$marker
- **Branch:** $branch
- **Pull request:** $pull_request
- **Blocked by:** $blocked_by
- **Last session:** $session

### Notes
$notes

### Blockers
$blockers

### Prompts to copy
Continue this item:
```text
Work on $repository#$number. Read it, its parent plan issue and the issues it is blocked by, then continue on its branch and pull request. When its state changes, update its status:* label and rewrite its Notes to what is true now.
```
With basstler as it is today:
```text
/plan-item-kickoff $plan_identifier $item_identifier
```
