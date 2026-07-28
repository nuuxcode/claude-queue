# Why turn boundaries matter

The [README](../README.md) shows that stock Claude Code ran two typed messages
backwards. This page is the argument for why that is worth caring about, and
the history of why the fix has the shape it does.

**Read the first section with a sceptical eye.** It is an argument built on
other people's research, not a measurement of this patch. The measurements are
in the README and in [`harness/`](../harness/), and they deserve a higher
standard of proof than anything here.

---

## The order is not a cosmetic detail

Running two messages backwards sounds like a display annoyance. It is not, and
the reason is one of the better studied failure modes in this field.

When a message lands mid-turn, Claude Code does not simply do it later. It
splits your work into turns **at a boundary you did not choose**, and turn
boundaries are what decide whether a model stays coherent.

### Models are less reliable across turns than within one

In [LLMs Get Lost in Multi-Turn Conversation](https://arxiv.org/abs/2505.06120)
(Laban, Hayashi, Zhou and Neville), 15 models from 8 providers were run over
200,000+ simulated conversations. The paper was named
[one of two Outstanding Papers at ICLR 2026](https://blog.iclr.cc/2026/04/23/announcing-the-iclr-2026-outstanding-papers/).
In that setup, multi-turn performance was **39% lower on average** than the
same tasks given in a single turn.

The decomposition is the part worth reading twice. Aptitude fell around 16%,
while unreliability rose 112%. In their tests the models did not get much less
capable. They got far less predictable: the paper reports performance
"degrading 50 percent points on average between the best and worst simulated
run for a fixed instruction". Same instruction, same model, half the scale
between a good day and a bad one.

Their account of the mechanism reads like a description of the clips in the
README:

> LLMs often make assumptions in early turns and prematurely attempt to
> generate final solutions, on which they overly rely. [...] when LLMs take a
> wrong turn in a conversation, they get lost and do not recover.

Now look at the reordering again. `metrics.py` counts calls to endpoints that
`CHANGELOG.md` was meant to enumerate, and both depend on an API that was still
being written. Running the later message first means answering a question whose
premise does not exist yet. The model does what that paper describes: it
assumes, commits, and carries the assumption forward.

### The mess stays in the window

Practitioners have named the recurring context failures: poisoning, distraction,
confusion, and
[clash](https://www.dbreunig.com/2025/06/22/how-contexts-fail-and-how-to-fix-them.html).
Clash is this one. Two jobs merged into a single turn sit in the same context
referring to each other, and a wrong turn is not discarded when the next message
arrives. It stays there, influencing every later step.

### Long contexts degrade before their stated limit

Chroma's [Context Rot](https://www.trychroma.com/research/context-rot) study
(Hong, Troynikov and Huber, 2025) tested 18 frontier models. Every one of them
degraded as input grew, unevenly, and well before any advertised limit. Blending
three jobs into one turn makes that turn longer than any of the three needed to
be.

Anthropic's own
[guidance on context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
treats context as a finite budget to curate rather than fill.

### So what this patch actually is

Not "a queue". **Control over where your turn boundaries fall**, which is the
lever all of the above says matters. Today that lever is held by whichever tool
call happens to finish next.

**What this is not.** None of those studies tested Claude Code, this patch, or
message queueing. They are evidence about what happens when work is split across
turns badly. The link to this patch is an argument, not a measurement.

---

## This is not just me

The same request keeps arriving in the Claude Code tracker under a new number
each time. Dates and states are as of July 2026.

A shorter list is below. The complete one, with every issue number, title, date
and state read from the GitHub API, plus the changelog evidence and how other
agents solved it, is in [the evidence](the-evidence.md).

| | | |
|---|---|---|
| Feb 2026 | [#25845](https://github.com/anthropics/claude-code/issues/25845) Prompt Queue with Steer Controls | **closed, not planned** |
| Apr 2026 | [#49373](https://github.com/anthropics/claude-code/issues/49373) Queue messages to send at true end-of-turn, not next LLM pause | closed as duplicate |
| Apr 2026 | [#50246](https://github.com/anthropics/claude-code/issues/50246) Message queue mode, queue messages instead of interrupting active tasks | open |
| May 2026 | [#63190](https://github.com/anthropics/claude-code/issues/63190) Deferred Messages, Queue Input for End of Turn | open |

From [#63190](https://github.com/anthropics/claude-code/issues/63190):

> When Claude Code is mid-turn (thinking, calling tools, writing code), the only
> way to send a message is as an **interrupt**. It gets injected at the next
> tool boundary and changes the trajectory of the current task. This creates a
> tension: you often think of the *next* thing you want while watching the
> current task execute, but you have no way to queue it without derailing
> what's in progress.

> There's a meaningful UX gap between "inject this immediately" and "send this
> when you're done." The interrupt model assumes every mid-turn message is
> urgent and contextual to the current step, but often it's just "here's what I
> want next."

From [#49373](https://github.com/anthropics/claude-code/issues/49373), which
names the comparison directly:

> This breaks long autonomous sessions. Codex lets you stack 5 prompts, walk
> away for an hour, and come back to finished work. In Claude Code, there's no
> reliable way to line up follow-ups because you can't predict when the queue
> will flush.

That is accurate. In Codex you press Tab and your prompt waits for the next
turn. You can stack several, leave, and come back to finished work. People who
move between the two tools feel the difference immediately.

---

## Why this is not simply "add a queue"

While those issues were being filed, **other people were asking for the exact
opposite.**

[#64624, June 2026](https://github.com/anthropics/claude-code/issues/64624):

> Currently, typing a message while Claude is generating queues it until the
> current response completes. There is no way to *steer* an in-progress
> response without pressing Escape (which discards all in-progress work).

[#30492](https://github.com/anthropics/claude-code/issues/30492) asks for a
priority channel to redirect Claude mid-execution.

Both camps are right, and neither is wrong. **They are the same person at
different moments.**

- You see Claude editing the wrong file. You want it to hear you **now**.
- You think of the next task. You want it to hear you **later**.

One default cannot serve both. Ship the interrupting one and the queueing camp
is stuck. Ship the queueing one and the steering camp is stuck. That is a
genuinely hard call to make for everyone at once, and it is probably why it
keeps not shipping.

**The fix is not a better default. It is letting you choose per message.**

The tracker history above is evidence that the problem is real and widely felt.
It is not an accusation. Choosing one default for everyone here is a real design
problem, and the reason a per message choice works is precisely that it does not
have to be made.
