"""
claude-queue: type your next instruction without derailing the running one.

    <text>        waits until the current turn finishes  (the default)
    s <text>      jumps in at the next tool boundary     (stock behaviour)
    q <text>      waits, said explicitly
    p <text>      parked: sits in the queue and never runs until you say so

    CLAUDE_QUEUE_DEFAULT=steer    puts the stock behaviour back as the default
    CLAUDE_QUEUE_DRAIN=all        waiting messages all run in one turn instead
                                  of one at a time
    CLAUDE_QUEUE_COLLAPSE=off     draws every waiting message in full, however
                                  tall, instead of folding it to one line
    CLAUDE_QUEUE_PERSIST=off      stops the queue being written to disk, so
                                  nothing comes back after a restart
    CLAUDE_QUEUE_ADOPT=on         lets a session with no queue of its own take
                                  the newest one in the project. Off by
                                  default: it also leaks queues between
                                  unrelated sessions

    tab <text>    sends it with the OPPOSITE timing to your default, so with
                  the stock default put back you get Codex's arrangement:
                  enter steers, tab queues

While messages are waiting:

    a message taller than one line is drawn as its first line and a count of
    the lines it is holding back. The highlighted one is always drawn in full,
    so up and down let you read any of them.

    up / down                     move the highlight through them
    enter                         pull the highlighted one back to edit
    shift+up / shift+down         move it earlier or later in the queue
    left / right                  change what it will do: waits, jumps in,
                                  paused, and round again
    delete / backspace            remove it, when the editor is empty

A paused message is the one that never surprises you. It is queued, drawn and
editable like any other, and no path that picks work will take it, so it waits
there through as many turns as you like. Point at it and press left or right to
give it a mode that runs.

Waiting messages survive a restart. Every change to the queue is written to
this project's .claude directory, in a file named for the session, and the next
session you start in this project brings the messages back as rows reading
[waits, restored]. Resuming the same session finds its own file; picking the
session from the /resume menu forks a new one, which adopts the newest file
this project has waiting and takes it over. None of them run until you send
something yourself: your message goes first, and the restored ones drain after
it, one at a time, in the order they were saved.

One pasted submission can be several messages when its first nonblank line uses
an explicit colon marker. Unmarked lines continue the message above them:

    q: write the notes
    q: run the tests
    and report what broke
    s: check the logs first

Other pasted text is literal. Code such as ``q = deque()`` and ``s = socket()``
is never mistaken for queue instructions.

HOW IT WORKS

Claude Code already tags every queued command with a priority, and already has
two collection points: a mid-turn fold that only accepts high priority, and an
end-of-turn drain that accepts anything. A command tagged "later" fails the
mid-turn filter and is still queued when the turn ends, so the drain takes it.

So this does not build a queue and does not change the collection rules. It
picks the tag, from a marker you type, and strips the marker before sending.

The editing side is the same story: the selector, the highlight and the
one-at-a-time pop are all Claude Code's own code, sitting behind an unreleased
flag, switched on at three call sites rather than wholesale. Reordering is the
one exception, the only genuinely new operation here, and it lives in the queue
module next to everything else that mutates the queue.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ccpatch import Edit, Patch, PatchError, main  # noqa: E402

# The short forms are commands. The English words "queue" and "steer" are not:
# silently eating the first word of "Queue depth is high" is worse than losing
# two redundant aliases. Pasted multi-job batches use the colon-only form so
# ordinary pasted code such as ``q = deque()`` stays literal.
MARKER = r"/^(q|s|p)(?::|\s)\s*/i"
PASTE_MARKER = r"/^(q|s|p):\s*/i"

# q waits, s jumps in, p is parked and never runs until you change it.
PRI_OF_MARKER = '(__qa)=>__qa==="q"?"later":__qa==="p"?"paused":"next"'

# "paused" is deliberately not a key in Claude Code's own priority table
# {now:0,next:1,later:2}. Every place that chooses a command to run compares
# that table's value, and a missing key compares false against everything:
# the mid-turn fold asks `table[p] <= table["next"]`, and both peek and dequeue
# scan for `table[p] < Infinity`. So a paused message is skipped by all three
# without a single new gate in the running path. It stays in the queue, drawn
# and editable, until you give it a priority that means something.
PAUSED = "paused"

# The default when you type no marker. "later" means wait for the end of the
# turn. Set CLAUDE_QUEUE_DEFAULT=steer to get stock behaviour back.
DEFAULT_EXPR = 'process.env.CLAUDE_QUEUE_DEFAULT==="steer"?void 0:"later"'


def _resolve(m):
    """Work out the priority once, before the command object is built.

    Doing it here rather than at the enqueue means the idle path gets the
    cleaned text too, so the marker never reaches the model whether Claude was
    busy or not. Two guards: prompts only, so a shell command starting with "q"
    can never be corrupted, and never strip a message down to nothing.

    It also decides whether one submission is one message or several.

    **In an explicit pasted batch, a colon marker starts a message. A line
    without one continues the message above it.** So this is three jobs, and
    the second is two lines long:

        q: write the notes
        q: run the tests
        and then tell me what broke
        s: check the logs first

    That rule means multi-line jobs still work, which the earlier all-or-nothing
    version could not express: it split only when EVERY line was marked, so
    there was no way to queue three things where one of them needed a second
    line.

    A paste with no leading colon marker is always one literal message. That
    includes code containing lines such as ``q = deque()`` or ``s = socket()``,
    and a paragraph followed later by something that resembles a marker.

    It is also where restored messages are released. A resumed session holds
    everything it brought back until you send something, and this runs on every
    submission, whatever its mode, so it is the one place that means "the person
    is back" without having to guess at keystrokes.
    """
    pre = (
        "globalThis.__qsHold=void 0;"
        "let __qsp={default_expr},__qsx=null,__qsf=null,"
        "__qsPri={pri_of},__qsi=globalThis.__qsInvert,"
        "__qsa=globalThis.__qsPastes;"
        "globalThis.__qsInvert=void 0;globalThis.__qsPastes=void 0;"
        "if(typeof __qsi===\"string\"&&__qsi==={val}){{"
        '__qsp=__qsp==="later"?"next":"later"}}'
        'if({mode}==="prompt"&&typeof {val}==="string"){{'
        "let __qspaste=Array.isArray(__qsa)&&__qsa.some((__qa)=>"
        "typeof __qa===\"string\"&&__qa&&{val}.includes(__qa)),"
        "__qsl={val}.split(`\\n`),__qsm=__qspaste?{paste_marker}:{marker},"
        "__qsn=__qsl.find((__qa)=>__qa.trim()),"
        "__qsbat=!__qspaste||!!(__qsn&&{paste_marker}.test(__qsn)),"
        "__qsf=(__qa)=>{{let __qb=__qsm.exec(__qa);"
        "return __qb&&__qa.slice(__qb[0].length).trim()?__qb:null}};"
        "if(__qsbat&&__qsl.some(__qsf)){{"
        "__qsx=[];"
        "__qsl.forEach((__qa)=>{{let __qb=__qsf(__qa);"
        "if(__qb)__qsx.push({{v:__qa.slice(__qb[0].length).trim(),"
        "p:__qsPri(__qb[1][0].toLowerCase())}});"
        "else if(__qsx.length)__qsx[__qsx.length-1].v+=`\\n`+__qa;"
        "else if(__qa.trim())__qsx.push({{v:__qa,p:__qsp}});}});"
        "__qsx=__qsx.map((__qy)=>({{...__qy,v:__qy.v.replace(/\\s+$/,\"\")}}))"
        ".filter((__qy)=>__qy.v.trim());"
        "if(__qsx.length<2){{"
        "if(__qsx.length===1){{__qsp=__qsx[0].p,{val}=__qsx[0].v;"
        'if(typeof {raw}==="string"){raw}={val};}}'
        "__qsx=null}}else{{"
        "{val}=__qsx.map((__qy)=>__qy.v).join(`\\n`);"
        'if(typeof {raw}==="string"){raw}={val};}}'
        "}}}}"
    ).format(mode=m.group("mode"), val=m.group("val"), raw=m.group("raw"),
             marker=MARKER, paste_marker=PASTE_MARKER,
             default_expr=DEFAULT_EXPR, pri_of=PRI_OF_MARKER)
    return pre + m.group(0)


def _no_turn_for_paused(m):
    """Do not start a turn for a submission that is entirely paused.

    The prompt box begins the visible part of a turn before anything has
    decided what the message is: it stamps a turn start time, which is what
    draws the working indicator and the seconds counting up beside it. For
    every other message that is right, because a turn really is about to
    begin. A paused message never begins one, so the indicator had nothing to
    end it and span forever over an idle session.

    Driven to be sure of the cause rather than guessing at it: the message
    itself never reached the model, no transcript was written after a minute,
    and the footer never offered "esc to interrupt". Deleting the paused row
    left the indicator spinning on an empty queue, which is what ruled out the
    queue as its source and left the clock.

    The test has to read the submission exactly the way the resolver does,
    not merely look at its first line. A batch that mixes a paused line with a
    runnable one really does start a turn, and skipping the clock there would
    break the honest case to fix the dishonest one. So this groups the lines
    the same way: a marked line starts a message, an unmarked line continues
    the one above it, and an unmarked line before any marker is a message at
    your default. Only when every message that comes out of that is paused is
    the clock skipped.

    It also has to honour the paste rule, because the two disagree about what
    a marker is. Typed text accepts "p ..." and "p: ..."; pasted text accepts
    only the colon form, so pasted "p alo" is literal and really does run. The
    list of recent pastes is still on hand at this point, which is what makes
    the two able to agree.
    """
    return (
        "if({wf}(({js})=>{js}+1),{dr}.clearBuffer(),{oue}.current=!1,"
        '!{jn}&&{ih}==="prompt"&&!{oe}.isRemoteMode)'
        "(globalThis.__qsAllPaused??=(__qt)=>{{"
        "let __qs=String(__qt||\"\"),__qa=globalThis.__qsPastes,"
        "__qpaste=Array.isArray(__qa)&&__qa.some((__qb)=>"
        "typeof __qb===\"string\"&&__qb&&__qs.includes(__qb)),"
        "__qm=__qpaste?{paste_marker}:{marker},"
        "__ql=__qs.split(`\\n`),__qn=__ql.find((__qb)=>__qb.trim()),"
        "__qbat=!__qpaste||!!(__qn&&{paste_marker}.test(__qn));"
        "if(!__qbat)return!1;"
        "let __qf=(__qb)=>{{let __qc=__qm.exec(__qb);"
        "return __qc&&__qb.slice(__qc[0].length).trim()?__qc:null}};"
        "if(!__ql.some(__qf))return!1;"
        "let __qx=[];"
        "__ql.forEach((__qb)=>{{let __qc=__qf(__qb);"
        "if(__qc)__qx.push(__qc[1][0].toLowerCase());"
        "else if(!__qx.length&&__qb.trim())__qx.push(\"*\")}});"
        "return __qx.length>0&&__qx.every((__qb)=>__qb===\"p\")}})"
        "({yt})||({oh}({yt}),{oo}())"
    ).format(wf=m.group("wf"), js=m.group("js"), dr=m.group("dr"),
             oue=m.group("oue"), jn=m.group("jn"), ih=m.group("ih"),
             oe=m.group("oe"), oh=m.group("oh"), yt=m.group("yt"),
             oo=m.group("oo"), marker=MARKER, paste_marker=PASTE_MARKER)


def _queue_when_paused(m):
    """A paused message goes to the queue even when nothing is running.

    Submitting while Claude is idle skips the queue entirely: the message
    becomes the turn and runs. That is right for every other mode and wrong for
    this one, because the whole point of a paused message is that it does not
    run until you say so.

    Rather than teach the idle path to hold something back, this widens the
    test for "this belongs in the queue". The branch it joins already enqueues
    with the resolved priority, clears the editor, and reports the message as
    queued, so a paused message typed into an idle session takes exactly the
    same path as one typed into a busy one, and there is no second version of
    that code to keep in step.

    A mixed batch is not covered here on purpose. If any line is runnable the
    submission is still a real turn, so it goes down the idle path and the
    split below picks the first runnable line to run.
    """
    return (
        'if({r}.isActive||{n}||__qsp==="{paused}"'
        '||__qsx&&__qsx.every((__qy)=>__qy.p==="{paused}")){{'
        'if({o}!=="prompt"&&{o}!=="bash"){{'
        '{pe}("prompt_queued","mode_not_queueable");return}}'
    ).format(r=m.group("r"), n=m.group("n"), o=m.group("o"), pe=m.group("pe"),
             paused=PAUSED)


def _remember_paste(m):
    """Remember exact bracketed-paste text until the next submit."""
    return m.group(0) + (
        "globalThis.__qsPastes??=[];"
        "globalThis.__qsPastes.push({text});"
    ).format(text=m.group("text"))


def _priority(m):
    """Attach the resolved priority, or enqueue one message per marked line.

    Each split line is enqueued as its own command object, so the queue holds
    distinct objects. That matters beyond tidiness: the queue identifies a
    message by object identity when it is removed or moved, and reusing one
    object would make three rows that cannot be told apart.

    preExpansionValue is dropped on a split, because it holds the raw text of
    the whole block and carrying it onto each line would be a lie about what
    that line was.
    """
    return (
        "(__qsx?({fe},void 0):"
        "xT({{...{cmd},value:{val}.trim(),"
        "preExpansionValue:{cmd}.preExpansionValue?.trim(),"
        "...__qsp?{{priority:__qsp}}:{{}}}}))"
    ).format(
        cmd=m.group("cmd"), val=m.group("val"),
        fe=("__qsx.forEach((__qy)=>xT({{...{cmd},value:__qy.v,"
            "preExpansionValue:void 0,priority:__qy.p}}))").format(cmd=m.group("cmd")),
    )


def _idle_split(m):
    """Split works when Claude is idle too: the first job runs, the rest wait.

    Without this, a block of marked lines typed into a session that is doing
    nothing arrives as one message. That is how it looked to Mounssif, who
    reported the split "only works when something is already queued": his
    session had been interrupted, so it was idle, and the whole block ran as a
    single prompt.

    Idle is not a reason to ignore what you asked for. There is simply no queue
    to put the FIRST job into, because nothing is running, so it becomes the
    turn and everything after it queues behind it. The result is the same list
    running in the same order either way, which is the point.
    """
    return (
        'be("prompt_submit"),'
        '__qsf=__qsx?__qsx.find((__qy)=>__qy.p!=="{paused}")??__qsx[0]:null,'
        "__qsx&&__qsx.forEach((__qy)=>{{if(__qy!==__qsf)"
        "xT({{...{j},value:__qy.v,preExpansionValue:void 0,"
        "priority:__qy.p}})}}),"
        "await {fn}({{inputSource:{a},queuedCommands:["
        "__qsf?{{...{j},value:__qsf.v,preExpansionValue:void 0,"
        "...__qsf.p?{{priority:__qsf.p}}:{{}}}}:{j}],"
    ).format(fn=m.group("fn"), a=m.group("a"), j=m.group("j"), paused=PAUSED)

def _tab_names(js):
    """The submit callback and the just-submitted flag, found by shape."""
    hits = list(re.finditer(
        r"if\((\w+)\)\1\((\w+)\.text\),(\w+)=!0;return \2\}", js))
    if len(hits) != 1:
        raise PatchError(
            f"claude-queue: expected exactly one submit path in the text input, "
            f"found {len(hits)}. "
            "Claude Code's internals changed; refusing to guess.")
    m = hits[0]
    return {"submit": m.group(1), "buf": m.group(2), "flag": m.group(3)}


def _tab_key(m, js):
    """Tab sends the message with the OPPOSITE timing to your default.

    Tab does nothing in the prompt box today: the switch has a bare
    `case"tab":return`, and the completion menu takes the key earlier when one
    is open, so this only ever fires when Tab would otherwise be wasted.

    It flips the DEFAULT, not the message. Type a marker and the marker wins,
    because an explicit instruction should not be quietly reversed by a
    keystroke.

    This is Codex's design rather than Codex's key assignment. Its editor has a
    setting for the default plus a shortcut that uses the opposite mode for one
    message, which works whichever way round you like your default. Set
    CLAUDE_QUEUE_DEFAULT=steer and you get Codex's exact keys: enter steers,
    tab queues.
    """
    n = _tab_names(js)
    return (
        'case"return":if({k}.ctrl){{'
        "if(!{w}.text&&globalThis.__qsRun?.())return;return}}"
        "return {ae}({k});"
        "case\"enter\":return {w}.insert(`\n`);"
        'case"tab":if({submit}&&{w}.text.trim()){{'
        "globalThis.__qsInvert={w}.text,{submit}({w}.text),{flag}=!0;return {w}}}"
        "return}}"
    ).format(k=m.group("k"), ae=m.group("ae"), w=m.group("w"),
             submit=n["submit"], flag=n["flag"])

def _no_abort(m):
    """A waiting message must never kill the turn it is waiting for.

    There is a path where submitting anything while a cancelable tool runs
    aborts the whole turn. As of 2.1.220 no tool declares itself cancelable, so
    it is unreachable, but the event and its schema exist. If it is ever turned
    on, a waiting message would abort the very turn it was told to wait for.
    """
    return (
        'if({e}.hasInterruptibleToolInProgress&&__qsp!=="later"'
        '&&__qsp!=="{paused}"){{{log}'
    ).format(e=m.group("e"), log=m.group("log"), paused=PAUSED)


def _one_at_a_time(m):
    """Run waiting messages one at a time instead of merging them into one turn.

    Claude Code merges consecutive queued prompts that match on a list of
    fields, so two messages typed while it works arrive together as a single
    turn. That is reasonable for an interruption, where both are corrections to
    the same thing in flight. It is wrong for a queue: each item is its own job,
    and merging them means the first one's result cannot inform the second.

    The branch immediately above this one already takes exactly one command,
    for slash and bash input, so this mirrors what is already there rather than
    inventing a mechanism.

    One at a time is the default. CLAUDE_QUEUE_DRAIN=all restores the stock
    behaviour for anyone who wants everything delivered in one go. Only waiting
    messages are affected either way; interrupting ones keep the stock rule.

    The sweep also gains a priority check. Stock filters it on mode alone, so
    with one interrupting and one waiting message both queued at the end of a
    turn, the interrupting one is taken first and drags the waiting one into
    the same turn, silently undoing its wait. Claude Code's OTHER drain path
    already requires matching priority to merge, so this makes the two agree.
    """
    return (
        'if({slash}({t})||{t}.mode==="bash"){{let {i}=[{one}(({s})=>{s}==={t})];'
        'return {reg}({i}),{exec}({i}).finally(()=>{unreg}({i})),{{processed:!0}}}}'
        'let {r}={t}.mode,{n}=(process.env.CLAUDE_QUEUE_DRAIN==="all"'
        '||{t}.priority!=="later")'
        '?{deqall}(({o})=>{qh}({o})&&!{slash}({o})&&{o}.mode==={r}'
        '&&{o}.priority==={t}.priority)'
        ':[{one}(({s})=>{s}==={t})];'
    ).format(**m.groupdict())


def _queue_names(js):
    """
    Find the minified names this patch has to call, by shape.

    Claude Code already has everything needed to edit one queued message at a
    time. It exports popEditableAt next to popAllEditable, and the up arrow
    simply calls the wrong one. Using it means naming three functions whose
    real identifiers change with every release, so they are located by the
    shapes around them rather than hardcoded.
    """
    def find(pattern, what):
        hits = set(re.findall(pattern, js))
        if len(hits) != 1:
            raise PatchError(
                f"claude-queue: expected exactly one {what}, found {len(hits)}. "
                "Claude Code's internals changed; refusing to guess."
            )
        return hits.pop()

    return {
        "popat": find(r"(\w+)=\w+\.popEditableAt\b", "popEditableAt binding"),
        "getq": find(r"(\w+)=\w+\.getCommandQueue,", "getCommandQueue binding"),
        # The editable predicate, taken from the one place it is used bare.
        "editable": find(r"\.getCommandQueue\(\)\.some\((\w+)\)\}", "editable test"),
        # The queue's own "something changed" call: refreezes the snapshot the
        # UI reads and emits. Anything that mutates the array has to end on it.
        "notify": find(
            r"function (\w+)\(\)\{\w+=Object\.freeze\(\[\.\.\.\w+\]\),\w+\.emit\(\)\}",
            "queue notifier",
        ),
    }


def _session_names(js):
    """
    Find the session this queue belongs to, and the agent it runs as.

    Both are needed by the saving side. The session id names the file, so that
    resuming a session finds its own messages and nothing else. The agent id has
    to be stamped on a restored message, because the queue only offers a command
    to the main thread when the two match, and a saved id from yesterday would
    be the wrong one today.

    The session id is read from the state object rather than through the
    accessor next to it. The accessor answers with whichever agent is running
    at the time, so a queue change that happens while a subagent is working
    would be filed under the subagent. The queue is the main thread's, so the
    main thread's id is the honest name for it.
    """
    def find(pattern, what):
        hits = set(re.findall(pattern, js))
        if len(hits) != 1:
            raise PatchError(
                f"claude-queue: expected exactly one {what}, found {len(hits)}. "
                "Claude Code's internals changed; refusing to guess."
            )
        return hits.pop()

    return {
        "state": find(
            r"function \w+\(\)\{return \w+\(\)\?\.sessionId\?\?(\w+)\.sessionId\}",
            "session state object",
        ),
        "agent": find(
            r"function \w+\(\w+\)\{return \w+\.agentId===(\w+)\(\)\}",
            "agent id getter",
        ),
    }


def _edit_one(m, js):
    """Bring back ONE queued message wherever the whole queue was taken.

    Stock hands the entire queue to the editor as a single blob joined with
    newlines. This pops the newest and leaves the rest queued.

    This is now the fallback rather than the main path: with the selector below
    turned on, the up arrow no longer reaches here. It still covers Escape,
    which also empties the queue into the editor.

    popAllEditable keeps its other caller, where a session hands its pending
    work over on cancel and really does want all of it.
    """
    n = _queue_names(js)
    return (
        "let {w}={popat}({getq}().filter({editable}).length-1,{t},{c});"
        "if(!{w})return!1;{rest}\"input_queue_pop_to_edit\""
    ).format(w=m.group("w"), t=m.group("t"), c=m.group("c"),
             rest=m.group("rest"), **n)


def _remember_slot(m, js):
    """Remember which slot a message came out of, so it can go back there.

    Editing a queued message and sending it again put it at the BOTTOM of the
    queue, because sending anything appends. So editing the first of three
    silently made it the last, which is a worse outcome than not editing it.

    The selector index counts only editable messages, while enqueue mutates the
    raw queue, which can also contain task notifications, metadata, and
    non-human entries. Find the selected object in the raw queue before it is
    popped, then park that raw index for the next enqueue.
    """
    n = _queue_names(js)
    return (
        "let {i}={ht}.getState().queueEditIndex;"
        "if({i}===null)return!1;"
        "let __qsa={getq}(),__qso=__qsa.filter({editable})[{i}];"
        "globalThis.__qsAt=__qsa.indexOf(__qso);"
        "let {r}={pop}({i},{t},{c});"
    ).format(i=m.group("i"), ht=m.group("ht"), r=m.group("r"),
             pop=m.group("pop"), t=m.group("t"), c=m.group("c"), **n)


def _enqueue_at_slot(m):
    """Put an edited message back where it came from, not at the end.

    Only the very next enqueue is affected, and the slot is cleared whether it
    was used or not, so a normal message typed later still goes to the back.
    """
    return (
        "function {fn}({a}){{"
        "let __qi=globalThis.__qsAt;globalThis.__qsAt=void 0;"
        'let __qo={{...{a},priority:{a}.priority??"next",'
        "timestamp:{a}.timestamp??new Date().toISOString()}};"
        'if(typeof __qi==="number"&&__qi>=0&&__qi<={arr}.length)'
        "{arr}.splice(__qi,0,__qo);else {arr}.push(__qo);"
        "{tail}"
    ).format(fn=m.group("fn"), a=m.group("a"), arr=m.group("arr"),
             tail=m.group("tail"))


def _keep_marker(m):
    """Give a message its marker back when it comes back for editing.

    The marker is stripped when you send a message, so nothing reaches the
    model that you did not type. That is right, and it collided with editing:
    pulling an "s" message back gave you plain text, and sending it again made
    it a WAITING message. An urgent interruption silently became "later" and
    nothing on screen said so.

    So a message whose priority differs from your default comes back with the
    marker that reproduces it. Send it unchanged and the timing is unchanged.
    Delete the marker and it becomes an ordinary queued message, which is now
    a choice you can see rather than one made for you.
    """
    return (
        "function {fn}({i},{cur},{off}){{"
        "let {c}={arr}.filter({ed})[{i}];if(!{c})return;"
        'let __qd=process.env.CLAUDE_QUEUE_DEFAULT==="steer"?"next":"later";'
        'let __qm={c}.priority&&{c}.priority!==__qd'
        '?({c}.priority==="later"?"q ":'
        '{c}.priority==="{paused}"?"p ":"s "):"";'
        "let {v}=__qm+{raw}({c}.value),"
    ).format(fn=m.group("fn"), i=m.group("i"), cur=m.group("cur"),
             off=m.group("off"), c=m.group("c"), arr=m.group("arr"),
             ed=m.group("ed"), v=m.group("v"), raw=m.group("raw"),
             paused=PAUSED)


def _move_fn(m, js):
    """Teach the queue to swap two waiting messages, and nothing more.

    Reordering is the one queue operation Claude Code does not already have, so
    this is the only genuinely new behaviour in the patch. It stays inside the
    queue module, where the array and the "something changed" call both live, so
    the UI redraws through the same path every other queue operation uses.

    It only ever swaps two messages that share a priority. That is not a
    restriction for its own sake: an interrupting message always drains before a
    waiting one whatever the list order says, so letting you drag a waiting
    message above an interrupting one would move it on screen and change nothing
    about when it runs. A list that lies about the order is worse than a list
    you cannot fully rearrange. Within one priority the list order IS the run
    order, so within one priority you can rearrange freely.

    Returns the new index, or -1 when there is nothing to swap with, so the
    caller knows whether to move the highlight.
    """
    n = _queue_names(js)
    return (
        "globalThis.__qsMove=function(__qi,__qd){{"
        "let __qe={arr}.filter({ed}),__qc=__qe[__qi];"
        "if(!__qc||__qd!==1&&__qd!==-1)return-1;"
        'let __qp=__qc.priority??"next",__qj=-1;'
        "for(let __qk=__qi+__qd;__qk>=0&&__qk<__qe.length;__qk+=__qd)"
        'if((__qe[__qk].priority??"next")===__qp){{__qj=__qk;break}}'
        "if(__qj<0)return-1;"
        "let __qa={arr}.indexOf(__qc),__qb={arr}.indexOf(__qe[__qj]);"
        "if(__qa<0||__qb<0)return-1;"
        "{arr}[__qa]=__qe[__qj],{arr}[__qb]=__qc,{notify}();"
        "return __qj}};"
        "globalThis.__qsDrop=function(__qi){{"
        "let __qe={arr}.filter({ed}),__qc=__qe[__qi];"
        "if(!__qc)return!1;"
        "let __qa={arr}.indexOf(__qc);"
        "if(__qa<0)return!1;"
        "{arr}.splice(__qa,1),{notify}();"
        "return!0}};"
        "globalThis.__qsSetMode=function(__qi,__qd){{"
        "let __qe={arr}.filter({ed}),__qc=__qe[__qi];"
        "if(!__qc||__qd!==1&&__qd!==-1)return!1;"
        'let __qm=["later","next","{paused}"],'
        '__qk=__qm.indexOf(__qc.priority??"next");'
        "if(__qk<0)__qk=0;"
        "__qc.priority=__qm[(__qk+__qd+__qm.length)%__qm.length];"
        "globalThis.__qsFrozen=!0,{notify}();return!0}};"
        "globalThis.__qsPoke={notify};"
    ).format(arr=m.group("arr"), ed=n["editable"], notify=n["notify"],
             paused=PAUSED) + m.group(0)


def _shift_arrows(m):
    """Make shift with an arrow key mean "move this message".

    Both arrows already return early on shift, so shift plus an arrow does
    nothing at all today in the prompt box. That makes it free to take: no
    existing behaviour is displaced, and the plain arrows keep meaning what they
    have always meant.

    The call goes through a global because this is the generic text input, used
    by inputs that know nothing about a queue. It answers false unless a queued
    message is actually highlighted, so every other input is untouched.
    """
    k = m.group("k")
    return (
        'case"up":if({k}.shift){{globalThis.__qsReorder?.(-1);return}}'
        "if({k}.ctrl||{k}.meta)return;return {up}();"
        'case"down":if({k}.shift){{globalThis.__qsReorder?.(1);return}}'
        "if({k}.ctrl||{k}.meta)return;return {dn}();"
    ).format(k=k, up=m.group("up"), dn=m.group("dn"))


def _install_reorder(m):
    """Wire the key to the queue. Deliberately does NOT move the highlight.

    The obvious version sets the highlight to the new index right here, and it
    is wrong: the effect below also moves the highlight, by following the
    message, and the two corrections cancel each other so the highlight bounces
    back on the next render. One owner for the highlight, and it is the effect.

    So this only asks the queue to move something. It answers false when
    nothing is highlighted, which is what keeps every other text input in the
    app unaffected by the key.

    The run gesture also lifts the hold a resumed session puts on the messages
    it brought back. That hold exists so a queue saved yesterday cannot start
    running because you opened a terminal, and it is released by you sending
    something, on the reasoning that sending is the one act that certainly
    means you are back. Pressing a key while pointing at one specific message
    means it just as certainly, and without this the release did nothing at
    all for exactly the messages most likely to need it: a restored row moved
    off paused, which is where Mounssif found it. Stepping off the list is
    deliberately not enough, because that can be the tail end of browsing.
    """
    return m.group(0) + (
        ",__qsRe=globalThis.__qsReorder=(__qsd)=>{{"
        "let __qsi={ht}.getState().queueEditIndex;"
        "if(__qsi===null||__qsi===void 0)return!1;"
        "globalThis.__qsMove?.(__qsi,__qsd);"
        "return!0}}"
        ",__qsRm=globalThis.__qsRemove=()=>{{"
        "let __qsi={ht}.getState().queueEditIndex;"
        "if(__qsi===null||__qsi===void 0)return!1;"
        "return globalThis.__qsDrop?.(__qsi)===!0}}"
        ",__qsMd=globalThis.__qsMode=(__qsd)=>{{"
        "let __qsi={ht}.getState().queueEditIndex;"
        "if(__qsi===null||__qsi===void 0)return!1;"
        "return globalThis.__qsSetMode?.(__qsi,__qsd)===!0}}"
        ",__qsRn=globalThis.__qsRun=()=>{{"
        "let __qsi={ht}.getState().queueEditIndex;"
        "if(__qsi===null||__qsi===void 0)return!1;"
        "globalThis.__qsHold=void 0;{lr}(null);return!0}}"
    ).format(ht=m.group("ht"), lr=m.group("lr"))


def _mode_arrows(m):
    """Left and right change what the highlighted message is going to do.

    The cycle is one loop in both directions, waits -> jumps in -> paused, so
    the two keys are opposites and neither is a dead end.

    The guard is the same one the delete key uses: the editor has to be empty
    and a queued message has to be highlighted. Both are already true whenever
    you are walking the queue, because typing anything clears the highlight,
    and both keys already do nothing on an empty line, so this takes no
    behaviour away from the text editor.

    It sits after the modified-key branches so ctrl, meta, fn and super keep
    their word-and-line movement untouched, and before the left arrow's own
    detach gesture, which is the one thing this genuinely shadows. That is a
    deliberate trade: the gesture needs an empty editor, and so does this, but
    this also needs a message highlighted, which only happens after you press
    up. Inside the queue, the arrows belong to the queue.
    """
    return (
        'case"{key}":if({k}.superKey)return {w}.{home}();'
        "if({k}.ctrl||{k}.meta||{k}.fn)return {w}.{word}();"
        "if(!{k}.shift&&!{w}.text&&globalThis.__qsMode?.({dir}))return;"
    ).format(key=m.group("key"), k=m.group("k"), w=m.group("w"),
             home=m.group("home"), word=m.group("word"),
             dir="1" if m.group("key") == "right" else "-1")


def _work_only(m):
    """A paused message is not work, so it must not make the session look busy.

    Two questions in the queue module mean "is there anything to do": the main
    thread's queue length, which decides whether the session is busy, and
    whether the queue has anything in it at all. Both count rows, and a paused
    row is a row, so a queue holding nothing but paused messages reported a
    busy session that never finished and a drain that never had anything to
    drain.

    Answering both from the runnable rows only is the honest fix, and it is one
    place rather than every caller. The drawing side is untouched, so a paused
    message is still listed, still walkable, still editable. It has simply
    stopped claiming to be pending work, which is exactly what pausing it
    meant.
    """
    return (
        'function {x}(){{return {pr}({arr}.filter('
        '(__qc)=>__qc.priority!=="{paused}"),{qh})}}'
        'function {o}(){{return {arr}.some('
        '(__qc)=>__qc.priority!=="{paused}")}}'
    ).format(x=m.group("x"), pr=m.group("pr"), arr=m.group("arr"),
             qh=m.group("qh"), o=m.group("o"), paused=PAUSED)


def _forget_slot(m):
    """Forget which slot a message came from once you clear the editor.

    Pulling a message back records its slot so that sending it again puts it
    where it was. That record has to expire, and it did not: abandoning the edit
    left the slot parked, so the next thing typed, a completely unrelated
    message, was filed into the gap the old one had left. Queue three, pull the
    first one back, change your mind, type something new, and it arrived at the
    FRONT of the queue.

    The bug hid behind Escape. Escape stops the turn, stopping the turn releases
    the queue, and by the time anything was checked the queue had drained and
    the evidence was gone. It only appeared once the test abandoned the edit by
    clearing the text instead of pressing Escape.

    Emptying the editor is the honest signal for "not that message any more".
    Anything still in the box is a draft of what was pulled back, and sending
    that should still return it to its own slot.
    """
    return m.group(0).replace(
        "if({it}.current==={te})return;".format(it=m.group("it"), te=m.group("te")),
        "if({it}.current==={te})return;if(!{te})globalThis.__qsAt=void 0;".format(
            it=m.group("it"), te=m.group("te")),
        1)


def _follow_message(m):
    """Keep the highlight on the message you picked, not on a position.

    Stock tracks a position and only clamps it: if the queue shrinks past the
    end, the highlight jumps to the last message. That is fine when the last
    message is what you were on, and wrong the rest of the time. Queue three,
    press up twice to sit on the middle one, and the turn ends: one message
    drains from the top, the two below shift up, and the highlight is now on a
    message you never selected. Press enter and you edit the wrong one.

    Nothing on screen tells you this happened, which is what makes it worth
    fixing rather than documenting.

    So the highlight follows the message itself. The queue holds the same
    objects across a change, so the message you picked can be found again by
    identity: it moves with the message when the queue drains above it, it
    moves with the message when you reorder it, and it clears when the message
    you were pointing at is gone. The old clamp stays as the fallback for the
    one case identity cannot answer, a message that left while you were on it.

    This effect is also the one place that always knows where the highlight
    is, so it publishes it. Nothing drains while you are pointing at a queued
    message, which is what makes changing a mode usable: without it, moving a
    paused message onto "waits" in an idle session ran it on the way past, so
    you could never reach the third mode at all.

    Letting go has to wake the queue again. The drain is watching the queue,
    not the highlight, so clearing the highlight alone would leave it asleep
    with work sitting in front of it. On the way from a highlight to none, this
    pokes the queue's own "something changed" call, which is the same door
    every other queue operation knocks on. It cannot loop: the poke re-runs
    this effect with no highlight either side, which pokes nothing.
    """
    return (
        "{cr}={hook}();"
        "let __qsQ={pi}.useRef({cr});"
        "{pi}.useEffect(()=>{{"
        "let __qsB=globalThis.__qsSel;globalThis.__qsSel={gr};"
        "if({gr}===null||{gr}===void 0){{"
        "let __qsF=globalThis.__qsFrozen;globalThis.__qsFrozen=!1;"
        "if(__qsF||__qsB!==null&&__qsB!==void 0)globalThis.__qsPoke?.()}}"
        "let __qsP=__qsQ.current;__qsQ.current={cr};"
        "if({gr}===null)return;"
        "let __qsE={cr}.filter({ed});"
        "if(__qsE.length===0){{{lr}(null);return}}"
        "let __qsW=__qsP?__qsP.filter({ed})[{gr}]:void 0,"
        "__qsN=__qsW?__qsE.indexOf(__qsW):-1;"
        "if(__qsN>=0){{if(__qsN!=={gr}){lr}(__qsN);return}}"
        "if({gr}>__qsE.length-1){lr}(__qsE.length-1)"
        "}},[{cr},{gr},{lr}]);"
    ).format(cr=m.group("cr"), hook=m.group("hook"), pi=m.group("pi"),
             gr=m.group("gr"), ed=m.group("ed"), lr=m.group("lr"))


def _delete_key(m):
    """Delete or backspace removes the highlighted message, but only when the
    editor is empty.

    Both keys already do nothing at that moment, because there is no text to
    delete, so nothing is displaced. The empty-editor condition is what makes
    this safe rather than terrifying: the instant you type anything the
    highlight clears, so there is no state where backspace could eat a queued
    message while you thought you were editing a word.
    """
    k, w = m.group("k"), m.group("w")
    return (
        'case"backspace":if(!{w}.text&&globalThis.__qsRemove?.())return;'
        "if({k}.superKey)return {ce}();if({k}.meta||{k}.ctrl)return {se}();"
        "return {w}.deleteTokenBefore()??{w}.backspace();"
        'case"delete":if(!{w}.text&&globalThis.__qsRemove?.())return;'
        "if({k}.superKey)return {oe}();if({k}.meta)return {oe}();"
        "return {w}.del();"
    ).format(k=k, w=w, ce=m.group("ce"), se=m.group("se"), oe=m.group("oe"))


def _enable_selector(m):
    """
    Turn on the queue selector Claude Code already has, and nothing else.

    Popping one message at a time is still the wrong shape for the job. To
    reach the FIRST queued message you have to pop everything above it, so by
    the time you get there the editor holds all of them again. What you
    actually want is to point at one message and edit only that one.

    Claude Code has exactly that: up and down move a highlight through the
    queue, and submitting pops only the highlighted message. It is finished
    code sitting behind a flag, CLAUDE_CODE_KB_COHESION_FIXES.

    Setting that flag is not the answer, because it also rewires Escape,
    Ctrl-C, Ctrl-D and exit. Measured: with the flag on, Escape interrupted the
    running command. Rewiring the key everyone uses to mean "stop" is not
    something to switch on underneath somebody who asked for a queue.

    So the gate is opened at exactly three call sites, the two arrow keys and
    the submit that consumes the selection. Every other use of the flag is left
    alone, so Escape and the rest keep behaving the way they do today.
    """
    return m.group(0).replace(m.group("sv") + "()", "!0", 1)


def _label(m):
    """Label every queued message with what it is going to do.

    The first version labelled only the exception, on the reasoning that a tag
    on every line is noise once waiting is the default. Using it proved that
    wrong: an unlabelled message gives you no confirmation at all, so "it was
    queued" and "my marker was not recognised" look identical, which is the one
    thing you actually need to know at the moment you press enter.

    So both states are named. CLAUDE_QUEUE_LABELS=off turns them off for anyone
    who preferred the quiet version.

    A message brought back from a previous run says so as well, because the one
    thing you need to know about a row you did not just type is that you did not
    just type it. The word goes inside the label rather than taking a line of
    its own: a restored waiting message reads [waits, restored], and a restored
    steer reads [jumps in, restored].

    The flag it reads sits on the stored command next to its priority, so it is
    never part of the text and nothing about it reaches the model.

    This builds a throwaway message purely so the queued list can be drawn, so
    nothing here reaches the model.
    """
    return (
        "function {fn}({arg}){{let {v}={arg}.value;"
        'if({arg}.mode==="bash"&&typeof {v}==="string")'
        "{v}=`<bash-input>${{{v}}}</bash-input>`;"
        'if({arg}.mode==="prompt"&&typeof {v}==="string"'
        '&&process.env.CLAUDE_QUEUE_LABELS!=="off"){{'
        'let __qsr={arg}.restored===!0?", restored":"";'
        'if({arg}.priority==="{paused}"){v}="[paused"+__qsr+"] "+{v};'
        'else if({arg}.priority==="later"){v}="[waits"+__qsr+"] "+{v};'
        'else if({arg}.priority==="next"){v}="[jumps in"+__qsr+"] "+{v};'
        "}}"
        "return {mk}({{content:{v}}})}}"
    ).format(fn=m.group("fn"), arg=m.group("arg"), v=m.group("v"),
             mk=m.group("mk"), paused=PAUSED)


def _fold_fn(m):
    """Work out how a queued message should look when it is not the one you are
    reading.

    Three long messages waiting is enough to fill a forty row terminal with
    their own text, which pushes the transcript and the busy indicator off the
    top of the screen. The session then looks frozen at exactly the moment you
    want to see that it is not. Claude Code has a shortener of its own, but it
    only starts at ten thousand characters, so a pasted paragraph is nowhere
    near it and is drawn in full.

    So a row that would take more than one terminal line is drawn as its first
    line plus a count of the lines it is holding back. The count is measured in
    the lines you would SEE, so a single long line that wraps three times says
    two, the same as three short lines would.

    The width is deliberately pessimistic, in two ways. The row sits inside a
    container the app caps at eighty columns, with padding either side and a
    two column pointer in front, and a few columns are left spare on top of
    that. And the width is the SMALLEST of everything that claims to know it,
    because they can disagree: under a pty whose size was never set, the stream
    still says eighty while the app is drawing to the sixty its environment
    asked for. Guessing too small only wastes a little room; guessing too big
    makes the row wrap, which is the whole bug back again.

    Nothing here touches the queued command. It copies the throwaway message
    that was built for drawing, the same object the labels are written on, so
    what is sent to the model is whatever you typed.

    The copy also takes a new uuid. The row renderer is memoised on that uuid
    and on nothing else that changes here, so leaving it alone leaves the old
    text on screen when the highlight moves.
    """
    return (
        "function __qsFold(__qm,__qh){"
        'if(__qh||process.env.CLAUDE_QUEUE_COLLAPSE==="off")return __qm;'
        "let __qb=__qm?.message?.content;"
        "if(!Array.isArray(__qb)||__qb.length!==1"
        '||__qb[0]?.type!=="text")return __qm;'
        'let __qs=typeof __qb[0].text==="string"'
        '?__qb[0].text.replace(/\\s+$/,""):"";'
        "if(!__qs)return __qm;"
        "let __qo=process.stdout||{},"
        "__qg=__qo.getWindowSize&&__qo.getWindowSize()||[],"
        "__qv=[__qo.columns,__qg[0],parseInt(process.env.COLUMNS,10)]"
        '.filter((__qc)=>typeof __qc==="number"&&__qc>0&&!isNaN(__qc)),'
        "__qx=__qv.length?Math.min(...__qv):80,"
        "__qw=Math.max(16,Math.min(__qx-2,80)-7),"
        "__ql=__qs.split(`\\n`),"
        "__qn=__ql.reduce((__qt,__qc)=>"
        "__qt+Math.max(1,Math.ceil(__qc.length/__qw)),0);"
        "if(__qn<2)return __qm;"
        "let __qd=__qn-1,"
        '__qe=" (+"+__qd+" line"+(__qd===1?"":"s")+")",'
        "__qr=__qw-__qe.length,"
        "__qf=__ql.find((__qc)=>__qc.trim())||__ql[0];"
        'if(__qf.length>__qr)__qf=__qf.slice(0,Math.max(1,__qr-3))+"...";'
        'return{...__qm,uuid:__qm.uuid+"-qs",'
        "message:{...__qm.message,content:[{...__qb[0],text:__qf+__qe}]}}}"
    ) + m.group(0)


def _fold_rows(m):
    """Fold every queued row except the one the highlight is on.

    The highlighted row is the answer to "what did I actually write". Up and
    down already walk the queue, so leaving that one row whole means every
    message is still readable in full, without a second key to learn and
    without the list ever being taller than the queue plus the message you are
    looking at.

    This is the one place in the drawing code that knows both the row and the
    highlight. Doing it where the text is built instead looks simpler and does
    not work: that step is memoised on the queue alone, so moving the highlight
    would not redraw anything.
    """
    return m.group(0).replace(
        "message:{msg},".format(msg=m.group("msg")),
        "message:__qsFold({msg},{ix}==={sel}),".format(
            msg=m.group("msg"), ix=m.group("ix"), sel=m.group("sel")),
        1)


def _persist(m, js):
    """Write the queue to the project on every change, and know how to bring
    it back.

    The queue lives in memory, so closing the terminal or losing the session
    lost every message waiting in it. This is the one place that can see every
    change to it: the queue's own "something changed" call, which every
    operation already ends on. Saving there means enqueue, dequeue, delete,
    reorder and edit are all covered by one edit, and none of them can be
    forgotten later.

    The file lives in the PROJECT, under .claude, named for the session. That
    is what makes the wrong-project case impossible rather than merely unlikely:
    a session in another directory never looks anywhere near it. It also means
    prompt text is sitting inside a repository, which is why the docs say to
    ignore it.

    A message is removed from the file at the moment it is dequeued, so a crash
    halfway down a queue re-offers only what had not run. The trade is stated
    rather than hidden: a message that was taken out of the queue and then lost
    to a crash before it reached the model is gone, and that is the safer end of
    the trade, because the other end is running something twice.

    Three properties this is careful about:

    - the write is to a temporary name and then a rename, so a crash during a
      write leaves either the old file or the new one, never half of one
    - nothing here may ever throw. A queue file must not be able to stop Claude
      Code from starting, so a corrupt or half written file is ignored in
      silence and the session begins clean
    - saving does not start until a restore has been attempted. Otherwise a
      message enqueued during startup could write the file before the saved
      messages had been read, and delete what it was supposed to protect

    Restoring is one shot and marks what it brings back. The flag goes on the
    stored command, so it survives the round trip through the file and is what
    the label reads, and it is never part of the message text.

    **A queue belongs to one session and is only ever restored into that
    session.** The file is named for the session id and nothing else opens it.

    That rule replaced a heuristic that was wrong, and the way it was wrong is
    worth keeping written down, because the reasoning behind it still sounds
    convincing.

    Resuming from the picker does not continue a session, it FORKS it, and the
    fork gets a new id. Only `--continue` and `--resume <id>` keep the id. So a
    lookup by id alone loses the queue on the picker path, and the fix looked
    obvious: if no file matches my id, adopt the newest one in this project.

    It leaked. "No file matches my id" is also true of every brand new session,
    so a fresh `claude` in the same directory adopted whatever the last session
    left, rewrote it under its own id, and passed it on again. Mounssif drove
    it on 2026-07-30: session one parked a message, a new session showed it as
    restored, that session parked a second, and a third came up holding both.
    One file, both messages, re-keyed each time and following every new session
    forever. It affected waiting and steering messages exactly as much as
    parked ones; parked ones only made it obvious, because they never drain.

    Following the fork properly is not cheap enough to do at startup. The chain
    is there, the fork's first record carries a parentUuid pointing at the last
    message of its parent, but resolving it means searching the project's
    transcripts for that uuid, and in this project one of them is 123 MB.

    So the picker path loses its queue, and that is stated rather than hidden.
    The file stays on disk; nothing is deleted. `CLAUDE_QUEUE_ADOPT=on` puts
    the old behaviour back for anyone who wants it, with the leak that comes
    with it.
    """
    n = _queue_names(js)
    s = _session_names(js)
    return (
        "let __qsReady=!1;"
        "function __qsDir(){{"
        'if(process.env.CLAUDE_QUEUE_PERSIST==="off")return null;'
        'return require("path").join(process.cwd(),".claude")}}'
        "function __qsPath(){{"
        "let __qd=__qsDir();"
        "if(!__qd)return null;"
        "let __qi={state}.sessionId;"
        'if(typeof __qi!=="string"||!__qi)return null;'
        'return require("path").join(__qd,"queue-"+__qi+".json")}}'
        "function __qsRead(__qf){{"
        "try{{"
        'let __qs=JSON.parse(require("fs").readFileSync(__qf,"utf8"));'
        "return __qs&&Array.isArray(__qs.messages)&&__qs.messages.length?"
        "__qs.messages:null}}catch(__qe){{return null}}}}"
        "function __qsNewest(__qx){{"
        "try{{"
        "let __qd=__qsDir();"
        "if(!__qd)return null;"
        'let __qm=require("fs"),__qp=require("path"),__qb=null,__qt=-1;'
        "for(let __qn of __qm.readdirSync(__qd)){{"
        'if(__qn.slice(0,6)!=="queue-"||__qn.slice(-5)!==".json")continue;'
        "let __qy=__qp.join(__qd,__qn);"
        "if(__qy===__qx)continue;"
        "let __qv;"
        "try{{__qv=__qm.statSync(__qy).mtimeMs}}catch(__qe){{continue}}"
        "if(__qv>__qt)__qt=__qv,__qb=__qy}}"
        "return __qb}}catch(__qe){{return null}}}}"
        "function __qsSave(){{"
        "if(!__qsReady)return;"
        "let __qf=__qsPath();"
        "if(!__qf)return;"
        "try{{"
        'let __qm=require("fs"),__qk=__qf+".part",'
        "__qr={arr}.filter({ed}).filter((__qc)=>"
        '__qc.mode==="prompt"&&typeof __qc.value==="string"'
        "&&__qc.value.trim()).map((__qc)=>({{value:__qc.value,"
        'priority:__qc.priority==="next"?"next":'
        '__qc.priority==="paused"?"paused":"later",'
        "restored:__qc.restored===!0}}));"
        "if(!__qr.length){{try{{__qm.unlinkSync(__qf)}}catch(__qe){{}}return}}"
        '__qm.mkdirSync(require("path").dirname(__qf),{{recursive:!0}});'
        "__qm.writeFileSync(__qk,JSON.stringify({{"
        'file:"claude-queue: the messages this session still has waiting",'
        "session:{state}.sessionId,saved:new Date().toISOString(),"
        "messages:__qr}},null,1));"
        "__qm.renameSync(__qk,__qf)}}catch(__qe){{}}}}"
        "globalThis.__qsRestore=function(){{"
        "if(__qsReady)return!1;"
        "__qsReady=!0;"
        "try{{"
        "let __qf=__qsPath();"
        "if(!__qf)return!1;"
        "let __qa=null,__qr=__qsRead(__qf);"
        'if(!__qr&&process.env.CLAUDE_QUEUE_ADOPT==="on"'
        "&&(__qa=__qsNewest(__qf)))__qr=__qsRead(__qa);"
        "if(!__qr)return!1;"
        "let __qn=0;"
        "for(let __qc of __qr){{"
        'if(!__qc||typeof __qc.value!=="string"||!__qc.value.trim())continue;'
        "{arr}.push({{agentId:{agent}(),mode:\"prompt\",value:__qc.value,"
        'priority:__qc.priority==="next"?"next":'
        '__qc.priority==="paused"?"paused":"later",'
        "timestamp:new Date().toISOString(),restored:!0}});"
        "__qn++}}"
        "if(!__qn)return!1;"
        "globalThis.__qsHold=!0,{fn}();"
        'if(__qa)try{{require("fs").unlinkSync(__qa)}}catch(__qe){{}}'
        "return!0}}catch(__qe){{return!1}}}};"
        "function {fn}(){{{snap}=Object.freeze([...{arr}]),"
        "__qsSave(),{em}.emit()}}"
    ).format(fn=m.group("fn"), snap=m.group("snap"), arr=m.group("arr"),
             em=m.group("em"), ed=n["editable"], **s)


def _hold_and_restore(m):
    """Bring the saved queue back, and hold it until you send something.

    This effect is the queue's whole reason for running at the right moment: it
    fires whenever the queue is not empty and nothing is in flight, which is the
    end of every turn. It is also the first thing in the app that runs with the
    session fully identified, so it is where the restore is asked for.

    The hold is what makes restoring safe. Measured on an instrumented build:
    rows pushed into the queue at startup with no hold are taken by this effect
    immediately, so a queue saved yesterday would start running before you had
    read a word of it, in a session that may be skipping permission prompts.
    That is the exact danger of the naive version of this feature.

    So restored rows sit there, drawn, walkable, editable, and nothing happens
    until you submit something yourself. Your message runs as the turn, and the
    restored ones drain after it, one at a time, in their saved order, through
    this same effect once the hold is gone.
    """
    return (
        "{pi}.useEffect(()=>{{globalThis.__qsRestore?.();"
        "if({n}||{r}.isActive)return;"
        "if({t})return;"
        "if({o}.length===0)return;"
        'if({o}.every((__qc)=>__qc.priority==="paused"))return;'
        "if(globalThis.__qsFrozen)return;"
        "if(globalThis.__qsHold)return;"
        "{call}({{executeInput:{e}}})}},["
    ).format(**m.groupdict())


def _not_busy_while_held(m):
    """A session holding restored messages is idle, and must look idle.

    Claude Code treats a non-empty main thread queue as the session being busy,
    which is true everywhere else: a queued message means a turn is running or
    about to. A held queue breaks that assumption, and the screen said so. On
    the instrumented build a resumed session sat at the prompt showing the
    working spinner, with an elapsed counter reading twenty thousand days,
    because no turn had ever started for it to count from.

    Nothing was actually running, so the fix is to stop claiming otherwise
    while the hold is on. The moment you send something the hold is gone and
    this reads exactly as it always did.

    Pointing at the queue is the second hold, and it needed saying here too.
    Nothing drains while a message is highlighted, so a waiting message sat
    there being counted as work about to happen. Moving a parked message onto
    "waits" therefore started the indicator immediately, and it ran on and on
    over a session where, by design, nothing could start until the queue was
    let go of. Reported by Mounssif with the counter past a minute.

    So the queue only makes the session busy when the queue is actually going
    to drain. A turn that is genuinely running still reads as busy through the
    first two terms, which is what keeps this narrow.
    """
    return (
        "mainConversationId:{cid},mainIsBusy:{bs}||!!{bn}||"
        "{len}()>0&&!globalThis.__qsHold&&!globalThis.__qsFrozen}})"
    ).format(**m.groupdict())


PATCH = Patch(
    name="claude-queue",
    summary="type your next instruction without derailing the running one",
    version="2.2.0-dev",
    marker="__qsp",
    usage="""
