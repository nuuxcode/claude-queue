# How it behaves, in detail

The [README](../README.md) covers everyday use and [the full story](deep-dive.md)
the detail. This page is for
when you want to know exactly what changes and why, before you run it or after
something surprises you.

---

## Everything that goes wrong today

Each of these was observed on stock Claude Code while building this. The rows
marked **measured** come from the recorded runs in [the full story](deep-dive.md) and can be
reproduced with the [harness](../harness/).

| | what happens |
|---|---|
| **You cannot say "next"** | The only thing you can express is "roughly now". There is no way to attach a message to the end of the current job |
| **It lands at an arbitrary moment** | Your message is picked up at the next tool boundary, whenever that happens to be, or at the end of the turn if no boundary comes first. **Measured**: 35s to 88s between typing and Claude acting in the clean stock recording |
| **Order is not preserved** | **Measured**: the message typed second was started first in the clean stock recording |
| **Everything merges into one turn** | Pending messages are handed to Claude together after the tool boundary, so their separate turn boundaries are not preserved |
| **One answer covers several asks** | Real stock output, three requests in: *"Done. Added `remove_task(task_id)`... The `list_tasks()` function already numbers them"*. That answers the second and third and never mentions the first, which had asked it to run the file and report back. Which parts actually happened is no longer visible |
| **New work starts before old work finishes** | **Measured**: one run began the new `metrics.py` before the original job had written its own `README.md` |
| **Queued messages arrive as a batch** | Everything waiting of the same kind is handed over together, so two things you typed become one turn and the first one's result cannot inform the second |
| **Nothing tells you any of this happened** | No reordering notice, no "these were merged". You find out by reading the output carefully, or you do not find out |
| **The only hard stop is Escape** | Which kills the running tool and throws away whatever it was doing. There is nothing between "interrupt and lose work" and "wait and say nothing" |
| **The workaround costs you every time** | Typing "once that is done, ..." is queueing by hand. It costs tokens, it costs attention, and it only works on the occasions you remember to do it |

### One thing deliberately not on that list

The runs also produced slightly different file sets from identical prompts: one
stock run skipped a test file that the other three wrote. That is real, and it
is tempting to add to the pile, but it does not belong here. Model output varies
between runs anyway, and no run was recorded **without** interruptions to
compare against, so nothing attributes that variation to the interruption. It
is left out rather than counted as evidence it cannot support.

---

## Is `s` just the current behaviour with a letter in front?

**Yes, and that is deliberate.** A patch that quietly changes the thing you did
not ask it to change is worse than no patch.

Claude Code ranks queued messages `now`, `next`, `later`. A message you type
while it is working is treated as **`next`** in every place that reads the
queue, including the mid-turn collection that runs at the next tool boundary.
That is why it interrupts.

| | priority it gets | when it runs |
|---|---|---|
| **stock Claude Code**, no patch | `next` | next tool boundary, mid-turn |
| **`s ...`** with this patch | `next`, set explicitly | next tool boundary, mid-turn. **Same path, same behaviour** |
| **no marker** with this patch | `later` | after the current turn finishes |
| no marker, `CLAUDE_QUEUE_DEFAULT=steer` | untouched | whatever stock would have done |

So `s` is today's behaviour, kept on purpose, because interrupting is genuinely
the right thing when Claude is editing the wrong file. This does not improve
steering. It gives you a second option next to it.

`later` is already one of Claude Code's three priorities, and an internal
path already enqueues at `later`. The patch chooses between values the
program already understands.

**The one behavioural difference**: at the end of a turn, stock
collects waiting messages by matching their kind only. This patch also requires
a matching priority, so an interrupting message can no longer drag a waiting one
into its turn and silently cancel its wait. On stock that situation cannot
arise, because stock has no waiting priority to cancel. If you run everything in steer mode, there is no
difference at all.

Verify it against your own disk rather than believing the table:

```bash
claude-queue verify
```

---

## When a steer actually lands

