import glob, os, pathlib, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import WORKSPACE, patched_binary  # noqa: E402
from lab import Lab
LIVE = patched_binary()
WS = WORKSPACE
HIS = ("p Okay, so we did pass one for request one and request two, then we did pass two, "
"then we did pass three. Now, this is a lot of MD files and a lot of data. So, to present "
"this in a demo tomorrow, it will be a little bit hard 'cause I can't just open it and read those MD files.\n"
"But I want to make an HTML page which has the summary of all these findings and this audit in a way they are "
"organized by the type, by the subtype.\n"
"So it should be organized so when I am demonstrating it, they can click maybe in the sidebar on the left.\n"
"And yeah, basically, you find an input box there, and you can put maybe your name and your feedback.")
def clean():
    for f in glob.glob(os.path.join(WS,".claude","queue-*.json")): os.remove(f)
def bracket_paste(lab, text):
    lab.write(b"\x1b[200~"+text.encode()+b"\x1b[201~"); lab._pump(1.2)
fails=[]
def check(n,ok,d=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {n}{'  '+d if d else ''}")
    if not ok: fails.append(n)
def qrows(l): return [x.strip() for x in l.screen().splitlines()
                      if "[waits" in x or "[jumps in" in x or "[paused" in x]

clean()
lab=Lab(workspace=WS, binary=LIVE,model="haiku",cols=100,rows=44); lab.start()
try:
    # 1. paste the WHOLE thing, marker included, while idle
    bracket_paste(lab, HIS); lab.write(b"\r"); lab._pump(6)
    rows=qrows(lab)
    check("1. long pasted 'p ...' is PARKED, not run",
          any("[paused]" in r for r in rows), str(rows)[:110])
    check("2. the 'p ' marker was stripped",
          not any("] p Okay" in r for r in rows), str(rows)[:110])
    check("3. nothing is running", "esc to interrupt" not in lab.screen())
finally:
    lab.stop(); clean()

# 4. typed marker + pasted body
lab=Lab(workspace=WS, binary=LIVE,model="haiku",cols=100,rows=44); lab.start()
try:
    lab.type("p ")
    bracket_paste(lab, HIS[2:])
    lab.write(b"\r"); lab._pump(6)
    rows=qrows(lab)
    check("4. typed 'p ' + pasted body is PARKED",
          any("[paused]" in r for r in rows), str(rows)[:110])
finally:
    lab.stop(); clean()

# 5. pasted code must stay literal
lab=Lab(workspace=WS, binary=LIVE,model="haiku",cols=100,rows=44); lab.start()
try:
    bracket_paste(lab, "q = deque()\nprint(q)")
    lab.write(b"\r"); lab._pump(6)
    rows=qrows(lab)
    check("5. pasted code 'q = deque()' is NOT a marker",
          not any("= deque" in r for r in rows), str(rows)[:110])
finally:
    lab.stop(); clean()
print("\n"+("FAILED: "+", ".join(fails) if fails else "LONG PASTE FIXED"))
sys.exit(1 if fails else 0)