While Claude is working:

    write the migration notes      waits until it finishes this turn
    s check the staging logs       jumps in at the next tool call
    q write the migration notes    waits, said explicitly
    p rewrite the changelog        parked, never runs until you change it

Also accepted: "q: ..." and "s: ...". The marker is always removed before the
text reaches Claude. Pasted text is literal unless its first nonblank line uses
the explicit colon form, which starts a multi-job batch.

With messages waiting:

    up / down                      move the highlight through the queue
    enter                          pull the highlighted one back to edit
    shift+up / shift+down          move it earlier or later in the queue
    left / right                   change its mode: waits, jumps in, paused

A message taller than one line is drawn as its first line plus a count of the
lines it is holding back. The highlighted one is always drawn in full.

Waiting messages survive a restart. They are saved in this project's .claude
directory, and the next session you start here brings them back reading
[waits, restored], whether you resume that session or pick it from the menu.
Nothing runs until you send something: your message goes first, then they drain
after it in their saved order.

    export CLAUDE_QUEUE_DEFAULT=steer    restores stock behaviour as default
    export CLAUDE_QUEUE_DRAIN=all        waiting messages all run in one turn
    export CLAUDE_QUEUE_COLLAPSE=off     draw long waiting messages in full
    export CLAUDE_QUEUE_PERSIST=off      never write the queue to disk
    export CLAUDE_QUEUE_ADOPT=on         let a fresh session take the newest
                                         saved queue in this project
