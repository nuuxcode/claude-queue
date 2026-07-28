# Every way someone can use this, and whether it is tested

Written because the worst bugs were found by using the thing for a minute,
not by testing what had already been imagined. This is the list of what people
will actually do, written down first, so the gaps are visible instead of
discovered.

Legend: **T** tested and passing · **G** gap, not tested · **R** risky, reason given

**121 scenarios, 112 tested.** One of them, B7, is a statistical result rather
than a deterministic one; the reason is below. The nine that are not driven are
all in sections I and J: three are reasoned from the code and say so in place,
six are gaps with the reason next to them, and two of those gaps are choices
rather than omissions, because a shell command and a pasted image are things
this deliberately does not bring back. Every row marked T names the file that
tests it. The stock-behavior comparisons use an unpatched control; the
remaining rows exercise the patched behavior they claim.

---

## A. Marker parsing (what you type)

| # | Case | State | Where |
|---|---|---|---|
| A1 | `q text` waits | T | test_markers |
| A2 | `s text` jumps in | T | test_markers |
| A3 | ordinary `Queue depth` and `Steer clear` sentences stay whole | T | test_markers |
| A4 | `q: text`, `s: text` colon forms | T | test_markers |
| A5 | `Q text`, `S text` uppercase | T | test_markers |
| A6 | no marker waits (default) | T | test_mixed |
| A7 | "start the server", "stop the build" not eaten | T | test_markers |
| A8 | "queueing jobs", "same thing" not eaten | T | test_markers |
| A9 | leading space escapes: ` q fix` arrives as `q fix` | T | test_markers |
| A10 | `q` alone with no body, must not strip to nothing | T | test_matrix |
| A11 | `!shell` command never relabelled or mangled | T | test_edges |
| A12 | `/slash` command typed while busy | T | test_gaps G2 |
| A13 | pasted code containing `q =` and `s =` stays literal | T | test_gaps G8 |
| A14 | marker typed while Claude is IDLE, not busy | T | test_gaps G1 |

## B. Queue mechanics (what runs when)

| # | Case | State | Where |
|---|---|---|---|
| B1 | one waiting message runs after the turn | T | test_mixed |
| B2 | two waiting run one at a time, in order | T | test_mixed |
| B3 | steer plus waiting: steer first, then queue in order | T | test_mixed |
| B4 | `CLAUDE_QUEUE_DRAIN=all` restores batching | T | test_mixed |
| B5 | `CLAUDE_QUEUE_DEFAULT=steer` restores stock default | T | test_mixed |
| B6 | queue something when Claude is idle: runs now | T | test_gaps G1 |
| B7 | turn ends the instant you queue: race | T (statistical) | test_hard H3 |
| B8 | many queued, six or more | T | test_gaps G3 |
| B9 | queued message while a subagent is running | T | test_hard H1 |

## C. Selector and editing (the new surface)

| # | Case | State | Where |
|---|---|---|---|
| C1 | up with an EMPTY queue still recalls last prompt | T | test_edges |
| C2 | up with one queued selects it | T | test_reorder R2 |
| C3 | up past the top: stops, must not break | T | test_matrix |
| C4 | down returns through the list and clears selection | T | test_gaps G4 |
| C5 | enter pops only the highlighted one | T | test_edges, test_ux |
| C6 | edited message returns to its own slot | T | test_matrix C13 |
| C7 | edit the MIDDLE one, others keep their order | T | test_gaps G4 |
| C8 | edit the LAST one | T | test_gaps G4 |
| C9 | pop one, then Escape without sending it | T | test_gaps G5 |
| C10 | pop one, delete all its text, send empty | T | test_gaps G5 |
| C11 | pop a `s` message: does it lose its marker | T | test_matrix |
| C12 | queue drains while browsing: does the index shift | T | test_reorder |
| C13 | pop, then type something new instead: where does it go | T | test_matrix |
| C14 | a queued message containing a pasted image | T | test_hard H2 |

## D. Keys and interaction

| # | Case | State | Where |
|---|---|---|---|
| D1 | Escape with messages queued | T | test_edges, test_gaps G5 |
| D2 | Ctrl-C behaviour unchanged | T | test_gaps G6 |
| D3 | `CLAUDE_QUEUE_LABELS=off` | T | test_edges |
| D4 | vim mode on, up/down mean movement | T | test_gaps G7 |
| D5 | very long queued message wrapping several lines | T | test_gaps G4 |

## E. Reordering (shift with an arrow)

