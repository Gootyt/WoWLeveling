# WoWLeveling – szintezés tervező

Grafikus felületű Python program World of Warcraft karakterek szintezésének
megtervezéséhez és követéséhez.

- Megadható a szintezés kezdete, az a dátum, amikorra az **első**, illetve az
  **utolsó** karakternek el kell érnie a maximum szintet, és maga a **maximum szint**.
- Új karakterek vehetők fel (név, kaszt nem kötelező). **Minden karakter 1-es
  szintről indul.**
- A karakterek listája **külön ablakban** nyílik meg. Karakterenként látszik a
  céldátum, a **mai cél** (amilyen szintet a mai nap végéig el kell érni), a
  hátralévő napok, a szükséges tempó és az állapot (színkódolva).
- A listában állítható a karakterek jelenlegi szintje és sorrendje, a karakterek
  szerkeszthetők és törölhetők.
- Minden változást automatikusan elment.

## Követelmények

- Python 3.8 vagy újabb, **tkinterrel** (más csomag nem kell).
  - Windows és macOS: a python.org telepítője tartalmazza a tkintert.
  - Linux: Debian/Ubuntu alatt `sudo apt install python3-tk`, Fedorán
    `sudo dnf install python3-tkinter`.

## Indítás

```
python wow_leveling.py
```

Windowson `py wow_leveling.py` is jó, vagy dupla kattintás a fájlra.

Ha több tervet akarsz külön vezetni (pl. másik szerveren), add meg az adatfájlt:

```
python wow_leveling.py masik_terv.json
```

## Használat

1. **Beállítások** (főablak): a dátumokat `ÉÉÉÉ-HH-NN` alakban kell megadni
   (pl. `2026-10-15`; a `2026.10.15.` alakot is elfogadja), vagy a ▼ gombbal
   naptárból választhatsz. Hibás érték esetén piros üzenet jelzi, mi a gond.
   A helyes beállításokat a program azonnal menti.
2. **Új karakter**: írd be a nevét (és ha akarod, a kasztját), majd
   „Hozzáadás” vagy Enter. Az új karakter a lista végére kerül.
3. **Karakterlista megnyitása…**: a lista külön ablakban nyílik meg, és minden
   változásra azonnal frissül.
4. **Haladás rögzítése**: jelöld ki a karaktert, írd be a jelenlegi szintjét
   (Enter vagy „Beállítás”), vagy nyomd meg a „+1 szint” gombot. Billentyűvel:
   `+` / `-` egy szinttel feljebb/lejjebb, `Delete` törlés, dupla kattintás
   szerkesztés.
5. **Sorrend**: a „▲ Feljebb” / „▼ Lejjebb” gombokkal. A sorrend határozza meg,
   melyik karakternek kell elsőként, melyiknek utoljára elérnie a maximum szintet.

## Hogyan számol a program?

**Céldátumok.** A lista első karakteréé az első céldátum, az utolsóé az utolsó, a
köztük lévőké egyenletesen oszlik el (egész napra kerekítve). Például ha az első
céldátum 2026-10-19, az utolsó 2026-11-24, és 5 karakter van, a céldátumok:
10-19, 10-28, 11-06, 11-15, 11-24.

**Ütemezés.** Két mód választható:

- *Párhuzamosan* – minden karakter a szintezés kezdőnapján kezd.
- *Egymás után* – az első karakter a kezdőnapon kezd, a többiek mindig az előző
  karakter céldátumát követő napon. Ilyenkor a listában a „Kezdés” oszlop is látszik.

**Mai cél.** A program úgy számol, hogy a karakter a kezdőnapjától a céldátumáig
(mindkét napot beleértve) egyenletes tempóban halad 1-es szintről a maximum
szintig. Ha például 10 nap alatt kell 1-ről 90-re jutni, akkor az első nap végére
9-es, a második végére 18-as szint a cél, és így tovább.

**Hátralévő napok, tempó.** A céldátumig hátralévő szintezési napok száma (a mai
nappal együtt), és hogy átlagosan hány szintet kell naponta szerezni a hátralévő
szintekből.

**Állapotok:**

| Állapot | Jelentés |
|---|---|
| Kész | elérte a maximum szintet |
| Előrébb jár | a mai célnál is magasabb szinten van |
| Mai cél teljesítve | pontosan a mai célnál tart |
| Ütemben | a tegnapi célt elérte, a maiból még hiányzik valamennyi |
| Lemaradásban | a tegnapi célt sem érte el |
| Lejárt a céldátum | a céldátum elmúlt, de még nincs maximum szinten |
| Még nem kezdődött | a szintezése még nem kezdődött el |

A lista alján a „mai teendő összesen” azt mutatja, hány szintet kell ma még
összesen szerezni ahhoz, hogy minden karakter elérje a mai célját.

Megjegyzés: a játékban a magasabb szintekhez több tapasztalati pont kell, a
program viszont minden szintet egyformán számol. Ezért érdemes az elején kicsit
előrébb járni.

## Adatok

A beállítások és a karakterek a program mappájában lévő `szintezes_adatok.json`
fájlba kerülnek (egyszerű, olvasható JSON). Ha ezt a fájlt elmented, az adataid is
megvannak. Ha a fájl megsérül, a program átnevezi
(`szintezes_adatok.hibas-<időpont>.json`, így nem vész el), és alapbeállításokkal
indul.

## Fájlok

- `wow_leveling.py` – a grafikus felület, ezt kell elindítani
- `leveling.py` – az ütemezés számítása, mentés és betöltés
- `tests/` – automatikus tesztek

## Tesztek

```
python -m unittest discover -s tests -v
```

A felület tesztjeihez grafikus kijelző kell (Linuxon kijelző nélkül pl.
`xvfb-run python -m unittest discover -s tests`); ha nincs, ezek kimaradnak.
