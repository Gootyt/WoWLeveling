"""A telefonos alkalmazás fordítása előtt: a program közös moduljait (a terv számolása, a helyi
adatbázis és a szinkronizálás) az android/app mappába másolja, mert a Buildozer csak azt csomagolja
be. Futtatás a repó gyökeréből: python android/prepare.py (a GitHub Actions is így futtatja)."""

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "android" / "app"
SHARED = (
    "leveling.py",
    "storage.py",
    "cloud_sync.py",
    "httpcompat.py",
    "wow_data.py",
    "raiderio.py",
    "murlok.py",
)


def main() -> None:
    for name in SHARED:
        shutil.copyfile(ROOT / name, APP / name)
        print(f"{name} -> {APP / name}")


if __name__ == "__main__":
    main()
