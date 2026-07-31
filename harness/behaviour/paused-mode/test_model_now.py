import glob, os, pathlib, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import WORKSPACE, patched_binary, stock_binary  # noqa: E402
from lab import Lab, busy_for
PATCHED = patched_binary()
STOCK = stock_binary()
WS = WORKSPACE
UNIQUE="Enter to set as default"
def clean():
    for f in glob.glob(os.path.join(WS,".claude","queue-*.json")): os.remove(f)
def probe(binary,name):
    clean()
    lab=Lab(workspace=WS, binary=binary,model="haiku",cols=100,rows=44); lab.start()
    try:
        lab.send(busy_for(40),label="busy"); time.sleep(5)
        lab.send("/model"); lab._pump(5)
        s=lab.screen()
        print(f"\n===== {name} =====")
        print("  turn still running :", "esc to interrupt" in s)
        print("  picker OPEN now    :", UNIQUE in s)
        print("  queued as a row    :", any("/model" in ln and "[waits" in ln for ln in s.splitlines()))
        for ln in [x.rstrip() for x in s.splitlines() if x.strip()][-11:]:
            print("   |", ln)
    finally:
        lab.stop(); clean()
probe(STOCK,"STOCK"); probe(PATCHED,"PATCHED")
