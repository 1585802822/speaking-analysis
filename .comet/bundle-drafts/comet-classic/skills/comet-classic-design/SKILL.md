---
name: comet-classic-design
description: "Use only when explicitly invoked as /comet-classic-design or routed by the comet-classic entry/runtime to the design Node; complete Design for comet-classic. Do not use for ordinary standalone tasks or as the workflow entry."
---

# Design

## Node Goal

Complete the `design` Node for `comet-classic`.

Responsibility: Turn the confirmed request into design artifacts and OpenSpec delta context.

## Guidance

This Node delegates to `comet-design`. Load that Skill, apply the Required Skill Calls below, and record the Output Schema evidence before running the Exit Check. Do not duplicate the delegate Skill's body here.

## Entry Check

```bash
node comet-classic/scripts/workflow-guard.mjs entry design
```

## Skill Implementation

Load `comet-design` for this Node. Operation: `default`.

## Required Skill Calls

- Load `archify` during this Node and record completed check `required-skill:design.archify`. Reason: Generate architecture diagrams for the speaking analysis pipeline.

## Augmentations

- This Node has no declared augmentations.

## Output Schemas

- `comet.design.v1`: Comet design artifacts and OpenSpec delta context. Required evidence: `design-summary`, `user-confirmation`. Required artifacts: `design-doc` at `specs/*.md`; `delta-spec` at `changes/*/specs/*/spec.md`.

## Evidence Record

```bash
node comet-classic/scripts/workflow-state.mjs record design '{"summary":"record the real Node result","completedChecks":[]}'
```

## Guardrails

- `design-artifacts`: Design artifacts exist (artifact-structured).

## Exit Check

```bash
node comet-classic/scripts/workflow-guard.mjs exit design --apply
```

If the script prints `SKILL: comet-classic-plan`, load that Skill next.

## Recovery

Read `reference/workflow-protocol.json` and the configured workflow state. Resume the first Node that is not listed in `completedNodes`.
