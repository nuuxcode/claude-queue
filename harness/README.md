# The harness

The numbers in the main README came out of this. It is here so you can check
them instead of believing them.

It answers one question: **what happens when you type a message while Claude
Code is already working?**

## What it does

It sends one job big enough to run for minutes (a small REST API across eight
files, with tests). While that job is running, it types two follow-ups. Each
follow-up asks for a file that does not exist yet, so "did it start this one"
is something you can see on screen rather than something to argue about.

```
add a CHANGELOG.md listing every endpoint with its method and path
add a metrics.py that counts how many times each endpoint was called
```

Then it reports, per run:

| | |
|---|---|
| **drift** | seconds from your message landing to Claude first touching the file it asked for |
| **order** | whether your two follow-ups ran in the order you typed them |
| **jumped** | whether a follow-up file was started before the original job wrote its own last file |

And across runs, which files each run produced. Identical input producing
different output is the same problem wearing a different hat.

The original prompt asks Claude to write `README.md` last. The "jumped" column
uses that file as a visible proxy for whether follow-up work began before the
original job finished, but the model still chooses its actual write order. If
`README.md` is never observed, the result says the proxy is unknown. A missing
follow-up is reported as `INCOMPLETE`, names the missing file, and makes
`measure.py` exit nonzero.

## Running it

Needs Python 3.9+ on macOS or Linux. Install the pinned driver dependencies:

```bash
python3 -m pip install -r requirements.txt
```

```bash
./record.py --binary "$(which claude)" --label stock
./measure.py runs/stock.json
```

To compare two builds, record both and measure them together:

```bash
./record.py --binary /path/to/other/claude --label patched
./measure.py runs/stock.json runs/patched.json
```

Every option `record.py` takes:

| option | required | default | what it does |
|---|---|---|---|
| `--binary` | yes | none | the claude executable to drive |
| `--label` | yes | none | name for this run. The result lands in `runs/<label>.json` |
| `--model` | no | `haiku` | which model the driven session uses |
| `--timeout` | no | `600` | seconds before the run is abandoned |

`measure.py` takes no options. Give it one or more run files:

```bash
./measure.py runs/stock.json                      # one run
./measure.py runs/stock.json runs/patched.json    # compared side by side
./measure.py runs/*.json                          # everything recorded so far
```

One thing to watch. If you have already installed this patch, `which claude`
finds the launcher, and the launcher starts a patched Claude Code. So that
command measures *your current setup*, which is usually what you want. To get a
genuinely unpatched side to compare against, run `claude-queue restore` first
and record that, or point `--binary` at a copy of the original, which is kept in
`~/.claude-patch/backups/`.

Each run takes a few minutes of wall clock and a few minutes of tokens on
whichever model you pass (`--model`, default `haiku`).

## Before you run it

**It runs Claude with permissions skipped**, inside a scratch directory it
creates next to this file. A demo that stops at a permission prompt measures
nothing. Read [`lab.py`](lab.py) first, it is around 200 lines and it is the
whole of what drives the session.

The driver starts Claude with `--safe-mode`. Your global instructions, hooks,
settings, memory, plugins, MCP servers, and agents are disabled. It assigns a
fresh session UUID and removes only that UUID's transcript when the driver
stops, including any new empty project-history directory. Your normal
authenticated home remains available, so no credential is copied into the
scratch workspace.

## Things this gets right that are easy to get wrong

**The follow-ups contain no ordering words.** Not "once the API is done", not
"after that". Writing those is queueing by hand inside the prompt, which is the
workaround the patch replaces. Put them in and stock Claude Code behaves
perfectly, and the run proves nothing. Four attempts at this demo failed that
way before anyone noticed the prompts were doing the work.

**It refuses to save a run where the follow-ups did not land mid-flight.** An
early version sent them on a fixed timer. The first job finished in 13 seconds,
so both "interruptions" arrived at an idle session with nothing to interrupt.
That recording was published before the mistake was spotted. Now a follow-up is
only sent while Claude is verifiably still working and the first turn has not
ended, and if that cannot be arranged the run is thrown away.

**It does not count turns.** Claude Code prints a banner when a turn ends
("Brewed for 1m 11s") and it looks like exactly the right signal. It scrolls out
of view within seconds, so a recording can show zero banners even when separate
turns provably happened. A turn counter built on it reported a working build as
broken. Everything measured here survives scrolling.

## Before publishing a GIF

On macOS, run the privacy OCR gate against every frame:

```bash
./audit_gifs.swift ../docs/images
```

Add project-specific private terms at runtime without writing them into the
repository: `GIF_PRIVACY_TERMS='term-one,term-two' ./audit_gifs.swift
../docs/images`.

It fails on home-directory paths, hook paths, hook messages, visible
account-login text, and any project-specific terms supplied at runtime. The
current 11 GIFs contain 317 frames and all pass. This check reads pixels, which
text grep cannot do.

## The runs behind the README

Two clean recordings: one stock and one patched, with the same job and the same
two follow-ups. Both ran with safe mode in neutral scratch workspaces.

```
run        file           typed  started  drift  ran in typed order    before README
stock-r2   CHANGELOG.md     15s     103s    88s  NO, it reordered you  no
stock-r2   metrics.py       46s      81s    35s                        YES
patched-r2 CHANGELOG.md     14s     129s   115s  yes                   no
patched-r2 metrics.py       42s     141s   100s                        no
```

Stock ran the two messages backwards. Patched ran them in the order they were
typed. The stock run also started `metrics.py` before the original job had
written its own `README.md`.

Honest limits: one machine, Haiku, Claude Code 2.1.220, and one clean run per
build. No explicit effort flag was set. The clips show the behavior changing in
the claimed direction and give you a reproducible path; the behavior suites,
not repeated demo timings, carry the deterministic claims. This is not a
benchmark.