Not instantly, and this matters.

Claude Code collects high priority messages once per model round-trip, which in
practice means **the moment the currently running tool finishes and before the
next one starts**. If Claude is thirty seconds into a fifty second test run,
your steer waits for that run to end.

| | what it does to a running command |
|---|---|
| Escape | kills it immediately and throws away the work |
| `s` | lets it finish, then lands before the next step |
| queue | lets the whole turn finish, then runs as its own turn |

So `s` is "as soon as possible without destroying anything", not "right now".
If you need it stopped mid-command, that is still Escape.

## Mixing queued and steering messages

They do not compete. Here is the order:

```
you type:   q ONE      q TWO      s STEER
it runs:    STEER  ->  ONE  ->  TWO
```

The steer is priority `next`, so the mid-turn collection takes it at the next
tool boundary, before the job you were waiting on finishes. The two waiting
messages are `later`, so that collection ignores them. They run after the turn
ends, one at a time, in the order you typed them.

This is the case that had a bug: the end-of-turn sweep used to match on kind
only, so the steer would drag a waiting message into its turn and silently
cancel its wait. It now matches priority too, and there is a test for it.

## Queue two things and they stay two things

Stock Claude Code hands over every queued message of the same kind at once, so
two things you typed while it worked arrive as one turn. That is fine for an
interruption, where both are corrections to the same thing. It is wrong for a
queue: the first job's result can no longer inform the second.

So waiting messages run **one at a time**, each as its own turn, in order.

```
❯ write the migration notes
⏺ Done.
❯ then run the test suite
⏺ Running…
```

`CLAUDE_QUEUE_DRAIN=all` gives you the stock behaviour back.

## Tab, the opposite of your default

Tab submits the message exactly as enter does, with the opposite timing to
whatever your default is. Unset, enter waits and tab jumps in. With
`CLAUDE_QUEUE_DEFAULT=steer`, enter jumps in and tab waits, which is Codex's
exact arrangement.

It flips the DEFAULT, not the message. A marker still decides: `q ...` sent
with tab still waits, because an explicit instruction should not be quietly
reversed by a keystroke.

Tab was free. The prompt box's key handler has a bare `case"tab":return`, so it
does nothing there today, and the completion menu takes the key earlier
whenever one is open, so nothing that already uses tab is displaced.

**The shape is borrowed from Codex, not the key assignment.** Codex's editor has
a setting for the default plus a shortcut that uses the opposite mode for one
message. Copying that rather than "tab always queues" means the key is useful
whichever way round you like your default, and setting
`CLAUDE_QUEUE_DEFAULT=steer` reproduces Codex exactly.

## Removing a queued message

Highlight it and press delete or backspace. The message goes, the rest keep
their order, and the highlight moves to the next one down.

**Only when the editor is empty.** Both keys already do nothing at that moment,
because there is no text to delete, so nothing is displaced by taking them. The
empty-editor condition is what makes binding a key this common safe rather than
alarming: the highlight clears the instant you type, so there is no state where
backspace could eat a queued message while you thought you were fixing a word.
That case has its own test, which checks the queue is unchanged after three
backspaces with text in the editor.

Removal is a real deletion, not a pop into the editor. If you wanted the text
back, press enter instead and edit it.

### Changing your mind after pulling one back

Pulling a message back records the slot it came from, so sending it again puts
it where it was. That record expires when you **clear the editor**, which is the
honest signal for "not that message any more". Anything still in the box counts
as a draft of what you pulled back, and sending it returns it to its own slot.

This had a real bug. The record did not expire at all, so abandoning an edit and
typing something unrelated filed the new message into the gap the old one had
left: queue three, pull the first one back, change your mind, type something
new, and it arrived at the FRONT of the queue.

It hid for a while behind Escape. Escape stops the turn, stopping the turn
releases the queue, and by the time anything was checked the queue had drained
and the evidence was gone. It only appeared once the test abandoned the edit by
clearing the text instead of pressing Escape.

