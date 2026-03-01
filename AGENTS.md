# Workspace Safety Rules (Ubuntu Workspaces)

These rules are mandatory for any browser/UI automation in this repository.

1. Never move existing windows between Ubuntu workspaces.
2. Never reuse or retarget windows that were opened in another workspace.
3. Only open new windows for tests in the current active workspace.
4. If the action cannot guarantee workspace isolation, stop and ask before continuing.
5. Use the requested Chrome profile (for example `diego`) only by opening a new window/tab in the current workspace, without touching other workspace windows.
6. Forbidden: any command/action that changes a window's workspace (for example `wmctrl -t`, workspace move helpers, or equivalent).
7. If a window was opened in another workspace by mistake, never move it; leave it there and continue only in the current workspace.

# Human Chat Mode (Permanent)

When the user says "como humano en el chat" (or equivalent), this is mandatory:

1. Use the visible `Molbot Direct Chat` UI as the execution path.
2. If it is already open, use that window/tab; if not, open it.
3. Type and send commands in the chat exactly as a human would.
4. Prefer real UI input/send behavior over internal shortcuts/APIs.
5. This mode is used specifically to test real interface behavior and detect UI failures.

# Lucy Validation Rule (Permanent)

When the goal is to verify whether **Lucy** can perform an action in `dc` (for example search/open/play flows), this is mandatory:

1. Do **not** execute the target chat command yourself as the agent.
2. Ask Lucy to run the command in `Molbot Direct Chat`.
3. Use Lucy's real outcome (success/failure) as the source of truth for debugging.
4. After Lucy runs it, you may inspect logs/history/events/windows to diagnose and fix issues.
5. Only run the command yourself if the user explicitly asks for an agent-run control test; otherwise first ask permission and explain briefly why.

# User Aliases (Permanent)

Interpret these aliases as fixed terms in this repository:

1. `cunn` => `Cunningham` (the project's AI).
2. `dc` => `Molbot Direct Chat`.
