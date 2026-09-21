---
name: comet-classic-archive
description: "Use only when explicitly invoked as /comet-classic-archive or routed by the comet-classic entry/runtime to the archive Node; complete Archive for comet-classic. Do not use for ordinary standalone tasks or as the workflow entry."
---

# Archive

## Node Goal

Complete the `archive` Node for `comet-classic`.

Responsibility: Archive the OpenSpec change and sync completed deltas back to the main specs.

## Guidance

This Node delegates to `comet-archive`. Load that Skill, apply the Required Skill Calls below, and record the Output Schema evidence before running the Exit Check. Do not duplicate the delegate Skill's body here.

## Entry Check

```bash
node comet-classic/scripts/workflow-guard.mjs entry archive
```

## Skill Implementation

Load `comet-archive` for this Node. Operation: `default`.

## Required Skill Calls

- This Node has no extra required Skill calls.

## Augmentations

- This Node has no declared augmentations.

## Output Schemas

- `comet.archive.v1`: OpenSpec archive and delta sync result. Required evidence: `archive-summary`, `archived-state`. Required artifacts: none.

## Evidence Record

```bash
node comet-classic/scripts/workflow-state.mjs record archive '{"summary":"record the real Node result","completedChecks":[]}'
```

## Guardrails

- `archive-state`: Archive state recorded (state-transition).

## Exit Check

```bash
node comet-classic/scripts/workflow-guard.mjs exit archive --apply
```

If the script prints `NEXT: done`, summarize the workflow evidence and stop.

## Recovery

Read `reference/workflow-protocol.json` and the configured workflow state. Resume the first Node that is not listed in `completedNodes`.
