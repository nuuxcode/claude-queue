# The behaviour suites

Every promise in [`docs/guarantees.md`](../../docs/guarantees.md) is made by one
of these. They drive a real Claude Code session on a pty, type into it the way a
person would, and read what actually happened off the screen or out of the
session transcript.

The checks that make a stock-behavior comparison run against an unpatched build
as well. They are gaps G2 and G6, reorder R5, and manage D6. The other checks
exercise only the patched behavior they claim.

## Running them

```bash
export CLAUDE_QUEUE_CONTROL=~/.claude-patch/backups/<the stock copy>
./test_markers.py
```

Both binaries are found for you if you do nothing:

| | how it is found |
|---|---|
| the build under test | first argument, else `$CLAUDE_QUEUE_BINARY`, else whatever `claude` resolves to |
| the unpatched control | `$CLAUDE_QUEUE_CONTROL`, else the newest stock copy saved in `~/.claude-patch/backups/` |

`./binaries.py` prints what it would use, and says exactly what is missing if it
cannot find one. Nothing is guessed: a suite with a control comparison refuses
to run without that control rather than reporting half a comparison.

Needs Python 3.9+ on macOS or Linux. Install the pinned dependencies with
`python3 -m pip install -r ../requirements.txt`.

**Every suite starts Claude with `--dangerously-skip-permissions` inside a
scratch workspace.** Read the driver before running it and do not point the
workspace at files you care about.

Each session also runs with `--safe-mode`, so the result does not depend on
your global hooks, instructions, settings, memory, plugins, MCP servers, or
agents. The driver removes its own UUID-named transcript and new empty history
directory when the session stops.

The two background-agent suites in `paused-mode/` are the exception, and they
have to be: `--safe-mode` disables agents, which is the thing they measure.
They use `paused-mode/freelab.py`, which drops safe-mode and then puts the rest
back off by hand with `--strict-mcp-config` and `--setting-sources project`, so
no MCP server loads and none of your own hooks fire inside the test. What comes
back is agents, plus your CLAUDE.md, which costs tokens and changes nothing
about queue behaviour.

Any check that needs the session transcript must read it before `lab.stop()`.
Stopping the session removes that UUID-named transcript. Reading it afterwards
produces missing evidence and a false failure.

**These cost real tokens.** Each suite opens several sessions and each session
runs a real turn, so the full set is a few minutes of wall clock and a few
minutes of model time on whatever `--model` you pass (default `haiku`).

## What each one covers

| suite | what it proves |
|---|---|
| `test_markers.py` | Every marker form, and near-misses that must NOT be treated as one. This includes "Queue depth", "Steer clear", "start the server", a bare "q", and a leading space |
| `test_mixed.py` | Waiting versus interrupting: what runs when, in what order, and both environment settings that put stock behaviour back |
| `test_edges.py` | Up with an empty queue still recalls history, the selector walk, labels off, and a shell command that starts with "q" surviving intact |
| `test_matrix.py` | The four cases written down as risky before they were tested, including the one where editing an `s` message silently downgraded it |
| `test_ux.py` | The labels, and that up alone highlights while enter pops exactly one |
| `test_gaps.py` | Slash commands while busy, six queued at once, a long wrapping message, escape, Ctrl-C against the control, vim mode, and pasted code that must remain literal |
| `test_reorder.py` | Moving a message, the highlight following it, the priority guard, and the one that matters: the transcript read back to prove the new order is the order that ran |
| `test_hard.py` | The three that needed their own driver: a message queued while a subagent runs, a queued message carrying a pasted image, and a submit fired at eight different offsets around the end of a turn |
| `test_manage.py` | Removing a message, every case where the delete key must do nothing, explicit colon-marked pasted batches, and Tab on prompts, slash commands, and shell commands |

### `paused-mode/`, added in 2.2.0

These cover parking, the mode arrows, and the three bugs this release fixes:
two that are in the released 2.1.0 and one in parking itself. They resolve their own binaries and workspace through
`paused-mode/paths.py`, so they need no arguments; override with
`CLAUDE_QUEUE_TEST_PATCHED`, `_STOCK`, `_SCRATCH` or `_WORKSPACE`.

Note the name clash: `paused-mode/test_matrix.py` is not the `test_matrix.py`
above. This one is the parking edge-case matrix.

| suite | what it proves |
|---|---|
| `test_matrix.py` | 30 checks over six sessions: parking while idle and while busy, the near-misses that must stay literal, the arrows, delete, a restart, the freeze on changing a mode, and both ways of letting go |
| `test_regress.py` | `q` and `s` are unchanged by all of the above |
| `test_isolation.py` | The three-terminal reproduction. One session's queue never reaches another, and each keeps its own file |
| `test_longpaste.py` | A long dictated paste starting `p ` parks instead of running, while pasted `q = deque()` stays one intact message |
| `test_bgagent2.py` | Whether a background agent holds the queue, typed and queued, against an unpatched control. It does not |
| `test_bgbash.py` | The same question for bash pushed back with ctrl+B. Also no |
| `test_escape.py` | Escape hands waiting messages back and leaves parked ones. Four of its seven checks fail on the build before the fix |
| `test_slash_model.py`, `test_immediate.py`, `test_model_now.py` | `/model` opening mid-turn, stock versus patched |

One post-audit regression is deliberately outside these real-session suites:
`tests/test_patch_def.py` executes the generated queue-edit JavaScript with a
non-editable shell command, task notification, metadata item, or non-human item
around the selected message. It checks the raw slot translation with and
without those entries. The live notification path has not been driven, so the
behavior-suite ledger now holds one hundred fifty-nine scenarios, 148 tested.

## The rule these were written under

Twenty-one distinct harness faults were found while building and auditing this, and fifteen of
them produced a red result on a build that was working. Two of them were the same
prompt. It said "count slowly to 90 with a sleep between each number", so the
model sometimes chose `sleep 0.1` and finished in nine seconds; once that was
pinned to an exact command, the model sometimes moved that command to the
BACKGROUND instead, and the turn ended in seven. Either way the session was idle
when the test typed into it, messages meant to queue ran instead, and three
suites reported an empty queue on a build that was fine. The prompt now says
foreground, wait for it to finish, do not background it.

So:

> **A red result is not a bug until the test is proven to exercise the thing it
> claims to.** Probe first, read the actual screen, then write the assertion.

Two helpers exist because of that rule. `expect_queue()` raises `SetupFailed`
rather than asserting on an empty queue, so a run that never reached the state
under test says so instead of reporting a failure. And every screen reading is
taken from the rendered screen through `lab.py`, never inferred from timing.

Setup drift exits nonzero by default because it proves nothing. Use
`--allow-setup-drift` only when you deliberately want drift reported without
failing the process, and rerun every named drift case before making a claim.

## Writing another one

Start from `probe`-style output before you assert anything: drive the session,
print the whole screen at each step, read it, and only then write the check.
Every one of the fifteen false red results above came from skipping that.
