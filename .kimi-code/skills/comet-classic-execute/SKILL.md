---
name: comet-classic-execute
description: "Use only when explicitly invoked as /comet-classic-execute or routed by the comet-classic entry/runtime to the execute Node; complete Execute for comet-classic. Do not use for ordinary standalone tasks or as the workflow entry."
---

# Execute

## Node Goal

Complete the `execute` Node for `comet-classic`.

Responsibility: Apply the implementation plan through direct coordinator execution.

## Guidance

This Node delegates to `comet-build`. Load that Skill, apply the Required Skill Calls below, and record the Output Schema evidence before running the Exit Check. Do not duplicate the delegate Skill's body here.

## Entry Check

```bash
node comet-classic/scripts/workflow-guard.mjs entry execute
```

## Skill Implementation

Load `comet-build` for this Node. Operation: `default`.

## Required Skill Calls

- This Node has no extra required Skill calls.

## Augmentations

- This Node has no declared augmentations.

## Output Schemas

- `comet.execution-evidence.v1`: Comet build execution evidence and task completion. Required evidence: `implementation-summary`, `test-evidence`. Required artifacts: `task-state` at `changes/*/tasks.md`.

## Evidence Record

```bash
node comet-classic/scripts/workflow-state.mjs record execute '{"summary":"record the real Node result","completedChecks":[]}'
```

## Guardrails

- `build-complete`: Build evidence recorded (semantic).

## Exit Check

```bash
node comet-classic/scripts/workflow-guard.mjs exit execute --apply
```

If the script prints `SKILL: comet-classic-subagent-execute`, load that Skill next.

## Recovery

Read `reference/workflow-protocol.json` and the configured workflow state. Resume the first Node that is not listed in `completedNodes`.