## One submission, several messages

**A marker starts a new message. A line without one continues the message above
it.** So this is three jobs, and the second is two lines long:

```
q write the migration notes       ->  [waits]    write the migration notes
q then run the test suite         ->  [waits]    then run the test suite
and tell me what broke            ->             and tell me what broke
s you are editing the wrong file  ->  [jumps in] you are editing the wrong file
```

Each message keeps the timing its own marker asked for, so one block can mix
waiting and interrupting jobs. Afterwards they are ordinary queue members:
movable, editable, removable, and they run as separate turns in order.

The continuation rule is what makes multi-line jobs possible. An earlier version
split only when EVERY line was marked, which meant there was no way to express
three jobs where one of them needed a second line.

**Two shapes are unchanged**, and both had tests before this rule existed:

```
plain paragraph            no markers anywhere, so it stays ONE message
second line

q one paragraph            only the first line is marked, so the later lines
second line, no marker     continue it: still ONE message
third line
```

Text before the first marker becomes its own message, at your default timing.

### It works when Claude is idle too

If something is running, every job in the block queues. If nothing is running
there is no queue to put the FIRST one in, so it becomes the turn and the rest
line up behind it. The same list runs in the same order either way.

That second case was broken until it was reported. A block typed into an idle
session arrived as a single message, which is how it looked from outside: "the
split only works when something is already queued". The session had been
interrupted, so it was idle, and the whole block ran as one prompt.

## Every setting, both of its states

Three environment variables. Each is compared against **one exact lower case
string** and nothing else, so any other value leaves the default in place
without saying so.

| variable | unset, the default | set to | effect | read at |
|---|---|---|---|---|
| `CLAUDE_QUEUE_DEFAULT` | a message with no marker gets priority `later`, so it waits | `steer` | a message with no marker is left at stock priority `next`, so it interrupts. `q ...` and `s ...` are unaffected either way | the moment you press enter, and again when a message is pulled back for editing so it comes back with the right marker |
| `CLAUDE_QUEUE_DRAIN` | at the end of a turn, exactly one waiting message is taken | `all` | at the end of a turn, every waiting message of the same kind and priority is taken together, which is what stock does | the end-of-turn sweep |
| `CLAUDE_QUEUE_LABELS` | queued messages are drawn with `[waits]` or `[jumps in]` | `off` | queued messages are drawn with no tag | each time the queued list is drawn |

What follows from that:

- There is no value that switches a setting the other way. The second state is
  the default, so you **unset** the variable rather than assigning it something
  else. `CLAUDE_QUEUE_LABELS=on` leaves the labels on, but only because on is
  already the default, not because the value was understood.
- The comparison is case sensitive. `CLAUDE_QUEUE_LABELS=OFF` keeps the labels.
- `CLAUDE_QUEUE_DEFAULT` is read in two places and both use the same test, so
  the marker a message comes back with always matches the timing it will get.
- Setting all three gives you stock behaviour with the markers still available.

## What you see on screen

Every queued message is labelled with what it will do:

```
❯ [waits] write the migration notes
❯ [waits] then run the test suite
❯ [jumps in] wrong file, stop
```

The labels are drawn on your screen and are never part of what Claude receives.
`CLAUDE_QUEUE_LABELS=off` removes them.

The first version labelled only the exception, on the reasoning that a tag on
every line is noise once waiting is the default. Using it showed that was wrong.
An unlabelled message gives you no confirmation at all, so "it was queued" and
"my marker was not recognised" look identical, which is the one thing you need
to know at the moment you press enter.

## Every marker form, checked

All of these are verified against a real session, including the near misses that
must NOT be treated as markers:

```
q ...   q: ...                      wait          Q ... too
s ...   s: ...                      jump in       S ... too
start the server    stop the build     Queue depth     Steer clear
                                       all untouched, all just messages
" q fix the tests"  leading space escapes it, arrives as "q fix the tests"
"q" alone           stays a literal message, never an empty send
```

