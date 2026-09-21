---
name: comet-classic-review
description: "Use only when explicitly invoked as /comet-classic-review or routed by the comet-classic entry/runtime to the review Node; complete Review for comet-classic. Do not use for ordinary standalone tasks or as the workflow entry."
---

# Review

## Node Goal

Complete the `review` Node for `comet-classic`.

Responsibility: Inspect the implementation with review Skills before verification.

## Guidance

This Node delegates to `requesting-code-review`. Load that Skill, apply the Required Skill Calls below, and record the Output Schema evidence before running the Exit Check. Do not duplicate the delegate Skill's body here.

## Entry Check

```bash
node comet-classic/scripts/workflow-guard.mjs entry review
```

## Skill Implementation

Load `requesting-code-review` for this Node. Operation: `default`.

## Required Skill Calls

- This Node has no extra required Skill calls.

## Augmentations

- This Node has no declared augmentations.

## Output Schemas

- `comet.review.v1`: Review or whitebox rule report. Required evidence: `review-summary`. Required artifacts: none.

## Evidence Record

```bash
node comet-classic/scripts/workflow-state.mjs record review '{"summary":"record the real Node result","completedChecks":[]}'
```

## Guardrails

- `review-evidence`: Review evidence recorded (evidence-only).

## Exit Check

```bash
node comet-classic/scripts/workflow-guard.mjs exit review --apply
```

If the script prints `SKILL: comet-classic-verify`, load that Skill next.

## Recovery

Read `reference/workflow-protocol.json` and the configured workflow state. Resume the first Node that is not listed in `completedNodes`.
