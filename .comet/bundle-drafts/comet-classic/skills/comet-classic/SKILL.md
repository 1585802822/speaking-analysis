---
name: comet-classic
description: "Use when the user wants the comet-classic managed workflow for Create a project-specific comet-classic five-phase workflow Skill for building the daily speaking analysis tool, starting from the design Node, explicitly invokes /comet-classic, or persisted workflow state identifies one unambiguous active run. Route through this entry Skill; do not invoke its internal Node Skills directly."
---

# comet-classic

## Decision Core

## Decision Core

### Automatic Node Detection

On every invocation, start from disk state, not chat memory:

1. Run `node comet-classic/scripts/workflow-state.mjs status` to read the active Classic change and its current phase.
2. If no active change exists and the user gave a task, treat this as a fresh open → design → build → verify → archive workflow. Initialize the change through the `open` Node before reading `next`.
3. If an active change exists, trust the script's reported `phase` and `completedNodes` over conversation history. Context compaction may have discarded earlier state.
4. Resolve drift: if the user's message clearly belongs to a different Node than the script's `next` output (e.g., the script says `design` but the user is asking about test results), pause and ask which Node to enter. Do not silently override the script.
5. If the script reports a Node as DONE but its required artifacts or evidence are missing, re-enter that Node instead of advancing. File evidence is the source of truth.

### Decision Classification And Decision Points

Genuine user decisions that require a pause:

- **Change shape**: when opening a new change and more than one isolation mode (`current` / `branch` / `worktree`) is valid.
- **Scope confirmation**: when the user's request materially changes the accepted design, plan, or acceptance criteria after the design Node is complete.
- **Archive finish choice**: when archiving a branch/worktree change and multiple finish options exist (local merge, push, push+PR, keep).

Automatic handling (do not ask):

- Deterministic guard failures with a single repair path.
- `NEXT: auto` with one valid `SKILL:` output.
- Re-running a Node because required artifacts are missing.
- Loading the Node Skill returned by `workflow-state.mjs next`.

Stop conditions:

- The Comet CLI is not installed or returns invalid JSON.
- Multiple active Classic changes exist and the script cannot disambiguate.
- A Node guard fails with no deterministic recovery path.
- `workflow-state.mjs` returns `NEXT: manual` and the required input cannot be inferred from the user's message.

### Red Flags

| Agent thought | Actual risk | Correct response |
|---|---|---|
| "The user mentioned testing, so we should skip to verify." | Mentioning a topic does not change the current Node or completed artifacts. | Stay in the current Node unless the script's `next` output or a scope confirmation explicitly advances. |
| "The design artifact exists, so design is done." | The artifact may be a stale scaffold. | Check the evidence field and user-confirmation receipt, not just file existence. |
| "I can load multiple Node Skills at once to speed things up." | Violates single-Node progression and corrupts state. | Load only the one Skill returned by `workflow-state.mjs next`. |
| "Conversation memory says we are in build." | Context may have been compacted. | Re-read `workflow-state.mjs status` on every resume. |
| "The guard failed, so I'll retry the same action blindly." | May loop or miss a required user decision. | Diagnose the failure; if no deterministic fix exists, pause and ask. |

### Resume And Drift Rules

- **Re-detect from scratch**: on every context resume, re-run the Startup Protocol. Do not trust conversation history for current-Node detection.
- **Trust files over state**: if the script says a Node is DONE but its expected artifacts or evidence are missing, treat the Node as incomplete and re-enter it.
- **Drift handling**: if the user's request belongs to a different Node than the one returned by `next`, pause and confirm which Node to enter. Do not silently follow the script if the user's intent conflicts.
- **Redoing a Node**: if the user wants to redo a completed Node, reset its completion state and re-enter rather than creating a parallel path.


## Workflow Nodes

