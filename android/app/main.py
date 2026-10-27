"""WoW szintezés – a telefonos alkalmazás (Kivy). Ideiglenes első változat a fordítás kipróbálásához."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if (ROOT / "leveling.py").exists():  # a repóból futtatva a közös modulok a gyökérben vannak
    sys.path.insert(0, str(ROOT))

from kivy.app import App  # noqa: E402
from kivy.uix.label import Label  # noqa: E402

import cloud_sync  # noqa: E402
import leveling  # noqa: E402


class WowApp(App):
    def build(self):
        return Label(text=f"WoW szintezés\n{len(leveling.REGIONS)} régió, {cloud_sync.POLL_SECONDS} mp")


if __name__ == "__main__":
    WowApp().run()
