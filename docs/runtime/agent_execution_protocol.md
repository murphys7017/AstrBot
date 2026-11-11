# Agent Execution Protocol

This protocol defines how Codex, OpenCode, Claude Code, Cursor, and similar coding agents should execute tasks under this governance runtime.

It is the agent-readable bridge between the project philosophy and day-to-day repository work.

## Product Layers

The project has three intended layers:

1. Human-readable governance spec
   - Explains the engineering-cybernetics principles behind the runtime.
   - Lives mainly in `AGENTS.md`, `.ai/index.md`, and the current project documentation.

2. Agent-readable runtime protocol
   - Defines how an agent should classify, route, execute, review, and report work.
   - Lives in `AGENTS.md`, `.ai/index.md`, `.ai/state.yaml`, and this document.

3. Future machine-readable control layer
   - Intended for scripts, MCP servers, CI checks, or adapter tooling that can validate governance behavior.
   - v1 does not require autonomous enforcement, but policy YAML and evaluation schemas should remain compatible with later tooling.

## Required Agent Loop

For any non-trivial task, the agent should run this loop:

1. Load the entry point.
   - Read `AGENTS.md`.
   - Read `.ai/index.md`.
   - For resumed or long-running work, re-check scope, assumptions, validation, and user changes using the continuity guidance in `AGENTS.md` and `.ai/index.md`.

2. Route the task.
   - Classify the task using the task classes and risk levels in `AGENTS.md` and `.ai/index.md`.
   - Identify the task objective, success criteria, and non-goals when they affect execution.

3. Load only the selected material.
   - Load the selected policies, workflow, skills, checklists, evaluation files, and state files.
   - Avoid loading unrelated governance files unless the user requests a broader review.

4. Execute the selected workflow.
   - Follow the workflow's required loop.
   - Keep the change bounded to the requested task.
   - Preserve architecture and user changes unless explicitly instructed otherwise.
   - Run a continuity checkpoint when scope, risk, context, validation status, or user intent changes.

5. Maintain explicit state when required.
   - Update `.ai/state.yaml` only when scope, risk, architecture impact, assumptions, or validation status would otherwise be hidden.

6. Apply checklists and evaluation.
   - Apply required checklists before completion.
   - Apply `checklists/objective_satisfaction.md` when the requested objective, success criteria, or non-goals affect completion.
   - Apply `checklists/continuity.md` when execution has been long-running, multi-turn, interrupted, or resumed.
   - Use the evaluation schema when evaluation is required or useful.
   - Report validation gaps honestly instead of implying full verification.

7. Report completion.
   - Summarize the task class, risk level, work performed, validation status, and remaining risks when relevant.
   - Do not claim full completion when required corrections remain.

## Adapter Responsibilities

Each adapter in `.ai/adapters/` should preserve the same control loop while translating it into runtime-specific guidance.

Adapters should specify:

- required load order
- router usage
- selected workflow execution
- state update expectations
- checklist and evaluation expectations
- fallback behavior when the agent cannot update files or run validation

Adapters should not duplicate the whole governance system. They should point agents back to the router and selected runtime files.

## Degraded Execution

If an agent cannot perform part of the protocol, it should degrade explicitly:

- If it cannot update state, report the state update that would have been made.
- If it cannot run validation, report the validation gap.
- If it cannot inspect a required file, report the missing context and reduce confidence.
- If task risk is unclear, choose the higher plausible risk level.

## Completion Standard

A task is complete only when:

- the requested objective is satisfied or the remaining gap is explicit
- the selected workflow exit conditions are satisfied or the unresolved boundary is explicit
- required checklists have been applied
- validation status is known
- residual risk is visible
- no required correction remains unaddressed