Pasted text is literal unless its first nonblank line uses `q:` or `s:`. That
explicit colon form starts a multi-job batch. Ordinary code containing
`q = deque()` or `s = socket()` stays one intact message.

## Editing something you already queued

Up and down move a highlight through the queue. Nothing enters the editor while
you browse:

```
   up x1              up x2              up x3
   [waits] alpha      [waits] alpha    ❯ [waits] alpha
   [waits] bravo    ❯ [waits] bravo      [waits] bravo
 ❯ [waits] charlie    [waits] charlie    [waits] charlie
```

Enter takes only the highlighted one, and when you send it back it returns to
the slot it came from rather than the end of the queue:

```
❯ alpha one                     in the editor
  [waits] bravo two             still waiting
  [waits] charlie three         still waiting
```

Stock hands the WHOLE queue over as one blob joined by newlines, so editing any
of them means untangling all of them and retyping.

### Why this is not just the flag

Claude Code already contains this selector, behind
`CLAUDE_CODE_KB_COHESION_FIXES`. Setting that flag is not what this does, and
the difference matters.

That flag gates a whole keyboard revision: the queue selector, and also Escape,
Ctrl-C, Ctrl-D and exit. Turning it on to get the selector would change four
other keys underneath you, and it is unreleased, so its behaviour can move
without warning.

So the gate is opened at exactly three call sites, the two arrow keys and the
submit that consumes the selection. The other eight uses of the flag are left
alone. Measured on both builds afterwards: Escape behaves identically, which is
the check that mattered.

An earlier build took a smaller swing at this and made the up arrow
pop the newest queued message into the editor rather than all of them. It was
not enough. To reach the FIRST queued message you still had to pop everything
above it, so by the time you got there the editor held all of them again. That
code is still present and now covers Escape, which also empties the queue into
the editor.

### The highlight follows the message, not the row

Stock tracks a position in the list and only clamps it: if the queue shrinks
past the end, the highlight jumps to the last message. That is right when the
last message is the one you were on, and wrong every other time.

Queue three, press up twice to sit on the middle one, and wait. The turn ends,
one message drains from the top, the two below shift up, and the highlight is
now on a message you never picked. Press enter and you edit the wrong one, with
nothing on screen saying anything happened.

So the highlight tracks the message itself. The queue holds the same objects
across a change, so the one you picked can be found again by identity: it moves
down when the queue drains above it, it moves with the message when you reorder
it, and it clears when the message it was pointing at is gone. The old clamp is
kept as the fallback for the one case identity cannot answer.

Proved by running the same test against the previous build and watching the
highlight slide from "second item" to "third item".

## Reordering messages that are waiting

Highlight one and hold shift with an arrow key:

```
   start              shift+up           shift+up
 ❯ [waits] alpha      [waits] alpha    ❯ [waits] charlie
   [waits] bravo    ❯ [waits] charlie    [waits] alpha
   [waits] charlie    [waits] bravo      [waits] bravo
```

This is the one genuinely new operation in the patch. Everything else picks
between behaviours Claude Code already has, but nothing in it can move a queued
message, so this adds a swap to the queue module itself, next to the array and
the redraw call every other queue operation uses.

**A message only swaps with another of the same priority.** A `[waits]` message
moves among the waiting ones, a `[jumps in]` message among the jumping ones,
and the two never cross. The reason: an interrupting
message drains before a waiting one whatever order the list shows, so letting
you drag a waiting message above it would move it on screen and change nothing
about when it runs. A list that lies about the order is worse than a list you
cannot fully rearrange. Within one priority the list order **is** the run order,
which is the property the test suite checks by letting the turn finish and
reading the run order back out of the session transcript.

Shift with an arrow does nothing in stock Claude Code's prompt box, both arrows
return early on shift, so taking that key displaces no existing behaviour.

---

## What it actually changes

Claude Code already stores queued messages with a priority, and it already
empties that queue in two places: partway through a turn, and at the end. Only
the first one is picky about priority.

