# Fleet view: the playbook

This file is written for a coding agent (Claude Code, Codex, Grok) and is
readable by a person. Do the steps in order. Each step is one action, a
"Verify:" command and the result to expect. Stop at the first result that
does not match and report what you saw. This is called a verification loop:
a step that is checked before the next one starts never carries a broken
state forward.

Every command runs from the top folder of this repo, in a pane of the Herdr
session the tab should go to. Herdr calls a space a workspace; its ids look
like `w1` (a workspace), `w1:t2` (a tab) and `w1:p3` (a pane).

## Goal

The Herdr workspace you work in has a tab named `Fleet`. Its left pane shows
every space, every agent's state and every machine's load; its right pane
shows what the agents spent today. Both refresh on their own and only read.

## Before you start

| Need | Check | Expected | If it fails |
|---|---|---|---|
| You run inside a Herdr pane | `test "${HERDR_ENV:-}" = 1 && echo inside` | `inside` | Stop. Open Herdr, open a pane in this repo's folder and start there: the steps add a tab to the session you run in. |
| Herdr 0.9.5 or newer, on this shell's PATH | `herdr --version` | `herdr 0.9.5` or a newer version | Install or update Herdr (`herdr update`, or herdr.dev). On `command not found`, add Herdr's folder to the PATH in your shell's startup file and open a new pane: the steps run `herdr` by name. |
| Python 3.11 or newer | `python3 -c 'import sys; print(sys.version_info >= (3, 11))'` | `True` | Install a newer Python from python.org or your package manager. |
| You are in this repo | `test -f src/fleet_view.py && echo here` | `here` | `cd` into the clone of this repo. |
| No tab is labelled `Fleet` yet | `python3 src/herdr_state.py find tab Fleet; echo "exit $?"` | `find: 0 tabs are labelled 'Fleet'; expected 1` and `exit 1` | If an earlier run of this playbook made it (its panes are labelled `fleet` and `tokens`), see "After a restart" or "Undo". Else stop and ask the person to rename their tab: Undo closes the tab labelled `Fleet`, so it must be the one these steps make. |
| Claude Code logs, for the token pane | `test -d ~/.claude/projects && echo logs` | `logs` | The token pane will show $0.00. That is fine if you use other agents; see "Adapt it". |

## Steps

### 1. Run the demo on the synthetic data

This shows what the views do before anything on your machine changes. The
demo reads a saved Herdr snapshot, saved machine readings and made-up
transcripts from `examples/demo/`, with a fixed clock.

```bash
bash examples/run.sh
```

Verify: `bash examples/run.sh | diff - examples/expected-output.txt && echo same`
Expected: `same`

### 2. Run the gate

The tests run offline on the same synthetic data. The scrub warns when you
have no deny-list; that is fine for a reader.

```bash
./check.sh
```

Verify: `./check.sh 2>/dev/null | tail -n 1`
Expected: `check: ok`

### 3. Copy the config

All settings live in one file: the machines, the prices, where the logs are.
`test -f ... ||` copies only when there is no config yet, so the step never
overwrites yours and is safe to run twice. (`cp -n` would do the same, but
some versions of GNU cp exit 1 when they skip a file, and that looks like a
failure.)

```bash
mkdir -p ~/.config/playbook-herdr-fleet-view
test -f ~/.config/playbook-herdr-fleet-view/config.toml || cp examples/config.example.toml ~/.config/playbook-herdr-fleet-view/config.toml
```

Verify: `python3 src/fleet_view.py fleet --once | head -n 1 | cut -c 1-5`
Expected: `Fleet`

### 4. Read both views once

`--once` prints a view and exits. Look at it: your spaces and agents should be
there, and this machine's load.

```bash
python3 src/fleet_view.py fleet --once
python3 src/fleet_view.py spend --once
```

Verify: `python3 src/fleet_view.py fleet --once | grep -c 'Herdr gave no spaces' || true`
Expected: `0`. (`grep -c` exits 1 when it counts nothing; `|| true` keeps
that from looking like a failure.) If it prints `1`, the line in the view
says why.

