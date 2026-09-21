---
name: comet-classic-verify
description: "Use only when explicitly invoked as /comet-classic-verify or routed by the comet-classic entry/runtime to the verify Node; complete Verify for comet-classic. Do not use for ordinary standalone tasks or as the workflow entry."
---

# Verify

## Node Goal

Complete the `verify` Node for `comet-classic`.

Responsibility: Run verification, reconcile branch state, and decide whether completion is valid.

## Guidance

This Node delegates to `comet-verify`. Load that Skill, apply the Required Skill Calls below, and record the Output Schema evidence before running the Exit Check. Do not duplicate the delegate Skill's body here.

## Entry Check

```bash
node comet-classic/scripts/workflow-guard.mjs entry verify
```

## Skill Implementation

Load `comet-verify` for this Node. Operation: `default`.

## Required Skill Calls

- This Node has no extra required Skill calls.

## Augmentations

- This Node has no declared augmentations.

## Output Schemas

- `comet.verify.v1`: Comet verification evidence and branch handling. Required evidence: `verification-commands`, `verification-result`. Required artifacts: none.

## Evidence Record

```bash
node comet-classic/scripts/workflow-state.mjs record verify '{"summary":"record the real Node result","completedChecks":[]}'
```

## Guardrails

- `verify-result`: Verification result recorded (evidence-only).

## Exit Check

```bash
node comet-classic/scripts/workflow-guard.mjs exit verify --apply
```

If the script prints `SKILL: comet-classic-archive`, load that Skill next.

## Recovery

Read `reference/workflow-protocol.json` and the configured workflow state. Resume the first Node that is not listed in `completedNodes`.