So this does not build a queue and does not change when the queue is emptied. It
chooses the priority for your message from the letter you type, and removes that
letter before the text is sent.

### Safety properties

- The change is applied to the copy of Claude Code on your machine. The original
  is saved first, and `restore` puts it back byte for byte.
- The patched program is built to one side and **run once** before it is allowed
  to replace the working one.
- If Claude Code changes in a way this does not recognise, it refuses and writes
  nothing rather than guessing.
- The launcher fails open. If anything goes wrong, Claude Code still starts, just
  unpatched.

### What it touches on your machine

```
~/.claude-patch/backups/      the untouched original (~250 MB, 2 kept)
~/.claude-patch/tweakcc/      locked helper tree (~88 MB today)
~/.claude-patch/registry.json what is installed
your shell rc                 one PATH line (skip it with --no-path)
```

The normal steady-state total is about 600 MB. The helper uses the shipped
package lock and installs with npm lifecycle scripts disabled.

The PATH entry is there because Claude Code updates itself, and an update
replaces the program and drops the change. The launcher notices and re-applies
it before starting, which takes about four seconds and only happens after an
update.

---

## Updating

```bash
claude-queue update
```

It checks for a newer version, **shows you exactly what changed**, and asks
before applying anything. Say no and nothing happens.

**Nothing is ever downloaded or applied behind your back.** There is no
auto-update and no background fetching. The only time anything is fetched is
when you run the command above, and even then it applies nothing until you
agree.

The one thing that does happen by itself is repair: Claude Code replaces its own
program when it updates, which removes the change, so the next launch puts back
**exactly the code you already installed**.

If the code on disk has changed since you installed it, for any reason, it is not
applied on its own. You get told, and it waits:

```
claude-queue     ON  v2.0.1
         update waiting: v2.0.1 installed, v2.1.0 on disk.
         review it, then run: claude-queue install
```

Claude Code still starts normally in the meantime, with what you had before.

---

## How it was tested

Driven against real Claude Code sessions on a pty. Cases that depend on stock
behavior use an **unpatched copy as a control**. First the marker behavior:

```
stock Claude   no marker   interrupted mid-turn     (the control behaved)
patched        no marker   waited for end of turn
patched        q           waited for end of turn
patched        s           interrupted mid-turn
```

The control matters more than the rest. Without it a broken test looks exactly
like a working feature, which happened more than once while building this. One
change applied cleanly, did nothing at all, and was only caught because the
control produced identical output.

Then a written list of every way someone can use this, one hundred
twenty-one
real-session cases across markers, queue mechanics, the selector, the keys,
reordering, removal, splitting, the tab key, the fold and persistence; 112
of them are tested and every gap names its reason in place.
One of them, a message submitted at the exact instant a turn ends, is a
statistical result rather than a deterministic one and is labelled that way
wherever it is quoted. Writing the list first is what surfaced the worst bugs:
editing a steer silently downgraded it to a wait, the highlight drifted onto a
different message when the queue drained, and abandoning an edit misfiled the
next thing you typed into the slot the old message had left. The first two were
written down as suspicions before either was found. The third was found by
rewriting a test that had been passing for the wrong reason: it abandoned the
edit with Escape, which stops the turn and drains the queue, so the state under
test was gone before anything was checked.

A later audit found a different index mismatch that the original list did not
cover. The selector index counts only editable messages, while reinsertion
splices the raw queue, which can also contain shell commands, task
notifications, metadata and non-human entries. A deterministic
generated-JavaScript regression now covers those shapes. It failed on 2.0.0
and passes on 2.0.1. The patch also applied to a real 2.1.220 stock executable
and the rebuilt copy started. A live background task notification landing
mid-queue has not been driven.

