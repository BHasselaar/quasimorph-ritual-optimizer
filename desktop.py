from __future__ import annotations
import os, sys, traceback
from pathlib import Path

def main():
    try:
        from quasimorph_optimizer.app import main as app_main
        app_main()
        return 0
    except Exception:
        text=traceback.format_exc()
        log=Path(__file__).resolve().parent/"startup_error.log"
        try: log.write_text(text,encoding="utf-8")
        except Exception: pass
        print(text)
        print(f"Error log: {log}")
        if os.name=="nt" and sys.stdin and sys.stdin.isatty():
            try: input("Press Enter to close...")
            except EOFError: pass
        return 1

if __name__=="__main__":
    raise SystemExit(main())
