# What this guarantees, and what it does not

A scheduler is only worth anything if you can say what it promises. This page
states the promises, the ones deliberately not made, and what was actually run
to check each one.

If you only read one line, read this one:

> **Changing how long a tool takes must not change which messages wait and which
> messages jump in.**

That is the property the current behaviour lacks, and it is the one thing here
that is true by construction rather than by testing.

---

## The two contracts

| | what it is | what it must do | what it must never do |
|---|---|---|---|
| **queue** | an ordering promise | stay invisible to the running turn, then run as its own turn afterwards, in order | leak into work already in flight |
| **steer** | a context promise | reach the running turn and change what it does, at the next safe boundary | wait quietly until the job is over |

They are not two settings of one thing. A queued message that becomes visible to
the active turn was not queued. A steering message that waits for the turn to end
did not steer.

**A message queue without a turn-boundary contract is not a queue. It is
deferred steering.** That distinction is the whole project.

---

## Why the classification cannot drift

The priority is decided **when you press enter**, from the marker you typed, and
stored on the command itself. Nothing later can change it.

```
you press enter
      |
      +--> marker read, priority fixed:  "later" (waits)  or  "next" (jumps in)
      |
      +--> message stored with that priority
                    |
   mid-turn collection   takes priority <= "next"   ->  a steer lands here
   end-of-turn drain     takes waiting messages of matching kind and
                         priority, one per turn      ->  a wait lands here
```

A `later` message fails the mid-turn filter every time, on a fast tool and a slow
one alike, because the filter tests the priority and not the clock. So tool
timing can change **where** a steer lands, which is expected and documented, but
it cannot change **whether** a message was a steer.

This is why the guarantee is structural rather than something to test for. There
is no code path in which a waiting message is examined mid-turn and kept or
dropped on a judgement call. It is not eligible.

---

## The state model

```
IDLE
  send                    -> starts a turn now

RUNNING
  no marker, or "q ..."   -> stored as a waiting message
  "s ..."                 -> stored as an interrupting message
  tab instead of enter    -> stored with the opposite timing to your
                             default; a marker still wins
  Escape, editor empty    -> stops the turn; waiting messages are kept and
                             the first one starts
  Escape while editing    -> stops the turn AND empties the whole queue into
                             the editor, joined, exactly like stock

NEXT TOOL BOUNDARY
  interrupting messages are collected here
  waiting messages are not eligible

WHILE MESSAGES WAIT
  up / down               -> move the highlight
  enter                   -> pull the highlighted one back to edit, alone
  shift+up / shift+down   -> move it earlier or later among its own kind
  delete / backspace      -> remove it, only when the editor is empty

TURN FINISHED
  the oldest waiting message starts, as its own turn
  one at a time, in the order shown on screen
```

---

## The promises

| # | promise | status | what was run |
|---|---|---|---|
| 1 | **A waiting message is invisible to the running turn** | kept | Six waiting messages typed into a long turn; none appeared in the transcript until that turn had finished |
| 2 | **Release happens at the true end of the turn**, not after a tool | kept, inherited | The session transcript shows queued messages arriving as separate user turns after the running turn closed, not between its tool calls |
| 3 | **Order is kept** | kept | Six distinct words queued, then read back out of the session transcript in the order typed |
| 4 | **Two waiting messages stay two turns** | kept | Stock merges consecutive queued prompts into one turn; here each runs alone, so the first one's result is on screen before the second starts |
| 5 | **Reordering changes the real run order**, not just the display | kept | Two messages queued, the second moved above the first, then the transcript read back to confirm the new order is the order that ran |
| 6 | **You can see what every waiting message will do** | kept | Every queued message carries `[waits]` or `[jumps in]` before it runs |
| 7 | **Editing one does not disturb the others** | kept | The edited message returns to its own slot, keeps its marker, and the rest stay queued and in order |
| 8 | **Interrupting messages still beat waiting ones** | kept | A steer typed after two waits still ran first |
| 9 | **Ordinary words are never eaten** | kept | Thirteen marker forms and near-misses in one session, including "Queue depth is high", "Steer clear of this", "start the server" and "queueing jobs". A bare "q" is driven separately in the risky-cases suite and stays a literal message |
| 10 | **Keys you already use still do the same job** | kept, with one visible consequence | Ctrl-C compared against an unpatched build and matched on every state checked. Escape interrupts the turn on both builds, and mid-edit Escape empties the queue into the editor, the stock shape, which the suite asserts (a hand probe against the control showed the same two effects). The visible difference comes at the end of an ordinary turn: stock hands the whole queue over at once, this starts the first waiting message and holds the rest |
| 11 | **Removing one message leaves the others alone** | kept | Three queued, the middle one highlighted and deleted; the other two keep their order and the highlight moves to the next one down |
| 12 | **The delete key never touches the queue while you are typing** | kept | With text in the editor, three backspaces edited the text and the queue was byte-identical afterwards |
| 13 | **A marker starts a message, an unmarked line continues the one above** | kept | Explicit pasted batches use `q:` and `s:`. Six shapes were driven, including continuation lines, mixed timing, blank lines and empty markers. Pasted code containing `q =` and `s =` was also driven and stayed one literal message |
| 14 | **Abandoning an edit does not misfile the next thing you type** | kept, and it was broken until it was tested | Three queued, the first pulled back, the editor cleared, then something new typed. Before the fix the new message landed at the FRONT, in the slot the old one had left |
| 15 | **Splitting works whether Claude is busy or idle** | kept, and it was broken until it was reported | Busy with an empty queue, busy with a full one, and idle. Idle used to arrive as a single message; the first job now becomes the turn and the rest queue behind it |
| 16 | **Tab is enter with the opposite timing, and a marker still wins** | kept | Driven against both defaults. Unset: enter waits, tab jumps in. With `CLAUDE_QUEUE_DEFAULT=steer`: enter jumps in, tab waits. An explicit marker still wins. Tab on slash and shell input was also driven, and the inversion did not leak onto the next prompt |
| 17 | **A non-editable queue item cannot shift where an edited message returns** | fixed in 2.0.1; deterministic regression green, live notification path not driven | The generated JavaScript was run with a shell command, task notification, metadata, and non-human entry around `[alpha, bravo]`. The 2.0.0 code returned edited `bravo` ahead of `alpha`; 2.0.1 translates the editable index to the raw queue index and preserves the raw order. The ordinary all-editable case also passes |

