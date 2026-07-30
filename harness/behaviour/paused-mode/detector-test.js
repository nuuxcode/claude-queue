
globalThis.__qsPastes = undefined;
const D = (__qt)=>{let __qs=String(__qt||""),__qa=globalThis.__qsPastes,__qpaste=Array.isArray(__qa)&&__qa.some((__qb)=>typeof __qb==="string"&&__qb&&__qs.includes(__qb)),__qm=__qpaste?/^(q|s|p):\s*/i:/^(q|s|p)(?::|\s)\s*/i,__ql=__qs.split(`\n`),__qn=__ql.find((__qb)=>__qb.trim()),__qbat=!__qpaste||!!(__qn&&/^(q|s|p):\s*/i.test(__qn));if(!__qbat)return!1;let __qf=(__qb)=>{let __qc=__qm.exec(__qb);return __qc&&__qb.slice(__qc[0].length).trim()?__qc:null};if(!__ql.some(__qf))return!1;let __qx=[];__ql.forEach((__qb)=>{let __qc=__qf(__qb);if(__qc)__qx.push(__qc[1][0].toLowerCase());else if(!__qx.length&&__qb.trim())__qx.push("*")});return __qx.length>0&&__qx.every((__qb)=>__qb==="p")};
const T = (t, p) => { globalThis.__qsPastes = p; return D(t); };
const cases = [
  ["p alo", undefined, true],
  ["p: alo", undefined, true],
  ["q alo", undefined, false],
  ["hello", undefined, false],
  ["print something", undefined, false],
  ["p", undefined, false],
  ["", undefined, false],
  ["p: a\ncontinuation line", undefined, true],
  ["p: a\ncont\np: b\nmore", undefined, true],
  ["p: a\nq: b", undefined, false],
  ["lead\np: a", undefined, false],
  ["p alo", ["p alo"], false],
  ["p: alo", ["p: alo"], true],
  ["p alo\np: b", ["p alo\np: b"], false],
];
let bad = 0;
for (const [txt, p, want] of cases) {
  const got = T(txt, p);
  const ok = got === want; if (!ok) bad++;
  console.log(`${ok?"ok  ":"FAIL"} ${JSON.stringify(txt).padEnd(26)} pasted=${p?"y":"n"} -> ${got} (want ${want})`);
}
console.log(bad ? `\n${bad} FAILED` : "\nDETECTOR CORRECT ON ALL 14 CASES");
process.exit(bad?1:0);