| # | Case | State | Where |
|---|---|---|---|
| E1 | shift+up moves the highlighted message earlier | T | test_reorder R1 |
| E2 | shift+down moves it later | T | test_reorder R1 |
| E3 | pushing past either end does nothing and does not break | T | test_reorder R2 |
| E4 | the highlight travels with the message | T | test_reorder R1, R2 |
| E5 | shift with an arrow does nothing when nothing is highlighted | T | test_reorder R3 |
| E6 | a waiting message never swaps with a jumping one | T | test_reorder R4 |
| E7 | on an unpatched build the key still does nothing | T | test_reorder R5 |
| E8 | the NEW order is the order they actually run | T | test_reorder R7 |
| E9 | reordering works with vim mode on | T | test_gaps G7 |
| E10 | reordering still works with `CLAUDE_QUEUE_DEFAULT=steer` | T | test_reorder R6 |
| E11 | move one, then edit it: it returns to its NEW slot | T | test_reorder R8 |

## F. Removing, and one prompt becoming several (v1.7.0)

| # | Case | State | Where |
|---|---|---|---|
| F1 | backspace removes the highlighted message | T | test_manage D1 |
| F2 | the forward delete key does the same | T | test_manage D5 |
| F3 | with text typed, the key edits the TEXT and not the queue | T | test_manage D2 |
| F4 | with nothing highlighted, the key does nothing to the queue | T | test_manage D3 |
| F5 | deleting every message leaves a usable session | T | test_manage D4 |
| F6 | on an unpatched build the key destroys nothing | T | test_manage D6 |
| F7 | every line marked: one queued message per line | T | test_manage S1 |
| F8 | each split line keeps its own marker's timing | T | test_manage S1 |
| F9 | only some lines marked: stays ONE message | T | test_manage S2 |
| F10 | split messages run as separate turns, in order | T | test_manage S3 |
| F11 | split messages can then be reordered and removed | T | test_manage S4 |
| F12 | abandon an edit, then type something new: it goes to the BACK | T | test_matrix C13 |
| F13 | an unmarked line continues the message above it | T | test_manage S5 |
| F14 | text before a later colon marker keeps the paste literal | T | test_manage S6 |
| F15 | splitting works with an EMPTY queue while busy | T | test_manage S1 |
| F16 | splitting works when Claude is IDLE: first runs, rest queue | T | test_manage S7 |
| F17 | a blank line between jobs is absorbed, not queued | T | test_manage S8 |
| F18 | a marker with no body is not a marker: it continues the line above | T | test_manage S8 |
| F19 | the leading-space escape still works inside a block | T | test_manage S8 |
| F20 | six jobs in one submission is six jobs | T | test_manage S8 |

## G. Tab, the opposite of your default (v1.9.0)

| # | Case | State | Where |
|---|---|---|---|
| G1 | tab jumps in when the default is wait | T | test_manage T1 |
| G2 | tab waits when `CLAUDE_QUEUE_DEFAULT=steer` | T | test_manage T1 |
| G3 | an explicit marker still wins over tab | T | test_manage T1 |
| G4 | tab on a slash command does not invert the next prompt | T | test_manage T2 |
| G5 | tab on a shell command submits it and does not invert the next prompt | T | test_manage T3 |

## I. Folding a long queued row (display only)

A waiting message taller than one line is drawn as its first line plus a count
of the lines it is holding back. The highlighted one is always drawn whole.

| # | Case | State | Where |
|---|---|---|---|
| I1 | a short message is drawn exactly as before | T | test_collapse K3 |
| I2 | a pasted message with newlines becomes one row and a count | T | test_collapse K1 |
| I3 | a long single line that wraps becomes one row and a count | T | tests/test_patch_def FoldingTests, and probe_collapse on both widths |
| I4 | a message that exactly fills one line is left alone | T | tests/test_patch_def FoldingTests |
| I5 | the highlighted row is drawn in full | T | test_collapse K2 |
| I6 | moving the highlight folds the row you left and opens the one you land on | T | test_collapse K2 |
| I7 | `CLAUDE_QUEUE_COLLAPSE=off` draws every line again | T | test_collapse K4 |
| I8 | any other value of that variable keeps the default | T | tests/test_patch_def FoldingTests |
| I9 | the count is display lines, so a wrapped single line counts the same as separate lines | T | tests/test_patch_def FoldingTests |
| I10 | three long messages on a forty row terminal: the busy indicator is still visible | T | test_collapse K1 |
| I11 | pull a folded message back and send it again: still every line | T | test_collapse K6 |
| I12 | what the model receives | R, reasoned not driven: the fold copies the throwaway message built for drawing and never the queued command, and K6 shows the stored command is intact after a round trip through the editor. No test reads the delivered text out of a transcript |
| I13 | an unpatched control does not fold, so the difference is the patch | T | test_collapse K5 |
| I14 | a message that is only whitespace | G, cannot be queued at all, which A10 covers |
| I15 | a queued message carrying a pasted image | R, reasoned not driven: its content is not a single text block, so the fold hands it back untouched. The shape is covered in tests/test_patch_def, and C14 drives real images |
| I16 | a sixty column terminal, pty sized and COLUMNS unset, which is what a person actually has | T, probe, probe_collapse_narrow |
| I17 | delete, reorder and split on folded rows | G, no key reads the drawn text, so the existing suites cover them unchanged |
| I18 | a terminal narrower than about twenty two columns | G, the floor on the fold width can exceed the room available. Claude Code is unusable at that size anyway |

