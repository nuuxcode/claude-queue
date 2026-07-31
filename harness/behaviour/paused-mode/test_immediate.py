"""Do /model, /status and /usage open instantly mid-turn, stock vs patched?"""
import glob, os, pathlib, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import WORKSPACE, patched_binary, stock_binary  # noqa: E402
from lab import Lab, busy_for
PATCHED = patched_binary()
STOCK = stock_binary()
WS = WORKSPACE
MARKS={"/model":("Default (recommended)","Haiku","Sonnet"),
       "/status":("Account","Session","Working directory","Model"),
       "/usage":("Usage","limit","resets","Current session")}
def clean():
    for f in glob.glob(os.path.join(WS,".claude","queue-*.json")): os.remove(f)
def probe(binary,cmd):
    clean()
    lab=Lab(workspace=WS, binary=binary,model="haiku",cols=100,rows=44); lab.start()
    try:
        lab.send(busy_for(35),label="busy"); time.sleep(4)
        running = "esc to interrupt" in lab.screen()
        lab.send(cmd,label=cmd); lab._pump(5)
        s=lab.screen()
        queued=any(cmd in ln and ("[waits" in ln or "❯ "+cmd==ln.strip()) for ln in s.splitlines())
        opened=any(k in s for k in MARKS[cmd])
        return running,queued,opened
    finally:
        lab.stop(); clean()
print(f"{'command':<9} {'binary':<9} {'turn running':<13} {'queued':<8} {'opened instantly'}")
for cmd in ("/model","/status","/usage"):
    for name,b in (("STOCK",STOCK),("PATCHED",PATCHED)):
        r,q,o = probe(b,cmd)
        print(f"{cmd:<9} {name:<9} {str(r):<13} {str(q):<8} {o}")
