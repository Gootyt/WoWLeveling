"""WoW szintezés tervező – indítás Windowson parancssori ablak nélkül.

A .pyw fájlt a Windows a pythonw.exe-vel futtatja (dupla kattintásra), így nem nyílik mellé fekete
parancssori ablak. A program maga a wow_leveling.py, ez csak elindítja. Parancssor híján a program
kiírásai és hibái a mappájában lévő wow_leveling_naplo.txt fájlba kerülnek; ha már az indításnál baj
van (pl. hiányzik egy fájl a mappából), azt egy ablak is jelzi.
"""

import os
import sys
import traceback

FOLDER = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(FOLDER, "wow_leveling_naplo.txt")
sys.path.insert(0, FOLDER)


def fail() -> None:
    details = traceback.format_exc()
    try:
        with open(LOG, "a", encoding="utf-8") as log:
            log.write(details)
    except OSError:
        pass
    message = f"A WoW szintezés tervező nem indult el:\n\n{details.strip().splitlines()[-1]}\n\nA részletek: {LOG}"
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "WoW szintezés tervező", 0x10)
    except (AttributeError, ImportError, OSError):  # nem Windows: ott van parancssor
        print(message, file=sys.stderr)
    raise SystemExit(1)


try:
    import wow_leveling
except Exception:
    fail()

try:
    wow_leveling.main()
except Exception:
    fail()