The stock-behavior comparisons run against an **unpatched control binary**.
Those are gaps G2 and G6, reorder R5, and manage D6. Other checks exercise only
the patched behavior they claim. A comparison that passes on both builds is not
evidence for a patch-specific change.

Where a fix corrected a real bug, the same test was run against the **previous
build** and watched to fail there. A test that passes everywhere proves nothing.

---

## The promises deliberately not made

### Claude is not told that a message was a steer

The marker is stripped before your text is sent, so nothing reaches the model
that you did not type. The cost is that the model cannot tell a mid-run
correction from an ordinary message.

This is a real trade and it went the other way on purpose: adding provenance
means injecting words you did not write into your own prompt. A patch that
quietly edits your messages is worse than one that omits a signal.

### There is no rejection channel

If an interrupting message cannot be applied, it simply stays queued until the
turn ends. It is not lost, and the label told you what it intended to do, but
nothing announces "this could not jump in after all".

Codex has a `rejected_steers_queue` for exactly this, and Hermes Agent falls back
to queue behaviour and says so. Both are better than what is here.

### What survives a restart, and what does not

Waiting messages survive. Every change to the queue is written to
`.claude/queue-<session-id>.json` in the project you are working in, and the
next session you start in that project brings them back as rows reading
`[waits, restored]`. Nothing runs until you send something yourself.

Two ways back, because there are two. `--continue` and `--resume <id>` keep
the session id, so the session finds its own file by name. The `/resume` menu,
which is also what picking a session out of a bare `claude` opens, does NOT
keep the id: it forks a new session, and the fork's id appears nowhere in the
saved file. So a session that finds no file of its own takes over the newest
one in this project instead: it rewrites the messages under its own id and
deletes the file it took them from, which is what stops the same messages
being offered again to every session that starts here afterwards.

The trade that comes with it, stated rather than hidden: two sessions live in
the same project, and the second one can take over the first one's file. It
cannot run any of them, the rows arrive marked `restored`, deleting them is
one key each, and the first session writes its file again on its next queue
change.

What does NOT survive, stated plainly, because half of persistence is knowing
where it stops:

- **A message already taken out of the queue to run.** It leaves the file at
  the moment it is dequeued. If the crash lands between that moment and the
  model seeing it, the message is gone; the other end of that trade is
  running something twice, and once is the safer mistake.
- **Anything in the editor.** A message you pulled back to edit has left the
  queue, and the input box is not saved.
- **Shell commands.** A queued `!command` is not saved on purpose: a shell
  command you typed yesterday should not run today because you resumed.
- **Images.** A message carrying a pasted image is not saved; restoring the
  words without the picture would lie about what the message was.
- **Where the highlight was.** The list returns in order, the cursor does not.
- **Anything in another project.** The file lives in the project directory,
  so a session resumed elsewhere never sees it, structurally.
- **Anything, if you turned it off.** `CLAUDE_QUEUE_PERSIST=off` restores the
  old behaviour completely: nothing written, nothing read.

A corrupt or half written file is ignored in silence and the session starts
clean: a queue file must never be able to stop Claude Code from starting.
Writes go to a temporary name and are renamed into place, so a crash during a
write leaves the old file or the new one, never half of one.

Escape with an empty editor does not clear it either: the turn stops and the
first waiting message starts immediately afterwards. Escape pressed while
EDITING a pulled-back message behaves like stock's cancel instead: the whole
queue is emptied into the editor, joined, and nothing runs until you send. That is the same shape as an unpatched build, where the whole queue
is delivered at once instead. If you want everything to stop, stop the turn and
then delete what is waiting.

### This is the terminal only

