# The evidence

This page is receipts. No argument, no interpretation beyond what the sources
say. Every issue number, title, state and date below was read from the GitHub
API, and every changelog line was read from Anthropic's own `CHANGELOG.md`, not
from memory or from someone's summary.

Check any of it yourself. That is the point of writing it down this way.

---

## 1. The same input channel has been described both ways

Claude Code's own changelog, two releases apart:

```
0.2.75    Hit Enter to queue up additional messages while Claude is working
0.2.108   You can now send messages to Claude while it works to steer Claude
          in real-time
```

One action. Announced first as a **queue**, then as **steering**.

Those are not two names for one thing. They are opposite requirements:

| | what it must do | what it must never do |
|---|---|---|
| **Queue** | stay invisible to the running turn, then run as its own turn afterwards | leak into the work already in flight |
| **Steer** | reach the running turn and change what it does | wait quietly until the job is over |

A queued message that becomes visible to the active turn has not been queued.
A steering message that waits for the turn to end has not steered. One input
action cannot reliably mean both unless the user says which one they meant.

**This is not a claim that Claude Code has no queue.** It has had queue-related
behaviour since 0.2.75, and some message types genuinely do wait for the turn to
finish today. The claim is narrower, and harder to argue with: the two
meanings are blurred, and which one you get depends on timing rather than on
what you intended.

---

## 2. Anthropic has been fixing this subsystem across 27 releases

`CHANGELOG.md` contains **34 entries mentioning queued or steering messages,
across 27 distinct releases**, from 0.2.75 to the current 2.1 series. That is
not a project ignoring the problem. It is a project repeatedly patching the
symptoms of one input channel carrying two contracts.

(Versions rather than dates, because the changelog states versions and those are
what was checked.)

A selection, quoted exactly and ordered oldest first:

| release | entry |
|---|---|
| 1.0.84 | Fix Claude sometimes ignoring real-time steering when wrapping up a task |
| 2.0.21 | Fixed an issue where queued commands don't have access to previous messages' output |
| 2.0.36 | Fixed queued messages being incorrectly executed as bash commands |
| 2.0.68 | Fixed an issue where steering messages could be lost while a subagent is working |
| 2.1.78 | Fixed queued prompts being concatenated without a newline separator |
| 2.1.85 | Fixed prompts getting stuck in the queue after running certain slash commands, with up-arrow unable to retrieve them |
| 2.1.105 | Fixed images attached to queued messages (sent while Claude is working) being dropped |
| 2.1.110 | Fixed queued messages briefly appearing twice during multi-tool-call turns |

Read them as a group and the shape is clear: **messages lost, duplicated,
merged, mistyped, stuck, and ignored.** Those are the failure modes of a
scheduler, not of a text box.

### The slash commands had to be exempted one at a time

| release | entry |
|---|---|
| 2.1.30 | Changed `/model` to execute immediately instead of being queued |
| 2.1.70 | Improved `/rename` to work while Claude is processing, instead of being silently queued |
| 2.1.83 | `/status` now works while Claude is responding, instead of being queued until the turn finishes |

Three separate releases, three commands, each carved out by hand. That is what
it looks like when one channel has to serve behaviours it cannot distinguish.

(This patch inherits that behaviour unchanged and does not add to it. Verified:
`/status` typed while Claude is working opens immediately, identically on a
patched and an unpatched build.)

---

## 3. The tracker: two groups, asking for opposite things

Every row was read from the GitHub API. States and dates are as fetched. Issue
titles are lightly normalized for punctuation and length.

### Asking for a queue