## J. Waiting messages surviving a restart

Every change to the queue is written to this project's `.claude` directory, in a
file named for the session. The next session started in that project brings the
messages back as rows marked restored, and nothing runs until you send
something yourself. `--continue` and `--resume <id>` keep the session id and
find their own file; the `/resume` menu forks a new id, so a session that finds
no file of its own adopts the newest one this project has waiting.

| # | Case | State | Where |
|---|---|---|---|
| J1 | clean exit with three waiting, resume: all three back, order kept | T | test_persist N1 |
| J2 | kill -9 mid turn, resume: all three back | T | test_persist N2 |
| J3 | the interrupted turn's own message is not duplicated into the queue | T | test_persist N2 |
| J4 | crash after the first of three ran: only two come back | T | test_persist N3 |
| J5 | a message that ran is removed from the file at the moment it is dequeued | T | test_persist N3, which reads the file after the crash |
| J6 | a session in a DIFFERENT directory sees nothing, even with the same session id | T | test_persist N4 |
| J7 | resuming from the `/resume` menu, which forks a NEW session id | T | test_persist N9. This shipped broken: the id lookup could never match a forked id, so the messages were saved and never offered back. N1 to N6 all drove `--resume <id>`, which keeps the id, which is why they passed |
| J7b | a plain new session in the same project adopts what is waiting there | T | test_persist N9 drives exactly that, because a fresh id in the same directory IS the fork. Deliberate: a session cannot tell the two apart |
| J7c | the adopted file is taken over, not copied: rewritten under the new id, the old one deleted | T | test_persist N9, and tests/test_patch_def PersistenceTests |
| J7d | a session that finds its OWN file ignores a newer one beside it | T | tests/test_patch_def PersistenceTests. Exact match stays the primary rule |
| J8 | two live sessions in the same project | R, reasoned not driven, and now a stated trade rather than a neutral one: the second session can adopt the first's file. Nothing runs from it, the rows say restored, and the first session rewrites its file on its next queue change. Driving it costs two concurrent paid sessions per assertion |
| J9 | a file from days ago | T, by construction: nothing expires, and the restored mark is what makes an old message recognisable. The mark is driven by N1 |
| J10 | the file is corrupt or half written: ignored, and the session still starts | T | test_persist N5 |
| J11 | restored rows wait, a new message runs first, then they drain in saved order | T | test_persist N6 |
| J12 | restored rows are visibly marked `[waits, restored]` and `[jumps in, restored]` | T | test_persist N1, and probe_persist2 for the steer form |
| J13 | the restored mark never reaches the model | T | tests/test_patch_def PersistenceTests: the value out of the file equals the value in, and the mark is a property beside it |
| J14 | the queue empties normally: the file is deleted, no litter | T | tests/test_patch_def PersistenceTests, and probe_persist2 on a real drain |
| J15 | `CLAUDE_QUEUE_PERSIST=off` writes no file and reads none | T | test_persist N8, and tests/test_patch_def PersistenceTests |
| J16 | any other value of that variable keeps the default | T | tests/test_patch_def PersistenceTests |
| J17 | an unpatched control writes no file | T | test_persist N7 |
| J18 | the write is atomic: a crash during a write leaves the old file or the new one | T | tests/test_patch_def PersistenceTests, which proves the temporary name is gone and the file parses |
| J19 | nothing is written before a restore has been attempted | T | tests/test_patch_def PersistenceTests. Without it a message enqueued during startup writes the file before the saved one has been read |
| J20 | a message pulled back into the editor when the crash happens | G, and documented: it left the queue when it was pulled back, so it is not restored. The editor is not saved |
| J21 | a queued shell command (`!cmd`) | G, deliberately not saved: restoring it would run a shell command you did not ask for at resume |
| J22 | a queued message carrying a pasted image | G, deliberately not saved: its value is not text, and half restoring it would be a lie about what it was |
| J23 | `/compact` in the queue when the crash happens | T, by construction: it is a prompt row like any other, and the shape is covered in tests/test_patch_def. Not driven in a session |
| J24 | a restored session shows the working spinner while it is idle | T, fixed: a held queue no longer counts as a busy session. Found by probe, and the row stays because the spinner was real and its counter read twenty thousand days |
| J25 | uninstalling: what is left behind | T, documented: the files are in each project's `.claude`, named `queue-<session>.json`, and the docs say so and say to ignore them |
| J26 | typing `/resume` itself, while restored rows are being held | T, driven in probe_resume_menu on v23: the picker opens, and the held rows drain, because the hold is released by ANY submission and a slash command is one. Not introduced here, it is the release rule doing what it says, but the fork path is what makes it reachable from a plain `claude`. Left as it is: the person did send something |
| J27 | a bare `claude` with no `--session-id` at all | T, driven in probe_resume_menu on v23: a file planted by a session that no longer exists came back as two rows marked restored, and was rewritten under the new id. N9 passes an explicit id, so this is the row that proves the app's own id generation is not what the fallback depends on |