1. `comet-classic-open` - Open (control). Responsibility: Intake the user request, choose the change shape, and initialize Comet state. Output Schemas: `comet.intake.v1`.
2. `comet-classic-design` - Design (producer). Responsibility: Turn the confirmed request into design artifacts and OpenSpec delta context. Required Skills: `archify`. Output Schemas: `comet.design.v1`.
3. `comet-classic-plan` - Plan (producer). Responsibility: Create the executable implementation plan and task contract. Output Schemas: `comet.plan.v1`.
4. `comet-classic-execute` - Execute (control). Responsibility: Apply the implementation plan through direct coordinator execution. Output Schemas: `comet.execution-evidence.v1`.
5. `comet-classic-subagent-execute` - Subagent Execute (handoff). Responsibility: Delegate implementation work and require auditable returned evidence. Output Schemas: `comet.handoff.v1`.
6. `comet-classic-review` - Review (guardrail). Responsibility: Inspect the implementation with review Skills before verification. Output Schemas: `comet.review.v1`.
7. `comet-classic-verify` - Verify (control). Responsibility: Run verification, reconcile branch state, and decide whether completion is valid. Output Schemas: `comet.verify.v1`.
8. `comet-classic-archive` - Archive (control). Responsibility: Archive the OpenSpec change and sync completed deltas back to the main specs. Output Schemas: `comet.archive.v1`.

## Skill Bindings

- `open`: implementation `comet-open` (default); required calls none; augmentations none.
- `design`: implementation `comet-design` (default); required calls `archify`; augmentations none.
- `plan`: implementation `comet-build` (default); required calls none; augmentations none.
- `execute`: implementation `comet-build` (default); required calls none; augmentations none.
- `subagent-execute`: implementation `subagent-driven-development` (default); required calls none; augmentations none.
- `review`: implementation `requesting-code-review` (default); required calls none; augmentations none.
- `verify`: implementation `comet-verify` (default); required calls none; augmentations none.
- `archive`: implementation `comet-archive` (default); required calls none; augmentations none.

## Guardrails And Evidence

- `open.comet-state-created`: .comet.yaml exists (state-transition).
- `design.design-artifacts`: Design artifacts exist (artifact-structured).
- `plan.plan-artifacts`: Plan artifacts exist (artifact-structured).
- `execute.build-complete`: Build evidence recorded (semantic).
- `subagent-execute.handoff-evidence`: Handoff evidence recorded (evidence-only).
- `review.review-evidence`: Review evidence recorded (evidence-only).
- `verify.verify-result`: Verification result recorded (evidence-only).
- `archive.archive-state`: Archive state recorded (state-transition).

## Workflow References

- Route, Output Schemas, required Skill calls, and recovery state: `reference/workflow-protocol.json`.
- Resolved source Skill evidence and composition provenance: `reference/resolved-skills.json`.

## Runtime And Recovery

### Startup Protocol

1. Run `node comet-classic/scripts/workflow-state.mjs status` to read the active Comet change state.
2. If there is no active Comet change, use `/comet-open` or the permanent `/comet-classic` entry to create or resume one.
3. Run `node comet-classic/scripts/workflow-state.mjs next` and load **only** the returned Skill. Do not load multiple Skills at once.

### Resume Rules (every context resume)

- **Re-detect from scratch**: on every context resume, re-run the Startup Protocol. Do not trust conversation history for current-Node detection — context compaction may have discarded critical state.
- **Trust files over state**: if the script says a Node is DONE but its expected artifacts or evidence are missing, treat the Node as incomplete and re-enter it. File evidence is the source of truth.
- **Drift handling**: if the user's request belongs to a different Node than the one returned by `next`, pause and confirm which Node to enter. Do not silently follow the script if the user's intent conflicts.

### Node Boundary Rules

- Before leaving a Node, run `node comet-classic/scripts/workflow-guard.mjs exit <node> --apply` to advance state and record evidence.
- If the guard fails, do not proceed — present the guard output and ask the user how to fix it.
- If the user wants to redo a completed Node, reset its completion state and re-enter rather than creating a parallel path.

The route, Output Schemas, required Skill calls, and recovery state are defined by `reference/workflow-protocol.json`.