When it says `'herdr' was not found`, Herdr is not on this shell's PATH:
fix that as in "Before you start". The config's `[fleet] herdr` alone is not enough,
because steps 5 to 7 and `src/herdr_state.py find` run `herdr` by name. Any
other reason, such as `herdr:` and a connection error, means this shell
cannot reach the Herdr server: an agent's sandbox can block it. Stop and
tell the person; the step may need to run outside the sandbox.

### 5. Make the Fleet tab and start the fleet pane

One command line, in three parts. `herdr tab create` makes the tab and answers
in JSON; Python takes the id of the tab's first pane from it. `herdr pane
rename` labels that pane `fleet`, so the next steps can find it by name (a
shell variable does not live from one step to the next in most agents'
shells). `herdr pane run` types the command into the pane's shell.

```bash
pane=$(herdr tab create --workspace "$HERDR_WORKSPACE_ID" --label Fleet --cwd "$PWD" --no-focus | python3 -c 'import json,sys; print(json.load(sys.stdin)["result"]["root_pane"]["pane_id"])') && herdr pane rename "$pane" fleet >/dev/null && herdr pane run "$pane" "python3 src/fleet_view.py fleet" >/dev/null && echo "started in $pane"
```

Verify: `herdr pane read "$(python3 src/herdr_state.py find pane fleet)" --source visible | grep -c '^Fleet '`
Expected: `1`

### 6. Split it to the right for the token pane

`--ratio 0.55` keeps 55% of the width for the fleet pane, the pane that is
split; the token pane gets the rest.

```bash
pane=$(herdr pane split "$(python3 src/herdr_state.py find pane fleet)" --direction right --ratio 0.55 --cwd "$PWD" --no-focus | python3 -c 'import json,sys; print(json.load(sys.stdin)["result"]["pane"]["pane_id"])') && herdr pane rename "$pane" tokens >/dev/null && herdr pane run "$pane" "python3 src/fleet_view.py spend" >/dev/null && echo "started in $pane"
```

Verify: `herdr pane read "$(python3 src/herdr_state.py find pane tokens)" --source visible | grep -c '^Token economy'`
Expected: `1`

### 7. Optional: an agent under the token pane that reviews the spend

Ask the person first: this starts a coding agent, and an agent spends tokens.
It gives the right side a second pane, where the person asks an agent to read
the numbers and judge them. Use the command of the agent the person uses
(`claude`, `codex`, `grok`).

```bash
pane=$(herdr pane split "$(python3 src/herdr_state.py find pane tokens)" --direction down --ratio 0.6 --cwd "$PWD" --no-focus | python3 -c 'import json,sys; print(json.load(sys.stdin)["result"]["pane"]["pane_id"])') && herdr pane rename "$pane" ask >/dev/null && herdr pane run "$pane" "claude" >/dev/null && echo "started in $pane"
```

Then the person types this into that agent, when they want a review:

```text
Run python3 src/fleet_view.py spend --json and tell me the three changes that
would cut the most spend, with the numbers behind each. Change nothing, and
type into no other pane.
```

Verify: `python3 src/herdr_state.py find pane ask`
Expected: one pane id, such as `w2:p4`.

### 8. Optional: add a machine you reach over ssh

The view sends `src/machine.py` to the machine on stdin and reads JSON back,
so nothing is installed there. It needs a login with a key (the view never
waits for a password) and `python3` 3.9 or newer on that machine. Add a table
to the config, with the alias from your `~/.ssh/config`:

```toml
[[machines]]
name = "build-box"
ssh = "build-box"
```

Verify: `python3 src/fleet_view.py fleet --json | python3 -c 'import json,sys; print([m["name"] for m in json.load(sys.stdin)["machines"] if m["ok"]])'`
Expected: a list with `local` and the name you added. A machine that does not
answer shows its reason in the fleet pane: test the login with
`ssh -o BatchMode=yes build-box python3 --version`.

## Adapt it

| Setting | Where | Example |
|---|---|---|
| The machines | config, one `[[machines]]` table each | `name = "build-box"` and `ssh = "build-box"` |
| Prices | config, `[prices.<key>]`; the longest key found in the model name wins. A key covers every name that holds it: `opus-5` also matches `claude-opus-5-5`. A model with no key is named under the token pane | `[prices."opus-5"]` for Opus 5, with `[prices."opus-5-5"]` next to it so Opus 5.5 keeps its own price |
| When "today" starts | config, `[spend] day_start` | `day_start = "06:00"` |
| Where the logs are | config, `[spend] logs` | `logs = ["~/.claude/projects", "/srv/agents/.claude/projects"]` |
| The lever lines | config, `[spend] big_context` and `rebuild_share` | `big_context = 150000`, `rebuild_share = 0.25` |
| How often each pane redraws | config, `[fleet] interval` and `[spend] interval` | `interval = 5` |
| Programs shown per machine | config, `[fleet] top_programs` | `top_programs = 5` |
| The Herdr command the views run | config, `[fleet] herdr`; the steps use `herdr` from the PATH | the full path from `command -v herdr`, for a pane whose PATH has no Herdr |
| Which workspace gets the tab | `--workspace` in step 5 | a `workspace_id` from `herdr workspace list` |
| Pane sizes | `--ratio` in steps 6 and 7 | `--ratio 0.6` keeps 60% for the pane that is split |
| Another agent's logs | `src/spend.py`: a reader that builds `Call` records, like `calls_in` | a reader for Codex's session logs, with `READER_KIND = "codex"` |
| A different config file | `--config` on each command | `python3 src/fleet_view.py fleet --config ~/fleet-home.toml` |

Two notes for the config. A top-level key such as `clock` goes before the
first `[table]`: TOML files every key after a table header under that table.
And `clock` is only for the demo and the tests; leave it out.

## Done when

- `./check.sh` prints `check: ok`.
- `python3 src/herdr_state.py find tab Fleet` prints one tab id.
- `herdr pane read "$(python3 src/herdr_state.py find pane fleet)" --source visible | grep -c '^Fleet '` prints `1`.
- `herdr pane read "$(python3 src/herdr_state.py find pane tokens)" --source visible | grep -c '^Token economy'` prints `1`.
- The person looked at the Fleet tab and saw their own spaces and agents in it.

## Undo

Closing the tab ends the programs in its panes (measured with Herdr 0.9.5:
both views ended). If step 7 started an agent there, closing the tab ends that
agent's session too, so ask the person first.

```bash
tab=$(python3 src/herdr_state.py find tab Fleet) && python3 src/herdr_state.py find pane fleet --tab "$tab" >/dev/null && herdr tab close "$tab"
rm -r ~/.config/playbook-herdr-fleet-view
```

The first line closes the tab only when it holds the pane labelled `fleet`,
so a tab these steps did not make is never closed. If it prints
`find: 0 panes are labelled 'fleet'; expected 1`, the tab labelled `Fleet`
is not this playbook's: stop and ask the person.

Verify: `python3 src/herdr_state.py find tab Fleet; echo "exit $?"`
Expected: `find: 0 tabs are labelled 'Fleet'; expected 1` and `exit 1`.
Then delete the clone of this repo if you do not want it any more.

## Safety

- Reads: one `herdr api snapshot` per refresh; on each machine `/proc/meminfo`,
  `/proc/uptime`, the load average, the disk use of `/`, and each process's
  name and RSS from `/proc/<pid>/status`; from the Claude Code transcripts,
  only the lines with token counts, and from them only the time, the folder,
  the session id, the model and the counts; the config file.
- Writes: nothing. The views print to their pane. The steps write the config
  file (step 3) and a tab with two or three panes (steps 5 to 7).
- Over ssh: one `python3 -` with the probe on stdin; it reads and prints JSON.
  `BatchMode=yes`, so it never waits for a password.
- Never: sends a message, calls a model, types into another pane, stops or
  signals a process, reads secrets or `.env` files, or prints what was said
  in a transcript. Only the optional agent of step 7 calls a model, and only
  when the person asks it something.
- Your screen: the views show your space names, pane labels, folder names and
  program names. So does `--json`. Treat a screenshot or a paste of them as you
  would treat your project list.
- The money is a yardstick: each call at the API list price in your config,
  not what your plan bills.
