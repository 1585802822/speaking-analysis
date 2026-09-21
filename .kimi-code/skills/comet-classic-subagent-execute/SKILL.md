---
name: comet-classic-subagent-execute
description: "Use only when explicitly invoked as /comet-classic-subagent-execute or routed by the comet-classic entry/runtime to the subagent-execute Node; complete Subagent Execute for comet-classic. Do not use for ordinary standalone tasks or as the workflow entry."
---

# Subagent Execute

## Node Goal

Complete the `subagent-execute` Node for `comet-classic`.

Responsibility: Delegate implementation work and require auditable returned evidence.

## Guidance

This Node delegates to `subagent-driven-development`. Load that Skill, apply the Required Skill Calls below, and record the Output Schema evidence before running the Exit Check. Do not duplicate the delegate Skill's body here.

## Entry Check

```bash
node comet-classic/scripts/workflow-guard.mjs entry subagent-execute
```

## Skill Implementation

Load `subagent-driven-development` for this Node. Operation: `default`.

## Required Skill Calls

- This Node has no extra required Skill calls.

## Augmentations

- This Node has no declared augmentations.

## Output Schemas

- `comet.handoff.v1`: Subagent handoff request and returned evidence. Required evidence: `handoff-request`, `handoff-result`. Required artifacts: none.

## Evidence Record

```bash
node comet-classic/scripts/workflow-state.mjs record subagent-execute '{"summary":"record the real Node result","completedChecks":[]}'
```

## Guardrails

- `handoff-evidence`: Handoff evidence recorded (evidence-only).

## Exit Check

```bash
node comet-classic/scripts/workflow-guard.mjs exit subagent-execute --apply
```

If the script prints `SKILL: comet-classic-review`, load that Skill next.

## Recovery

Read `reference/workflow-protocol.json` and the configured workflow state. Resume the first Node that is not listed in `completedNodes`.
