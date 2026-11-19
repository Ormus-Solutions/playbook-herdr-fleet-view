# Fleet view: what is going on, at a glance, plus the token economy

A Herdr tab that shows every space, every agent's state and every machine's
load on one screen, and next to it what the agents spent today.

## What it is

The tab has two panes, side by side. The left pane is the fleet view: every
Herdr space with its agents and their state (blocked, waiting, working,
idle), then each machine with its load, RAM, disk and the programs that hold
the most RAM. The right pane is the token economy: what the agents spent
today, per space, per agent and per hour, read from the agents' own usage
logs, with the changes that would cut it. The pattern is a read-only
dashboard over data that already exists. Herdr already knows each agent's
state, the kernel already counts each machine's load, and the agents already
log the tokens of every call. The view adds nothing to the agents and asks
nobody anything; it reads three sources on a timer and draws them. That is
why it is cheap to run all day and safe to leave open.

## What it saved me

In Ormus's words:

> Full fleet-view, great for on the glance "what is going on". The panes on
> the right are dedicated to reviewing token economy.

Two numbers measured on the server where his agents run, while this playbook
was written, show why the counting rules below matter: its Claude Code logs
held 1579 usage lines for 688 calls, so a sum over lines would have counted
the spend 2.3 times; and 380 shell processes had a plain RSS sum of 1.7 GiB
while holding 0.2 GiB of their own memory.

## Who it is for

- You run several coding agents in Herdr, in more than one space or on more
  than one machine, and you want to see which one needs you without opening
  each space.
- You pay for tokens, by the call or through a plan with limits, and you want
  to see which agents and habits cost the most.

Skip it if you run one agent in one terminal: Herdr's own screen is enough.
Skip the token pane if you need a bill: it prices each call at the API list
price, a yardstick, and your provider's usage page is the record.

## Requirements

| Tool | Version | Check |
|---|---|---|
| Herdr | 0.9.5 (tested; its snapshot API is protocol 22) | `herdr --version` |
| Python | 3.11 or newer, for the view | `python3 --version` |
| git | any recent version | `git --version` |
| Linux | for RAM and programs by RAM; macOS shows load and disk only | `uname -s` |
| Claude Code | only for the token pane's numbers; it writes the logs | `ls ~/.claude/projects` |
| ssh and python3 3.9+ on other machines | only to show other machines | `ssh -o BatchMode=yes <alias> python3 --version` |

## Quick start

### Hand it to your agent

Clone this repo, open your coding agent (Claude Code, Codex, Grok) inside a
Herdr pane in the clone, and paste this:

```text
Read PLAYBOOK.md in this repo and follow it step by step. After each step,
run its "Verify:" command and compare the result with "Expected:". If they
differ, stop and tell me what you saw. Ask me before any step that changes
something outside this repo, and before step 7 (it starts an agent). When you
finish, run the "Done when" checks and show me their output.
```

### Do it by hand

Run these in a Herdr pane, inside the clone:

1. See it work on the synthetic data: `bash examples/run.sh`.
2. Copy the settings and change them if you like (machines, prices):
   `mkdir -p ~/.config/playbook-herdr-fleet-view && cp -n examples/config.example.toml ~/.config/playbook-herdr-fleet-view/config.toml`
3. Try both views once: `python3 src/fleet_view.py fleet --once` and
   `python3 src/fleet_view.py spend --once`.
4. Make the tab and start the fleet pane in it: step 5 of PLAYBOOK.md (one
   command line).
5. Split it to the right for the token pane: step 6 of PLAYBOOK.md.
6. If you want an agent that reviews the spend with you, step 7.

To remove it, close the tab (`herdr tab close <tab id>`) and delete the
config folder. PLAYBOOK.md, "Undo", has the exact lines.

## Preview

The output of `bash examples/run.sh` on the synthetic data in
`examples/demo/` (four spaces, seven agents, three machines, seven
transcripts; every name in it is made up):

```text
Fleet  17:30:00   4 spaces, 7 agents: 1 blocked, 1 waiting, 2 working, 3 idle
Needs you: acme-web / build / web (blocked), acme-web / docs / docs (waiting)

Spaces
  acme-web       3 agents   1 blocked  1 waiting  1 working
    build / api              claude   working
    build / web              codex    blocked
    docs / docs              claude   waiting
  demo-api       2 agents   1 working  1 idle
    main / worker            claude   working
    main / review            claude   idle
  notes          1 agent    1 idle
    inbox / writer           grok     idle
  system         1 agent    1 idle
    Fleet / ask              claude   idle

Machines
  local         16 cores, up 3d04h
    load  ███░░░░░░░░░░░░░   20%   3.2 now, 2.5 over 15 min
    RAM   ██████░░░░░░░░░░   38%   24.5G of 64.0G, swap 1.0G used
    disk  ███████░░░░░░░░░   41%   758G of 1.8T
    RAM by program        own + shared once   plain RSS sum
      node x40                         1.1G            2.9G
      postgres x12                     632M            6.2G
      python3 x3                       390M            410M
  build-box     32 cores, up 12d01h
    load  ███████████░░░░░   67%   21.5 now, 12.4 over 15 min
    RAM   ████████████░░░░   77%   98.0G of 128G, no swap
    disk  ███████████████░   95%   1.9T of 2.0T
    RAM by program        own + shared once   plain RSS sum
      java x2                          8.8G            8.9G
      cc1plus x16                      2.8G            3.0G
      node x120                        2.6G            8.0G
  gpu-box       no answer: Connection timed out

Token economy  2026-01-15 00:00 to 17:30 UTC
API list prices: a yardstick, not a bill. Each call counted once.

  $4.59 today   51 calls   4.0M tokens read, 90% from the cache

By space          spend  share  calls  each hour from 00:00
  demo-api         $2.23    49%     19  ········██··█▄▂▅▅▅
  acme-web         $1.97    43%     25  ·········▇▅▆▂▂▄▅▆▃
  system           $0.05     1%      2  ················▁▁
  (no live pane)   $0.34     7%      5  ·······▄▃·········

By agent                    model     spend  calls  read/call  writes
  demo-api / main / worker  opus       $2.15     16        38k     42%
  acme-web / build / api    opus       $1.75     17       154k      4%
  acme-web / docs / docs    sonnet     $0.22      8        42k      6%
  demo-api / main / review  sonnet     $0.08      3        37k      8%
  system / Fleet / ask      sonnet     $0.05      2        19k     22%
  (no live pane) old-app    opus       $0.34      5        59k      8%
  read/call: tokens each call read. writes: their share written to the cache.

Levers
  - demo-api / main / worker: 42% of the tokens it read were cache writes, so
    its cache is rebuilt often (a pause longer than the cache lifetime, or a
    prompt start that changes).
  - acme-web / build / api: its last call read 218k tokens. /compact or /clear
    makes each next call cheaper.

Read 7 Claude Code transcripts. No reader yet for codex, grok, so their spend
is not shown.
```

