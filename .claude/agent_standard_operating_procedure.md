# 🤖 Agentic Standard Operating Procedure (SOP)

## 🎯 Core Principles
- **Simplicity Over Cleverness**: Impact the minimal amount of code. Favor readability over "elegant" complexity.
- **Root Cause Resolution**: No temporary patches. Find why a bug exists and fix the source.
- **Zero-Handholding Autonomy**: Proactively resolve errors, CI failures, and logs without asking for permission, unless architectural integrity is at risk.

---

## 🏗️ Workflow Orchestration

### 1. The Planning Phase
- **Mandatory Planning**: Enter "Plan Mode" for any task involving >3 steps or architectural shifts.
- **State Tracking**: All plans must be written to `tasks/todo.md` with checkable items.
- **Stop-Loss Protocol**: If a plan fails twice or hits a logic wall, **STOP**. Re-evaluate the logs, update the `todo.md`, and check in with the user.

### 2. Subagent Strategy
- **Focused Execution**: Use subagents for parallel research, isolated exploration, or complex analysis to keep the main context clean.
- **Resource Awareness**: Avoid spawning subagents for trivial tasks. Ensure every subagent has a narrow, one-task scope.

### 3. Verification & Definition of Done
- **Proof of Work**: Never mark a task complete without demonstrating it works (logs, tests, or diffs).
- **The Staff Engineer Bar**: Before presenting a solution, ask: *"Is this production-ready, maintainable, and idiomatic?"*
- **Regression Check**: Ensure changes do not break existing functionality.

---

## 🧠 Memory & Lessons Management (`tasks/lessons.md`)

### 1. The Feedback Loop
- **Instant Update**: Immediately after any user correction or a failed attempt, update `tasks/lessons.md`.
- **Pre-Flight Review**: At the start of every session, read `tasks/lessons.md` to load project-specific constraints and past failures.

### 2. Lesson Structure
Entries must follow this pattern-matching format for high scannability:
- **[Pattern Name]**: Short descriptive title.
- **Context**: Where the issue occurred (e.g., "API Auth", "React Hooks").
- **Anti-Pattern**: What was done wrong (the "mistake").
- **The Correction**: The specific rule or "Staff" approach to take instead.
- **Verification**: The command or method to prove the mistake isn't repeated.

### 3. Hygiene & Archiving
- **De-duplication**: Every 5 lessons, consolidate similar patterns into "Super Rules."
- **Mastery**: Move patterns to the "Archived/Mastered" section after 5 consecutive successful implementations with zero regressions.

---

## 🛠️ Task Management Protocol

| File | Purpose | Management Rule |
| :--- | :--- | :--- |
| `.claude/tasks/todo.md` | Active State | Update progress in real-time. Include a `## Review` section at completion. |
| `.claude/tasks/lessons.md` | Long-term Memory | Mandatory update after any correction. Focus on patterns, not just incidents. |
| `.claude/tasks/spec.md` | Technical Truth | Define architecture here before coding non-trivial features. |

---

## ⚡ Autonomous Bug Fixing
- When a bug is reported, find the logs/errors immediately.
- Fix the issue autonomously if it aligns with the existing architecture.
- **Pre-emptive Strike**: If you see failing tests in the CI or local environment, fix them without being prompted.
- **Safety Valve**: If a fix requires changing a core API or project-wide pattern, present a brief trade-off analysis to the user before executing.