---
name: comet-classic-open
description: "Use only when explicitly invoked as /comet-classic-open or routed by the comet-classic entry/runtime to the open Node; complete Open for comet-classic. Do not use for ordinary standalone tasks or as the workflow entry."
---

# Open

## Node Goal

Complete the `open` Node for `comet-classic`.

Responsibility: Intake the user request, choose the change shape, and initialize Comet state.

## Guidance

This Node delegates to `comet-open`. Load that Skill, apply the Required Skill Calls below, and record the Output Schema evidence before running the Exit Check. Do not duplicate the delegate Skill's body here.

## Entry Check

```bash
node comet-classic/scripts/workflow-guard.mjs entry open
```

## Skill Implementation

Load `comet-open` for this Node. Operation: `default`.

## Required Skill Calls

- This Node has no extra required Skill calls.

## Augmentations

- This Node has no declared augmentations.

## Output Schemas

- `comet.intake.v1`: Comet change intake and initial state. Required evidence: `intake-summary`. Required artifacts: `comet-state` at `changes/*/.comet.yaml`.

## Evidence Record

```bash
node comet-classic/scripts/workflow-state.mjs record open '{"summary":"record the real Node result","completedChecks":[]}'
```

## Guardrails

- `comet-state-created`: .comet.yaml exists (state-transition).

## Exit Check

```bash
node comet-classic/scripts/workflow-guard.mjs exit open --apply
```

If the script prints `SKILL: comet-classic-design`, load that Skill next.

## Recovery

Read `reference/workflow-protocol.json` and the configured workflow state. Resume the first Node that is not listed in `completedNodes`.