""",
    edits=[
        Edit(
            "remember bracketed paste as literal input",
            re.compile(
                r'function (?P<fn>\w+)\((?P<arg>\w+)\)\{(?P<guard>\w+)\.current=!1;'
                r'let (?P<text>\w+)=(?P<clean>\w+)\((?P=arg)\)\.replace\('
                r'/\\r\\n\|\\r/g,`\n`\)\.replaceAll\("\\t","    "\);'
            ),
            _remember_paste,
        ),
        Edit(
            "resolve the marker",
            re.compile(
                r"let (?P<cmd>\w+)=\{agentId:\w+\(\),value:(?P<val>\w+),"
                r'preExpansionValue:\w+\.\w+==="suggestion_accepted"\?void 0:(?P<raw>\w+),'
                r"mode:(?P<mode>\w+),"
            ),
            _resolve,
        ),
        Edit(
            "attach the priority",
            re.compile(
                r"xT\(\{\.\.\.(?P<cmd>\w+),value:(?P<val>\w+)\.trim\(\),"
                r"preExpansionValue:(?P=cmd)\.preExpansionValue\?\.trim\(\)\}\)"
            ),
            _priority,
        ),
        Edit(
            "no turn clock for a submission that only pauses",
            re.compile(
                r'if\((?P<wf>\w+)\(\((?P<js>\w+)\)=>(?P=js)\+1\),'
                r'(?P<dr>\w+)\.clearBuffer\(\),(?P<oue>\w+)\.current=!1,'
                r'!(?P<jn>\w+)&&(?P<ih>\w+)==="prompt"'
                r'&&!(?P<oe>\w+)\.isRemoteMode\)'
                r'(?P<oh>\w+)\((?P<yt>\w+)\),(?P<oo>\w+)\(\)'
            ),
            _no_turn_for_paused,
        ),
        Edit(
            "a paused message queues even when nothing is running",
            re.compile(
                r'if\((?P<r>\w+)\.isActive\|\|(?P<n>\w+)\)\{'
                r'if\((?P<o>\w+)!=="prompt"&&(?P=o)!=="bash"\)\{'
                r'(?P<pe>\w+)\("prompt_queued","mode_not_queueable"\);return\}'
            ),
            _queue_when_paused,
        ),
        Edit(
            "split when idle too: first job runs, the rest wait",
            re.compile(
                r'be\("prompt_submit"\),await (?P<fn>\w+)\(\{inputSource:'
                r'(?P<a>[^,]+),queuedCommands:\[(?P<j>\w+)\],'
            ),
            _idle_split,
        ),
        Edit(
            "tab sends with the opposite timing",
            re.compile(
                r'case"return":if\((?P<k>\w+)\.ctrl\)return;return (?P<ae>\w+)\((?P=k)\);'
                r'case"enter":return (?P<w>\w+)\.insert\(`\n`\);case"tab":return\}'
            ),
            _tab_key,
        ),
        Edit(
            "never abort while waiting",
            re.compile(
                r"if\((?P<e>\w+)\.hasInterruptibleToolInProgress\)\{"
                r"(?P<log>\w+\(`\[interrupt\])"
            ),
            _no_abort,
        ),
        Edit(
            "run waiting messages one at a time",
            re.compile(
                r'if\((?P<slash>\w+)\((?P<t>\w+)\)\|\|(?P=t)\.mode==="bash"\)\{'
                r'let (?P<i>\w+)=\[(?P<one>\w+)\(\((?P<s>\w+)\)=>(?P=s)===(?P=t)\)\];'
                r'return (?P<reg>\w+)\((?P=i)\),(?P<exec>\w+)\((?P=i)\)'
                r'\.finally\(\(\)=>(?P<unreg>\w+)\((?P=i)\)\),\{processed:!0\}\}'
                r'let (?P<r>\w+)=(?P=t)\.mode,(?P<n>\w+)=(?P<deqall>\w+)\(\((?P<o>\w+)\)=>'
                r'(?P<qh>\w+)\((?P=o)\)&&!(?P=slash)\((?P=o)\)&&(?P=o)\.mode===(?P=r)\);'
            ),
            _one_at_a_time,
        ),
        Edit(
            "say what each queued message will do",
            re.compile(
                r"function (?P<fn>\w+)\((?P<arg>\w+)\)\{let (?P<v>\w+)=(?P=arg)\.value;"
                r'if\((?P=arg)\.mode==="bash"&&typeof (?P=v)==="string"\)'
                r"(?P=v)=`<bash-input>\$\{(?P=v)\}</bash-input>`;"
                r"return (?P<mk>\w+)\(\{content:(?P=v)\}\)\}"
            ),
            _label,
        ),
        Edit(
            "work out the folded form of a queued message",
            re.compile(
                r"function (?P<fn>\w+)\((?P<arg>\w+)\)\{"
                r"return (?P=arg)\.queueEditIndex\}"
            ),
            _fold_fn,
        ),
        Edit(
            "fold every queued row except the highlighted one",
            re.compile(
                r"(?P<mk>\w+)=\((?P<msg>\w+),(?P<ix>\w+)\)=>(?P<jx>\w+)\.jsx\("
                r"(?P<row>\w+),\{isFirst:(?P=ix)===0,"
                r"useBriefLayout:(?P<brief>\w+),"
                r'selectionHighlight:(?P<any>\w+)\?(?P=ix)===(?P<sel>\w+)'
                r'\?"on":"off":void 0,'
                r"children:(?P=jx)\.jsx\((?P<rend>\w+),\{message:(?P=msg),"
            ),
            _fold_rows,
        ),
        Edit(
            "bring back one queued message, not all of them",
            re.compile(
                r"let (?P<w>\w+)=\w+\((?P<t>\w+),(?P<c>\w+)\);"
                r"if\(!(?P=w)\)return!1;(?P<rest>.{0,400}?)"
                r'"input_queue_pop_to_edit"'
            ),
            _edit_one,
        ),
        Edit(
            "let the up arrow pick a queued message",
            re.compile(
                r"if\((?P<sv>\w+)\(\)\)\{let (?P<b>\w+)=(?P<ht>\w+)\.getState\(\)"
                r"\.queueEditIndex;if\((?P=b)===null&&(?P<rn>\w+)>0\)"
            ),
            _enable_selector,
        ),
        Edit(
            "let the down arrow pick a queued message",
            re.compile(
                r"if\((?P<sv>\w+)\(\)\)\{let (?P<rn>\w+)=(?P<ht>\w+)\.getState\(\)"
                r"\.queueEditIndex;if\((?P=rn)!==null\)\{"
            ),
            _enable_selector,
        ),
        Edit(
            "edit only the message you picked",
            re.compile(
                r"if\((?P<sv>\w+)\(\)&&(?P<bo>\w+)\.queueEditIndex!==null"
                r"&&(?P<pv>\w+)\(\)\)return;"
            ),
            _enable_selector,
        ),
        Edit(
            "remember which slot a message came from",
            re.compile(
                r"let (?P<i>\w+)=(?P<ht>\w+)\.getState\(\)\.queueEditIndex;"
                r"if\((?P=i)===null\)return!1;"
                r"let (?P<r>\w+)=(?P<pop>\w+)\((?P=i),(?P<t>\w+),(?P<c>\w+)\);"
            ),
            _remember_slot,
        ),
        Edit(
            "put an edited message back in its slot",
            re.compile(
                r"function (?P<fn>\w+)\((?P<a>\w+)\)\{(?P<arr>\w+)\.push\("
                r"\{\.\.\.(?P=a),priority:(?P=a)\.priority\?\?\"next\","
                r"timestamp:(?P=a)\.timestamp\?\?new Date\(\)\.toISOString\(\)\}\),"
                r"(?P<tail>[^}]*\})"
            ),
            _enqueue_at_slot,
        ),
        Edit(
            "teach the queue to swap two waiting messages",
            re.compile(
                r"function (?P<y>\w+)\((?P<p>\w+)\)\{let (?P<o>\w+)=(?P<pri>\w+)\[(?P=p)\];"
                r"return (?P<arr>\w+)\.filter\(\((?P<c>\w+)\)=>"
                r'(?P=pri)\[(?P=c)\.priority\?\?"next"\]<=(?P=o)\)\}return\{subscribe:'
            ),
            _move_fn,
        ),
        Edit(
            "shift with an arrow moves the message you picked",
            re.compile(
                r'case"up":if\((?P<k>\w+)\.shift\|\|(?P=k)\.ctrl\|\|(?P=k)\.meta\)return;'
                r'return (?P<up>\w+)\(\);'
                r'case"down":if\((?P=k)\.shift\|\|(?P=k)\.ctrl\|\|(?P=k)\.meta\)return;'
                r'return (?P<dn>\w+)\(\);'
            ),
            _shift_arrows,
        ),
        Edit(
            "connect the move key to the highlighted message",
            re.compile(
                r"let (?P<ht>\w+)=\w+\(\),(?P<mt>\w+)=\w+\(\),(?P<gr>\w+)="
                r"\w+\(\((?P<w1>\w+)\)=>(?P=w1)\.queueEditIndex\),"
                r"(?P<lr>\w+)=(?P<pi>\w+)\.useCallback\(\((?P<w>\w+)\)=>\{"
                r"(?P=mt)\(\((?P<rn>\w+)\)=>(?P=rn)\.queueEditIndex===(?P=w)\?(?P=rn):"
                r"\{\.\.\.(?P=rn),queueEditIndex:(?P=w)\}\)\},\[(?P=mt)\]\)"
            ),
            _install_reorder,
        ),
        Edit(
            "delete removes the message you picked",
            re.compile(
                r'case"backspace":if\((?P<k>\w+)\.superKey\)return (?P<ce>\w+)\(\);'
                r'if\((?P=k)\.meta\|\|(?P=k)\.ctrl\)return (?P<se>\w+)\(\);'
                r'return (?P<w>\w+)\.deleteTokenBefore\(\)\?\?(?P=w)\.backspace\(\);'
                r'case"delete":if\((?P=k)\.superKey\)return (?P<oe>\w+)\(\);'
                r'if\((?P=k)\.meta\)return (?P=oe)\(\);return (?P=w)\.del\(\);'
            ),
            _delete_key,
        ),
        Edit(
            "forget the slot when you clear the editor",
            re.compile(
                r"(?P<it>\w+)=(?P<pi>\w+)\.useRef\((?P<te>\w+)\);(?P=pi)\.useEffect\(\(\)=>\{"
                r"if\((?P=it)\.current===(?P=te)\)return;"
                r"if\((?P=it)\.current=(?P=te),(?P<ht>\w+)\.getState\(\)\.queueEditIndex!==null\)"
                r"(?P<lr>\w+)\(null\)\},\[(?P=te),(?P=lr),(?P=ht)\]\);"
            ),
            _forget_slot,
        ),
        Edit(
            "keep the highlight on the message, not on a position",
            re.compile(
                r"(?P<cr>\w+)=(?P<hook>\w+)\(\);(?P<pi>\w+)\.useEffect\(\(\)=>\{"
                r"if\((?P<gr>\w+)===null\)return;"
                r"let (?P<n>\w+)=(?P<count>\w+)\((?P=cr),(?P<ed>\w+)\);"
                r"if\((?P=n)===0\)(?P<lr>\w+)\(null\);"
                r"else if\((?P=gr)>(?P=n)-1\)(?P=lr)\((?P=n)-1\)"
                r"\},\[(?P=cr),(?P=gr),(?P=lr)\]\);"
            ),
            _follow_message,
        ),
        Edit(
            "say that you can reorder them too",
            re.compile(r'return"Press up to edit queued messages"'),
            # Two rules here, both learned the hard way.
            #
            # Short, because the line is truncated on a normal terminal and a
            # hint you cannot read to the end is worse than a brief one. The
            # old wording listed four keys and got cut before the third.
            #
            # ASCII, because anything else arrives mangled. Arrows and a
            # middle dot came out as "\u00c3\u00a2\u00c2\u2020\u00c2" once
            # inside the repacked binary, while the app's own middle dots
            # rendered fine, so the text this patch introduces has to stay in
            # the range that survives the trip.
            #
            # The second line replaces the first as soon as the queue changes
            # under a highlight, which is exactly the moment "how do I let go
            # of this" becomes the question.
            lambda m: 'return globalThis.__qsSel!=null?'
                      '"left/right mode, enter edit, del remove, '
                      'ctrl+enter run":'
                      '"Press up to edit queued messages, '
                      'left/right to change mode"',
        ),
        Edit(
            "give a message its marker back when you edit it",
            re.compile(
                r"function (?P<fn>\w+)\((?P<i>\w+),(?P<cur>\w+),(?P<off>\w+)\)\{"
                r"let (?P<c>\w+)=(?P<arr>\w+)\.filter\((?P<ed>\w+)\)\[(?P=i)\];"
                r"if\(!(?P=c)\)return;"
                r"let (?P<v>\w+)=(?P<raw>\w+)\((?P=c)\.value\),"
            ),
            _keep_marker,
        ),
        Edit(
            "restore on resume, and hold it until you send something",
            re.compile(
                r"(?P<pi>\w+)\.useEffect\(\(\)=>\{if\((?P<n>\w+)\|\|"
                r"(?P<r>\w+)\.isActive\)return;if\((?P<t>\w+)\)return;"
                r"if\((?P<o>\w+)\.length===0\)return;"
                r"(?P<call>\w+)\(\{executeInput:(?P<e>\w+)\}\)\},\["
            ),
            _hold_and_restore,
        ),
        Edit(
            "a held queue is not a busy session",
            re.compile(
                r"mainConversationId:(?P<cid>\w+),mainIsBusy:(?P<bs>\w+)\|\|"
                r"!!(?P<bn>\w+)\|\|(?P<len>\w+)\(\)>0\}\)"
            ),
            _not_busy_while_held,
        ),
        Edit(
            "left changes the mode of the message you picked",
            re.compile(
                r'case"(?P<key>left)":if\((?P<k>\w+)\.superKey\)'
                r'return (?P<w>\w+)\.(?P<home>startOfLine)\(\);'
                r'if\((?P=k)\.ctrl\|\|(?P=k)\.meta\|\|(?P=k)\.fn\)'
                r'return (?P=w)\.(?P<word>prevWord)\(\);'
            ),
            _mode_arrows,
        ),
        Edit(
            "right changes the mode of the message you picked",
            re.compile(
                r'case"(?P<key>right)":if\((?P<k>\w+)\.superKey\)'
                r'return (?P<w>\w+)\.(?P<home>endOfLine)\(\);'
                r'if\((?P=k)\.ctrl\|\|(?P=k)\.meta\|\|(?P=k)\.fn\)'
                r'return (?P=w)\.(?P<word>nextWord)\(\);'
            ),
            _mode_arrows,
        ),
        Edit(
            "a paused message is not pending work",
            re.compile(
                r'function (?P<x>\w+)\(\)\{return (?P<pr>\w+)\('
                r'(?P<arr>\w+),(?P<qh>\w+)\)\}'
                r'function (?P<o>\w+)\(\)\{return (?P=arr)\.length>0\}'
            ),
            _work_only,
        ),
        # Last on purpose. It rewrites the queue's "something changed" call,
        # which is the shape three earlier edits use to find their way around
        # the queue module, so anything that reads it has to run first.
        Edit(
            "save the queue, and know how to bring it back",
            re.compile(
                r"function (?P<fn>\w+)\(\)\{(?P<snap>\w+)=Object\.freeze\("
                r"\[\.\.\.(?P<arr>\w+)\]\),(?P<em>\w+)\.emit\(\)\}"
            ),
            _persist,
        ),
    ],
)


if __name__ == "__main__":
    sys.exit(main(PATCH, sys.argv))