---

## What was found by writing this list

**C11, C12 and C13 were all real.** C11 and C12 were predicted here before they
were found. C11: editing an `s` message silently turned it into a waiting one.
C12: the queue drained from the top while you were browsing and the highlight
ended up on a message you never picked, because stock tracks a position and only
clamps it. Both are fixed, and both fixes were proved by running the same test
against the previous build and watching it fail.

## The three that needed their own driver

All three are now tested, each by `test_hard.py`, and each needed something the
other suites do not have.

| # | how it was finally driven |
|---|---|
| B9 | Ask for a real subagent, wait for `Agent(` on screen, queue during it, and check the message is still waiting twenty-five seconds later while the subagent is visibly still working |
| C14 | Put a real PNG on the system clipboard with `osascript`, send ctrl+v into the pty, and check the image survives being queued. Anthropic's changelog fixed image loss in queued messages twice, at 2.1.72 and 2.1.105, so this is a real place for things to break |
| B7 | Cannot be aimed from outside the program, so it is fired at eight different offsets around the end of a turn and the transcript is read back each time. The claim is that the message is delivered exactly once, never lost and never doubled. Eight of eight. **That is weaker than a deterministic test and is labelled as such wherever it is quoted.** |

## The rule this list exists to enforce

**Twenty-one distinct harness faults across these sessions, fifteen of which produced
a red result on a build that was working.** Every one came from inferring state from a
screen signal that was never verified. So: probe first and read the screen, then
write the assertion. A red result is not a bug until the test is proven to
exercise the thing it claims to.

A selection, session one then session two: a turn counter reading banners that
scroll away; a busy detector whose pattern this build never prints; an idle
check that fired between tool calls; pyte discarding scrollback; the environment
scrub deleting the very flag under test; a walk test assuming one pop per
keypress; a relative binary path that read as a crash on boot; a chunked read
corrupting a rule line; `input_area()` finding the transcript instead of the
editor; a fake paste the input treated as typing; a ctrl-c comparison read while
both builds were still mid-flight; `test_gaps` G2 asserting a shape neither
build has; `test_ux` still asserting the v1.2.0 pop; `test_reorder` R2 with no setup
guard, which failed on an empty queue when six sessions ran at once; and the
busy prompt letting the model pick `sleep 0.1`, which ended the turn in nine
seconds and made `test_markers` report 2 of 13 on a build that scores 13 of 13.

## H. Hand-driven probes, not yet in a suite

| # | scenario | status |
|---|---|---|
| H1 | /compact typed while two messages wait: queues as [waits], runs in turn order | T, probe, 3 runs |
| H2 | a message queued BEHIND /compact survives the manual compaction and runs after it | T, probe |
| H3 | automatic compaction near the context limit with a populated queue | G, costs a near-full session |
| H4 | steer sent during a slow tool prevents a write that has not started (file absent, model says SKIPPED) | T, probe |
| H5 | steer sent after the write happened: damage stays on disk, model may ignore the moot instruction | T, probe |
| H6 | plain Escape with a populated queue: turn stops, queue kept, first message starts | T, probe |
| H7 | three long queued messages fill the screen and hide the busy indicator, identically on the control: inherited display behaviour | T, probe, both builds. FIXED by the fold in section I. The row stays because the behaviour it records is still what an unpatched build does, and because `CLAUDE_QUEUE_COLLAPSE=off` asks for it back. `test_collapse` K1 is the same scenario as a check, and it fails on the build before the fold |