The patch changes the Claude Code executable on your machine. Desktop, the VS
Code extension, Remote Control and the SDK are untouched and keep their own
behaviour. 
### There is no pause

The community's full wish list is four operations: steer, queue, interrupt,
and pause, where pause means freezing the run with its state intact and
resuming later. This patch provides the first two and leaves interrupt as it
was. Pause does not exist here, and `Ctrl+Z` at the shell level is a process
suspension, not an agent-aware pause.

### It does not make Claude write better code

It makes the schedule predictable. Whether a predictable schedule produces better
output is a reasonable hypothesis and an untested one. The measurements in the
[README](../README.md) show ordering and timing, nothing about quality, and
that is deliberately as far as the claim goes.

### The model still does not know when you typed it

Two Claude Code issues,
[26388](https://github.com/anthropics/claude-code/issues/26388) and
[57624](https://github.com/anthropics/claude-code/issues/57624), describe a
failure this does not fix: you typed "also fix the tests" before reading the
answer on screen, and it arrives looking like a reply to that answer. Waiting for
the turn boundary makes the ordering predictable, which helps. The missing
temporal context is still missing.

---

## What is tested

One hundred twenty-one scenarios, listed in
[the scenario ledger](../harness/behaviour/SCENARIOS.md) with 112 of them
tested and every gap named in place, were written down **before** they were
tested, covering markers, queue mechanics, the selector, the keys, reordering,
removal, splitting, the tab key, the fold and persistence.

A later audit found one state shape that list missed: the selector counts only
editable messages, but enqueue splices the raw queue, which can also contain
shell commands, task notifications, metadata and non-human entries. That is
covered by a separate deterministic generated-JavaScript regression. It failed
on 2.0.0 and passes on 2.0.1, both with and without a non-editable item ahead of
the selected message. A live background-task notification landing mid-queue
has not been driven, so this is not counted as a seventy-ninth real-session
scenario.

Three of them needed a driver the rest of the suite does not have, and they were
the last to close:

| | how it was driven |
|---|---|
| A message queued while a **subagent** is running | Ask for a real subagent, queue during it, and check the message is still waiting twenty-five seconds later while the subagent is visibly still working. A subagent is a turn inside a turn, and the worry was that its completion looked like a turn boundary and released the queue early |
| A queued message carrying a **pasted image** | Put a real PNG on the system clipboard, send ctrl+v into the session, and check the image survives being queued. Anthropic's changelog fixed image loss in queued messages twice, at 2.1.72 and 2.1.105 |
| The turn ending **at the instant you press enter** | Cannot be aimed from outside the program, so the same submit is fired at eight different offsets around the end of a turn and the session transcript is read back each time. Delivered exactly once every time, never lost, never duplicated |

**That last one is a statistical result, not a deterministic one.** Eight attempts at eight offsets is evidence that the race
is not easy to hit, not proof that it cannot happen. A deterministic test would
need a hook inside the submit path, which would be testing the harness rather
than the build.

Writing the list first is what found the worst bugs in this patch, all of them
before anyone reported them:

- Editing a message marked `s` silently turned it into a waiting one, so an
  urgent interruption became "later" with nothing on screen saying so.
- The highlight tracked a row rather than a message, so a queue draining from the
  top left you pointing at a message you never picked.
- Abandoning an edit left the slot it came from still recorded, so the next
  thing you typed was filed into that gap. Pull the first of three back, change
  your mind, type something unrelated, and it arrived at the FRONT.

All three are fixed, and each fix was confirmed by running the same test against
the previous build and watching it fail there.

The third one is also a lesson about method. Its test had been passing, for the wrong
reason: it abandoned the edit by pressing Escape, and Escape stops the turn,
which releases the queue, so the state under test was gone before anything was
checked. A green test that never reaches the thing it claims to test is worse
than no test, because it also tells you not to look.

## The rule the testing runs on

Twenty-one distinct harness faults were found while building and auditing this, and **fifteen of
them produced a red result on a build that was working**. A selection: a spinner
pattern that never matched, a screen library that discarded scrollback, an
environment scrub that deleted the very flag under test, a relative path that
looked like a crash on boot, a chunked read that corrupted a line, a screen check
that found the transcript instead of the input box, a fake paste the input
treated as typing, a comparison read while both sides were still mid-flight, two
assertions still checking shapes from earlier releases, and a prompt that let the
model decide how long to stay busy. That last one twice: it sometimes chose a
tenth-of-a-second sleep and finished in nine seconds, and it sometimes moved the
command to the background and finished in seven, and either way every message
meant to queue ran instead.

Twenty of the twenty-one came from inferring state from a screen signal that had
never been verified. So:

> **A red result is not a bug until the test is proven to exercise the thing it
> claims to.** Probe first, read the actual screen, then write the assertion.

The suites themselves ship in [`harness/behaviour/`](../harness/behaviour/), so
the promises on this page are something you can run rather than take on trust,
and the ledger marks the hand-probed rows apart from the suite rows.
Suites with a stock-comparison case find both binaries for you, including the
unpatched control, and refuse to run rather than report half a comparison.