The other half of that discipline is distrusting the harness. Twenty-one distinct
harness faults were found while building and auditing this, and fifteen of them produced a
red result on a build that was working. A selection: a spinner pattern that never
matched, a screen library that discarded scrollback, an environment scrub that
deleted the very flag under test, a relative path that looked like a crash on
boot, a chunked read that corrupted a line, a screen check that found the
transcript instead of the input box, a fake paste that the input treated as
typing, a comparison read while both sides were still mid-flight, and two
assertions still checking shapes from earlier releases.

Twenty of the twenty-one came from inferring state from a screen signal that was
never verified. So the rule is: probe first, read the actual screen, then write the
assertion. **A red result is not a bug until the test is proven to exercise the
thing it claims to.**

Every fix for a behavioural bug is also run against the **previous** build to
watch it fail there. A test that passes everywhere proves nothing.

Then the recorded comparison in [the full story](deep-dive.md): two clean runs of the same
multi-file job, one stock and one patched, with two follow-ups typed mid-build
in each. That harness
is in [`harness/`](../harness/) and you can run it yourself.

It refuses to save a run where the follow-ups did not genuinely land mid-flight,
because an early version sent them on a timer, the first job finished in 13
seconds, and the resulting recording showed two messages "interrupting" an idle
session. It was published before anyone noticed. The guard exists so that cannot
happen again, to me or to you.

Honest limits: one machine, one model, two clean recorded runs. Enough to show the
behaviour changed in the direction claimed, and enough for you to reproduce it.
It is not a benchmark.

---

## Three probes people keep asking about

Driven by hand against the current build, outside the suites, each with the
screen read after the turn fully settled.

**A steer can save a file whose write has not started.** Task: a thirty second
command, then write POISON into danger.txt, then say DONE. A steer sent during
the slow command ("do not create danger.txt, say SKIPPED") landed at the tool
boundary, the write never happened, and the model said SKIPPED.

**A steer cannot save a file already written.** Same task with the write moved
first. The file existed before the steer could land, the damage stayed on
disk, and the model finished with DONE, treating the too-late instruction as
moot. Escape remains the only brake for a tool in flight, and reverting damage
is the model's judgement, not a mechanism.

**Long queued messages can hide the spinner.** Three long messages queued on
a 40-row terminal rendered their full text, filling every row; the transcript
and the working indicator were pushed off screen entirely, which reads as a
frozen session. Driven on both builds: the unpatched control renders exactly
the same way, so this is inherited, not introduced. A collapsed display for
long queued rows is the natural fix and is on the roadmap.

**Where exactly a steer lands, defined once.** The landing points are
tool-result boundaries: the moment one tool's result has arrived and before
the next tool starts. A message typed between boundaries waits for the next
FUTURE one, so if the current tool is long, the steer waits through it. And a
turn that is streaming plain text has no tool boundaries at all, so during
text-only streaming even an `s` message arrives when the stream ends. One
more honesty line that our own race probe measured: delivery is not
obedience. A steer that arrives after its moment has passed can be treated by
the model as moot; the probe watched one answer DONE to an instruction it no
longer needed.

**Why the fold exists.** Claude Code shortens a queued message of its own
accord only past ten thousand characters, which no pasted paragraph reaches.
So three ordinary long messages waiting were enough to fill a forty row
terminal with their own text and leave no room for the busy indicator, which
made a working session look frozen. A folded row shows its first line and a
count; the highlighted row is always whole; the stored message never changes.

**/compact queues like a message.** Typed while two messages waited, it joined
the list as `[waits] /compact`, ran in its turn, and a message queued behind
it stayed listed through the compaction and ran after it. The automatic
compaction near the context limit was not driven; filling a session that far
costs real money, and no claim is made about it.

## Uninstalling

```bash
claude-queue restore
```

That puts the original program back, byte for byte, and takes this out of the
picture. Left behind afterwards:

```
~/.claude-patch/backups/     the saved original (~250 MB)
~/.claude-patch/registry.json
one line in your shell config
```

Remove those by hand if you want nothing left. They are kept by default because
throwing away someone's only copy of the original program is a bad default.
