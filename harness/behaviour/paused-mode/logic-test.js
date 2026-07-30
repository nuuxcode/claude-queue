// Claude Code's own three selectors, copied verbatim from the 2.1.220 source.
const Wuo = {now:0, next:1, later:2};
const fold   = (e,p) => e.filter(c => Wuo[c.priority ?? "next"] <= Wuo[p]);
const peek   = (e,f) => { let o=-1,c=1/0; for(let i=0;i<e.length;i++){const n=e[i];
                          if(f&&!f(n))continue; const v=Wuo[n.priority??"next"];
                          if(v<c){o=i;c=v}} return o===-1?undefined:e[o]; };
const deq    = peek;

const q = [
  {id:"A", priority:"paused"},
  {id:"B", priority:"paused"},
];
const mixed = [{id:"P", priority:"paused"}, {id:"W", priority:"later"}];

let fail = 0;
const check = (name, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if(!ok) fail++;
  console.log(`${ok?"PASS":"FAIL"}  ${name}  got=${JSON.stringify(got)} want=${JSON.stringify(want)}`);
};

check("mid-turn fold ignores paused",      fold(q,"next").map(x=>x.id), []);
check("fold at 'later' ignores paused",    fold(q,"later").map(x=>x.id), []);
check("peek never returns paused",         peek(q)?.id, undefined);
check("dequeue never returns paused",      deq(q)?.id, undefined);
check("mixed: paused skipped, waits runs", peek(mixed)?.id, "W");
check("mixed fold at later takes only W",  fold(mixed,"later").map(x=>x.id), ["W"]);

// the mode cycle
const cyc = ["later","next","paused"];
const step = (p,d) => cyc[(cyc.indexOf(p)+d+cyc.length)%cyc.length];
check("right cycles q->s->p->q", ["later"].concat([1,1,1].map((_,i,a)=>0)).length?
  [step("later",1), step("next",1), step("paused",1)] : [], ["next","paused","later"]);
check("left  cycles q->p->s->q", [step("later",-1), step("paused",-1), step("next",-1)],
  ["paused","next","later"]);

console.log(fail ? `\n${fail} FAILED` : "\nALL LOGIC CHECKS PASSED");
process.exit(fail?1:0);
