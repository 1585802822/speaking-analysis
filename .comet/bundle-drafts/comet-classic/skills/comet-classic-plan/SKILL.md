---
name: comet-classic-plan
description: "Use only when explicitly invoked as /comet-classic-plan or routed by the comet-classic entry/runtime to the plan Node; complete Plan for comet-classic. Do not use for ordinary standalone tasks or as the workflow entry."
---

# Plan

## Node Goal

Complete the `plan` Node for `comet-classic`.

Responsibility: Create the executable implementation plan and task contract.

## Guidance

This Node delegates to `comet-build`. Load that Skill, apply the Required Skill Calls below, and record the Output Schema evidence before running the Exit Check. Do not duplicate the delegate Skill's body here.

## Entry Check

```bash
node comet-classic/scripts/workflow-guard.mjs entry plan
```

## Skill Implementation

Load `comet-build` for this Node. Operation: `default`.

## Required Skill Calls

- This Node has no extra required Skill calls.

## Augmentations

- This Node has no declared augmentations.

## Output Schemas

- `comet.plan.v1`: Comet executable implementation plan. Required evidence: `producer-summary`. Required artifacts: `implementation-plan` at `plans/*.md`.

## Evidence Record

```bash
node comet-classic/scripts/workflow-state.mjs record plan '{"summary":"record the real Node result","completedChecks":[]}'
```

## Guardrails

- `plan-artifacts`: Plan artifacts exist (artifact-structured).

## Exit Check

```bash
node comet-classic/scripts/workflow-guard.mjs exit plan --apply
```

If the script prints `SKILL: comet-classic-execute`, load that Skill next.

## Recovery

Read `reference/workflow-protocol.json` and the configured workflow state. Resume the first Node that is not listed in `completedNodes`.