## How it works

**One snapshot per refresh.** `herdr api snapshot` returns every workspace,
tab, pane and agent in one JSON answer. Herdr calls a space a workspace. The
view asks once per refresh, not once per space, so it stays fast with many
spaces. Herdr's agent states map to the four words of the view: `blocked`
(an approval or a question is on its screen), `done` shown as **waiting**
(it answered and nobody has looked yet), `working`, and `idle`. Blocked and
waiting agents are listed on the "Needs you" line, because those are the ones
that cost you time when nobody looks.

**The probe goes to the machine.** For another machine, the view sends
`src/machine.py` over ssh on stdin (`ssh <alias> python3 - 3`) and reads back
one JSON object. Nothing is installed there. A machine that stops answering
keeps its last card, marked with the time of that data, so a network blip
does not blank the screen.

**The memory-sum lesson.** RSS (resident set size) is the RAM a process
maps. It has three parts: its own memory (`RssAnon`), the program file and
libraries (`RssFile`), and shared memory (`RssShmem`). Forty copies of
`node` map the same program file, and twelve database workers map the same
shared buffers, so a plain sum of RSS counts those pages forty or twelve
times. On a busy machine the sum can be larger than the RAM the machine has.
The view sums each program's own memory and adds the largest shared part of
one of its processes; file pages are left out because they are the kernel's
page cache, which it can drop and read again. The demo shows both numbers
side by side: `postgres x12` holds 632M, while its plain RSS sum says 6.2G.
For one process, plain RSS is fine; the trap is only in the sum. If you need
the exact share of each process, `Pss` in `/proc/PID/smaps_rollup` splits
each shared page between the processes that map it, but it is readable only
for your own processes.

**Count each call once.** Claude Code writes one model call on several lines
of its transcript, one per content block, each with the same message id and
the same token counts. The token pane keys every call by its message id, so a
call counts once. A subagent writes its own file under
`<session>/subagents/`, with the parent's session id on each line, so its
spend goes to the agent that started it.

**Give each call to a pane.** A call goes to the live agent whose session id
Herdr knows; else to the one live Claude Code agent that works in the same
folder; else to a row for that folder: "(shared folder)" when two agents
work there, "(no live pane)" when none does (an ended session).

**A yardstick, not a bill.** Each call is priced at the API list price in
your config: input, output, cache reads, and cache writes for 5 minutes and
for 1 hour. With a plan, your real limit is the plan's, but the list price
still ranks agents and habits by cost. Two levers come from the numbers: a
live agent whose last call read more than 200k tokens (every next call reads
it all again: `/compact` or `/clear`), and an agent whose cache writes are
more than 30% of what it read (its cache is rebuilt often).

The code reads only numbers from the transcripts: the time, the folder, the
session id, the model and the token counts. It never keeps or prints what was
said.

## Files

| Path | What it is |
|---|---|
| `PLAYBOOK.md` | the steps, for an agent or a person |
| `src/fleet_view.py` | the program: both views, `--demo`, `--once`, `--json` |
| `src/herdr_state.py` | spaces and agents from `herdr api snapshot`; `find pane LABEL` |
| `src/machine.py` | the machine probe (also runs alone over ssh) and the memory sum |
| `src/spend.py` | the token economy: read, count once, price, attribute, levers |
| `src/config.py` | reads and checks the TOML config |
| `examples/config.example.toml` | the settings to copy and change |
| `examples/demo/` | the synthetic Herdr snapshot, machine readings and transcripts |
| `examples/run.sh`, `examples/expected-output.txt` | the demo and the text it must print |
| `tests/` | offline tests that pin the behaviour on the synthetic data |
| `check.sh` | the one gate: tests, placeholders, scrub |
| `scripts/scrub.sh` | the scrub check, copied from playbook-packaging |
| `CHANGELOG.md` | what changed, newest first |

## Credits

Made by Ormus (Ormus Solutions). Packaged with playbook-packaging by Ormus (Ormus Solutions). MIT license.
