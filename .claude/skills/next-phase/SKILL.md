---
name: next-phase
description: Implement the next unchecked phase of PLAN.md (or the phase given as argument), verify it, commit it, and stop.
argument-hint: "[phase number, e.g. 2 or A1]"
disable-model-invocation: true
---

Implement one phase of the plan.

1. Read `CLAUDE.md`, `PLAN.md` and `docs/DECISIONS.md`. For a Milestone 2 phase (`A1`–`A4`), also read `docs/PLAN-API.md`, and only continue if the user explicitly started Milestone 2.
2. Pick the phase: `$ARGUMENTS` if given, otherwise the first phase in `PLAN.md` with unchecked boxes. Check that all earlier phases are ticked; if not, stop and say which one is missing.
3. Say in one or two lines which phase you are doing and what "Done when" requires.
4. Implement the phase exactly as written. If something in the plan is wrong or impossible, stop and explain before changing the design.
5. Run `pytest` (and `pytest -m live` only if the phase's "Done when" requires it). Fix until green.
6. Tick the phase's checkboxes in the plan file, check `git status` (no `data/`, `.env`, real exports or `*.db`), and make one commit named `Phase N: <title>`, with no mention of Claude in the message.
7. Write a short summary: what was done, test results, anything the user must try by hand (with exact commands), and open questions. Then stop. Do not start the next phase.