| # | opened | state | title |
|---|---|---|---|
| [535](https://github.com/anthropics/claude-code/issues/535) | 2025-03-16 | closed | Feature request: The ability to queue up messages |
| [15854](https://github.com/anthropics/claude-code/issues/15854) | 2025-12-31 | closed | [FEATURE] Programmatic access to message queue |
| [25845](https://github.com/anthropics/claude-code/issues/25845) | 2026-02-15 | closed | [FEATURE REQUEST] Prompt Queue with Steer Controls |
| [29224](https://github.com/anthropics/claude-code/issues/29224) | 2026-02-27 | closed | [FEATURE] Side-channel responses for queued messages during active task execution |
| [30677](https://github.com/anthropics/claude-code/issues/30677) | 2026-03-04 | open | [FEATURE] VS Code Extension: Support queued message sending instead of interrupting |
| [33323](https://github.com/anthropics/claude-code/issues/33323) | 2026-03-11 | open | [FEATURE] Task queue for queuing multiple prompts/tasks |
| [34835](https://github.com/anthropics/claude-code/issues/34835) | 2026-03-16 | open | [FEATURE] The ability to queue up messages |
| [49373](https://github.com/anthropics/claude-code/issues/49373) | 2026-04-16 | closed | Queue messages to send at true end-of-turn, not next LLM pause |
| [50246](https://github.com/anthropics/claude-code/issues/50246) | 2026-04-18 | open | Message queue mode: queue messages instead of interrupting active tasks |
| [63190](https://github.com/anthropics/claude-code/issues/63190) | 2026-05-28 | open | [FEATURE] Deferred Messages, Queue Input for End of Turn |

**From March 2025 to May 2026**, the same request arriving under a new number
each time.

"Closed" undersells how the original ended: **#535 was closed as not planned by the github-actions stale bot** on
2026-01-15, "due to 60 days of inactivity", not by a human decision. The first
comment after closure, from a user: "A ticket with 26 votes just gets
auto-closed..." Its successor **#50246 is open with 162 thumbs-up and 42
comments** as of 2026-07-27, the most-upvoted thread in the cluster. One
comment there: "There are jobs I send to Codex instead of Claude Code over
this one silly feature."

The breadth, reproducible from the search API on 2026-07-27: title-searching
queue and steer terms in this tracker returns **199 issues; 152 remain after
filtering to message/prompt/input senses, 53 of them open** (three of the 53
use "steer" in an unrelated sense, so the conservative figure is 50).

Issue 49373 states the distinction this whole project rests on: messages
presented as queued can be flushed at the next model pause, including between
tool calls, rather than after the task completes.

Issue 34835 contains the clearest statement of the fix, from a user comparing
Codex's keys (enter to steer, tab to queue, esc to interrupt): "steer and
queue are two fundamentally different user intents, and conflating them ...
leads to exactly the problems described in this issue".

Anthropic's own prompting guidance points the same direction. The Claude
Sonnet 5 page on platform.claude.com, under "Interactive coding products",
states: "ambiguous or underspecified prompts conveyed progressively over
multiple user turns tend to relatively reduce token efficiency and sometimes
performance". And the Opus 5 page says the model
"performs best when given the complete task specification up front and left to
run". The docs never discuss mid-turn injection timing itself; the measurement
of that is this project's own, in the harness.

### Asking for faster steering

| # | opened | state | title |
|---|---|---|---|
| [30492](https://github.com/anthropics/claude-code/issues/30492) | 2026-03-03 | open | [Feature Request] Real-time steering: priority message channel for redirecting Claude mid-execution |
| [61274](https://github.com/anthropics/claude-code/issues/61274) | 2026-05-21 | closed | Steering ignored: messages typed during long agent tool-call sequence never reach the model |
| [64624](https://github.com/anthropics/claude-code/issues/64624) | 2026-06-02 | open | Feature: Real-time steering, send message mid-generation without queueing |
| [65827](https://github.com/anthropics/claude-code/issues/65827) | 2026-06-06 | closed | [FEATURE] A PAUSE (Ctrl-Z / suspend) for the agent, distinct from STOP (kill) |

Note 64624's framing: it complains that typing a message **queues** it, and asks
for a way to steer without pressing Escape. That is the exact opposite complaint
to 49373, filed six weeks earlier about the same input box.

Both are right. They are the same person at different moments.

### Reporting what goes wrong when the two are mixed

| # | opened | state | title |
|---|---|---|---|
| [26388](https://github.com/anthropics/claude-code/issues/26388) | 2026-02-17 | closed | Queued messages get misinterpreted when user types during AI response |
| [54031](https://github.com/anthropics/claude-code/issues/54031) | 2026-04-27 | closed | Queued-message ordering is undocumented and appears LIFO in practice |
| [57568](https://github.com/anthropics/claude-code/issues/57568) | 2026-05-09 | closed | Agent reads new user messages after tool-call batches, not mid-flight, causing race conditions during iterative work |
| [57624](https://github.com/anthropics/claude-code/issues/57624) | 2026-05-09 | closed | Queued messages typed during Claude's response are misinterpreted as replies |

26388 and 57624 name a failure this patch does not fix and should not pretend
to: the model sees your words but not **when you wrote them**. You typed "also
fix the tests" before you had read the answer on screen; it arrives looking like
a reply to that answer. Waiting for the turn boundary makes that ordering
predictable, which helps, but the temporal context is still missing.

54031 reports the ordering being not just wrong but **undocumented**, which is
its own problem: you cannot work around behaviour nobody has written down.

---

## 4. How other agents solve it

### Codex separates the two at the protocol level

Not in a blog post. In the app-server API, read from OpenAI's own repository:

```
turn/start       begin a new turn
turn/steer       add user input to an already in-flight regular turn
                 without starting a new turn
turn/interrupt   request cancellation of an in-flight turn
```

Three operations, three contracts. The documentation for `turn/steer` is
explicit that it "does not emit `turn/started`", which is the machine-readable
way of saying a steer is not a new turn.

The terminal UI carries the same split. Its input module holds
`queued_user_messages` and `pending_steers` as **separate structures**, plus a
`rejected_steers_queue` for messages that tried to steer a turn that cannot
accept one. Its own tooltip reads:

> Press Tab to queue a message when a task is running; otherwise it sends
> immediately

So: Enter steers the running turn, Tab queues the next one. Two keys, two
meanings, chosen by you rather than by whichever tool happened to finish first.

**And Codex still shipped a regression.**
[openai/codex#17285](https://github.com/openai/codex/issues/17285), opened
2026-04-10 and still open: *"Queued prompts behave like steer prompts; multiple
queued prompts sent simultaneously."*

That is the most useful single fact on this page. A team that named the two
concepts, built two data structures and two API operations for them, **still**
shipped a build where the queue behaved like a steer. This is a hard problem. It
is not carelessness at Anthropic, and anyone selling it as carelessness is
selling you something.

The difference is that Codex publishes the contract it intends to keep, so a
regression is a bug you can file. Without a stated contract, the same behaviour
is just how it works today.

### Hermes Agent exposes three modes explicitly

[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent),
quoted from its CLI documentation:

| mode | what it does |
|---|---|
| `interrupt` (default) | Your message redirects the active turn. Model generation restarts with displayed reasoning and completed work preserved; running tools finish first |
| `queue` | Your message is silently queued and sent as the next turn after the agent finishes |
| `steer` | Your message is injected into the current run, arriving at the agent after the next tool call, no interrupt, no new turn |

Switchable per session with `/busy queue`, `/busy steer`, `/busy interrupt`.

Two independent teams arrived at the same three-way split. That is a strong
signal that the split is in the problem, not in anyone's taste.

Hermes also documents something worth copying: if a steer cannot be applied
because the agent has not started or an image is attached, it **falls back to
queue behaviour so nothing is lost**, and says so. Failing loudly beats failing
quietly.

### People are building the missing guarantee outside the tool

[jinhuang712/claude-code-queue](https://github.com/jinhuang712/claude-code-queue)
is one of several: a wrapper that defers a message until the current task
finishes.

These are version-specific workarounds, and what makes them worth citing is
not how they work. It is that people are building external infrastructure to buy a
scheduling guarantee the tool does not offer.

### The same demand, off the tracker

The conversation is not confined to GitHub. A sample from Reddit, each thread
verifiable at its link:

- [New Feature? Steer in Real-Time](https://www.reddit.com/r/ClaudeAI/comments/1ms32xe/new_feature_steer_in_realtime/),
  136 upvotes at capture: users discover mid-run messaging and immediately
  disagree about what it does. One reply: "Steering had caused more problems
  than it has solved for me." Another: "sometimes it'll completely lose what
  you added to the command queue".
- [Mid-turn messages: queuing vs steering, what is the actual default?](https://www.reddit.com/r/ClaudeAI/comments/1v683yv/midturn_messages_queuing_vs_steering_whats_the/),
  posted 2026-07-25: "Typing a correction and hoping it
  lands before the wrong file gets written is a coin flip."
- [It's honestly insane that Anthropic still has not...](https://www.reddit.com/r/ClaudeCode/comments/1uzeyaw/its_honestly_insane_that_anthropic_still_has_not/):
  the title carries the mood, and the thread lands on the same three-way split
  this patch implements. The analogy used there is the cleanest plain-language
  version of the whole design: steering changes the route while driving,
  queueing adds a destination for later, stopping pulls the car over.
- [TAB / non-steering message?](https://www.reddit.com/r/ClaudeAI/comments/1uom9s3/tab_nonsteering_message/):
  a user asks for exactly the tab-to-queue key this patch ships. The question
  received zero human replies.
- [What I found parsing 1,700 Claude Code transcripts](https://www.reddit.com/r/ClaudeCode/comments/1pjbriy/what_i_found_parsing_1700_claude_code_transcripts/):
  independent transcript analysis surfaces internal enqueue, dequeue, remove
  and pop-all events, corroborating what this project found in the binary: the
  queue machinery exists inside, it is the explicit control over it that is
  missing.

One more pattern worth naming: across these threads the words queue, steer and
interrupt are used with contradictory meanings, sometimes opposite ones. That
terminology instability is why the on-screen labels here say `[waits]` and
`[jumps in]` instead of reusing the contested words.

---

## 5. What this evidence proves, and what it does not

**It proves** the demand is real, sustained since March 2025, and comes from
two groups wanting opposite defaults. It proves Anthropic has repeatedly fixed
symptoms in this subsystem. It proves at least two other agents concluded the
split has to be explicit. It proves that even a team that made the split
explicit still shipped it broken once.

**It does not prove** that this patch is the right design, that it makes Claude
produce better code, or that the numbers in the [README](../README.md) would
reproduce on your machine. The first is a judgement, the second is an untested
hypothesis, and the third is what the [harness](../harness/) is for.

Claims deliberately not made anywhere in this project:

- "Claude Code has no queue." It has had queue-related behaviour since 0.2.75.
- "Claude Code has no steering." Its changelog announced steering at 0.2.108 and
  has fixed it several times since.
- "Queued messages are LIFO." One issue reports that; it appears to be version
  and surface specific, and it has not been reproduced here as a general rule.
- "This makes Claude write better code." It makes the schedule predictable.
  Whether predictability improves output is a hypothesis worth testing, and it
  is not what the measurements here show.
