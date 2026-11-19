# Changelog

Every change a reader should know about, newest first.

## 0.1.0 - 2026-11-19

- First version: the fleet view (every Herdr space, its agents and their
  state, and each machine's load, RAM, disk and programs by RAM) and the
  token economy (today's spend per space, per agent and per hour, from
  Claude Code transcripts, with levers).
- RAM per program is each process's own memory plus the largest shared part,
  not a plain sum of RSS.
- Each model call counts once, by its message id; a subagent's spend goes to
  the agent that started it.
- A live view is cut to its pane from the bottom, so its header and the
  "Needs you" line stay on screen; the last row says how much was cut.
- A model with no price in the config is named under the token pane, with
  how many of its calls were left out.
- Steps 5 to 7 of PLAYBOOK.md are safe to run twice, "After a restart" starts
  the views again, and Undo closes only the Fleet tab these steps made.
- Tested with Herdr 0.9.5 (snapshot API protocol 22), Python 3.11 and 3.14,
  and the remote probe with Python 3.9.
