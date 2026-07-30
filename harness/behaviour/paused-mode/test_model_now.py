import glob, os, sys, time
sys.path.insert(0, os.path.expanduser("~/Developer/_claude-lab"))
from lab import Lab, busy_for
PATCHED="/opt/homebrew/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe"
STOCK="/private/tmp/claude-501/-Users-hamzadebbarh/01760ee6-421a-4114-a9ad-bc3289f8e897/scratchpad/stock-claude.exe"
WS=os.path.expanduser("~/Developer/_claude-lab/workspace")
UNIQUE="Enter to set as default"
def clean():
    for f in glob.glob(os.path.join(WS,".claude","queue-*.json")): os.remove(f)
def probe(binary,name):
    clean()
    lab=Lab(binary=binary,model="haiku",cols=100,rows=44); lab.start()
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
