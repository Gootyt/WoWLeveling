# WoWLeveling – szintezés tervező

Grafikus felületű Python program World of Warcraft karakterek szintezésének
megtervezéséhez és követéséhez.

- Megadható a szintezés kezdete, az a dátum, amikorra az **első**, illetve az
  **utolsó** karakternek el kell érnie a célszintet, valamint a **kezdőszint** és a
  **célszint**.
- A szintek **két tizedesjegy pontosságúak** (pl. `83,45`: a 83-as szint 45%-ánál
  tart a karakter). Tizedesvesszővel és -ponttal is beírhatók.
- Új karakterek vehetők fel. Csak a név kötelező; megadható a realm, a faj, a
  kaszt, a spec, az itemlevel, a Raider.io pontszám és a jelenlegi szint is (szint
  nélkül a karakter a kezdőszintről indul). A spec választólistája mindig a kiválasztott kaszt specjeit kínálja, a
  realm mező pedig a már használt realmeket. A karakterek szintje lehet a
  kezdőszint alatt vagy a célszint felett is.
- A karakterek listája **külön ablakban** nyílik meg. Karakterenként látszik a
  céldátum, a **mai cél** (amilyen szintet a mai nap végéig el kell érni), a
  **szinteltérés** (hány szinttel jár a terv előtt vagy mögött), a hátralévő napok,
  a szükséges napi tempó és az állapot (színkódolva).
- A lista alján látszik, hányadik napja tart a szintezés, és hogy a karakterek
  együtt **melyik nap szintjén állnak** (pl. „a 8. nap szintjén állnak – 3 nappal a
  mai cél mögött”).
- **Előretekintés:** ha minden karakter teljesítette a mai célt, a lista
  automatikusan a holnapi célokat mutatja; ha azt is, a holnaputániakat, és így
  tovább. A lista tetején lévő jelölőnégyzettel ki- és bekapcsolható.
- A lista oszlopai **automatikusan** olyan szélesek, amennyit a tartalmuk kíván;
  ha a tartalom szélesebb lesz, az ablak is nő (legfeljebb a képernyő szélességéig).
- A lista bármelyik oszlop szerint **rendezhető** a fejlécre kattintva (pl. a
  szinteltérés szerint, hogy elöl legyenek a leginkább lemaradt karakterek).
- A **Murlok.io** oszlopban a karakter specjének pontszáma látszik a
  [Murlok.io](https://murlok.io) Mythic+ rangsorából (a program magától lekéri).
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
   naptárból választhatsz. A kezdő- és a célszint két tizedesjegyig adható meg; a
   mezők nyilai egy egész szinttel léptetnek. Hibás érték esetén piros üzenet
   jelzi, mi a gond. A helyes beállításokat a program azonnal menti.
2. **Új karakter** (a főablak jobb oldalán): írd be a nevét (és ha akarod, a
   realmjét, faját, kasztját, specjét, itemlevelét, Raider.io pontszámát és jelenlegi szintjét),
   majd „Hozzáadás” vagy Enter. A realm, a faj, a kaszt és a spec listából
   választható, de bármit beírhatsz. Ha kasztot váltasz, és a már kiválasztott spec
   nem tartozik az új kaszthoz, a spec mező kiürül. Az itemlevel és a Raider.io
   pontszám egy tizedesjegyig adható meg (pl. `327`, `326,5` vagy `2543,7`); a
   weboldalról ezres elválasztóval másolt alak (`2,543.7`) is jó. Az új karakter a
   lista végére kerül.
3. **Karakterlista megnyitása…**: a lista külön ablakban nyílik meg, és minden
   változásra azonnal frissül.
4. **Haladás rögzítése**: jelöld ki a karaktert, írd be a jelenlegi szintjét
   (pl. `84,30`, majd Enter vagy „Beállítás”), vagy nyomd meg a „+1 szint”
   gombot. Billentyűvel: `+` / `-` egy szinttel feljebb/lejjebb, `Delete` törlés.
   Dupla kattintásra (vagy a „Szerkesztés…” gombbal) a karakter minden adata
   módosítható.
5. **Rendezés**: kattints egy oszlop fejlécére; újabb kattintásra megfordul az
   irány (a fejlécben ▲ = növekvő, ▼ = csökkenő). A rendezés csak a nézetet
   változtatja meg, a karakterek sorrendjét nem. A # oszlopra kattintva visszakapod
   az eredeti sorrendet. Az üres értékek (pl. a kész karakterek mai célja) mindig a
   lista végére kerülnek, a „Kaszt” szerinti rendezés kaszton belül spec szerint
   rendez, az „Állapot” szerinti pedig a legsürgősebbel kezd.
6. **Sorrend**: a „▲ Feljebb” / „▼ Lejjebb” gombokkal (csak a # szerinti
   nézetben). A sorrend határozza meg, melyik karakternek kell elsőként, melyiknek
   utoljára elérnie a célszintet.

## Hogyan számol a program?

**Céldátumok.** A lista első karakteréé az első céldátum, az utolsóé az utolsó, a
köztük lévőké egyenletesen oszlik el (egész napra kerekítve). Például ha az első
céldátum 2026-10-19, az utolsó 2026-11-24, és 5 karakter van, a céldátumok:
10-19, 10-28, 11-06, 11-15, 11-24.

**Ütemezés.** Két mód választható:

- *Párhuzamosan* – minden karakter a szintezés kezdőnapján kezd.
- *Egymás után* – az első karakter a kezdőnapon kezd, a többiek mindig az előző
  karakter céldátumát követő napon. Ilyenkor a listában a „Kezdés” oszlop is látszik.

**Mai cél.** A terv szerint a karakter a kezdőnapján a kezdőszinten áll, és a
céldátumáig (mindkét napot beleértve) egyenletes tempóban jut el a célszintig. Ha
például a kezdőszint 1,00, a célszint 90,00, és erre 10 nap van, akkor az első nap
végére 9,90, a második végére 18,80 a cél, és így tovább. A mai célt a program két
tizedesjegyre lefelé, a szükséges tempót felfelé kerekíti.

**Szinteltérés.** A karakter jelenlegi szintje mínusz az a szint, ahol a terv
szerint a mai nap végén tartania kellene. Pozitív érték: ennyivel jár a terv
előtt, negatív: ennyivel van mögötte. Ha a szintezés már tart, ez éppen a
„Szint” és a „Mai cél” különbsége. A kezdés előtt a kezdőszinthez, a céldátum
után a célszinthez viszonyít a program.

**Előretekintés.** Bekapcsolva (ez az alapbeállítás) a lista az első olyan nap
céljait mutatja, amelynek a tervezett szintjét még nem érte el minden karakter.
Ilyenkor a cél oszlop fejléce „Holnapi cél” (vagy pl. „Cél (10-18)”), a
szinteltérés és az állapot is ehhez a naphoz viszonyít („Ütemben – a holnapi célig
még 0,57 szint”), a táblázat fölött pedig egy zöld sor jelzi, hogy melyik nap
céljai látszanak és miért. A „Hátra (nap)”, a „Napi tempó” és a lista alján lévő
napszint továbbra is a valódi mai naphoz igazodik. Kikapcsolva a lista mindig a
mai célokat mutatja. A beállítást a program megjegyzi.

**Hátra (nap), napi tempó.** A céldátumig hátralévő szintezési napok száma (a mai
nappal együtt), és hogy átlagosan hány szintet kell naponta szerezni a célszintig.
Ha egy karakter a kezdőszint alatt van, a hiányzó szintek is beleszámítanak.

**Melyik nap szintjén állunk?** A lista alján a program összeadja, hány szintet
léptek a karakterek a kezdőszinthez képest (a célszint feletti rész nem számít, a
kezdőszint alatti karakterek hiánya levonódik). Utána megkeresi a terv utolsó
olyan napját, amelynek végére összesen ennyi szint volt esedékes. A szintezés 1.
napja a kezdőnap, az utolsó az utolsó karakter céldátuma. Ha ez a nap a mai, a
karakterek együtt éppen a mai célnál tartanak; ha korábbi, ennyi nappal le vannak
maradva.

**Murlok.io oszlop.** A program a Murlok.io három Mythic+ rangsoroldalát kéri le
([tank](https://murlok.io/meta/tank/m+), [healer](https://murlok.io/meta/healer/m+),
[DPS](https://murlok.io/meta/dps/m+)), és minden karakternél a kasztjához és
specjéhez tartozó pontszámot írja ki (pl. Unholy Death Knight: 3891). A Murlok.io
ezt a Blizzard Battle.net API adataiból, a spec legjobb játékosai alapján számolja,
és 8 óránként frissíti; ez a játékbeli Mythic+ rating, ami közel áll a Raider.io
pontszámhoz, de nem pontosan ugyanaz.

- A lekérés a lista megnyitásakor magától elindul, ha a tárolt adat 8 óránál
  régebbi, vagy bármikor a „Frissítés a Murlok.io-ról” gombbal. A háttérben fut, a
  program közben használható; az eredmény (és az esetleges hiba) a lista tetején
  látszik.
- Internetkapcsolat kell hozzá. A program csak ezt a három nyilvános oldalt kéri le,
  rólad vagy a karaktereidről nem küld semmit. A lekért pontszámok az adatfájlba is
  bekerülnek, így netkapcsolat nélkül a legutóbbi adatok látszanak.
- Csak akkor van érték, ha a karakternél a kaszt és a spec is meg van adva (a
  listában szereplő angol nevekkel, pl. „Death Knight” és „Unholy”).

**Állapotok:**

| Állapot | Jelentés |
|---|---|
| Kész | elérte (vagy meghaladta) a célszintet |
| Előrébb jár | a mai célnál is magasabb szinten van |
| Mai cél teljesítve | pontosan a mai célnál tart |
| Ütemben | a tegnapi célt elérte, a maiból még hiányzik valamennyi |
| Lemaradásban | a tegnapi célt sem érte el |
| Kezdőszint alatt | a szintezése még nem kezdődött el, és a kezdőszint alatt van |
| Lejárt a céldátum | a céldátum elmúlt, de még nincs célszinten |
| Még nem kezdődött | a szintezése még nem kezdődött el |

A lista alján a „mai teendő összesen” azt mutatja, hány szintet kell ma még
összesen szerezni ahhoz, hogy minden karakter elérje a mai célját.

Megjegyzés: a játékban a magasabb szintekhez több tapasztalati pont kell, a
program viszont minden szintet egyformán számol. Ezért érdemes az elején kicsit
előrébb járni.

## Adatok

A beállítások és a karakterek a program mappájában lévő `szintezes_adatok.json`
fájlba kerülnek (egyszerű, olvasható JSON). Ha ezt a fájlt elmented, az adataid is
megvannak. A program korábbi (maximum szintes) változatának adatfájlját is
beolvassa: ilyenkor a kezdőszint 1,00, a célszint a korábbi maximum szint lesz. Ha
a fájl megsérül, a program átnevezi (`szintezes_adatok.hibas-<időpont>.json`, így
nem vész el), és alapbeállításokkal indul.

## Fájlok

- `wow_leveling.py` – a grafikus felület, ezt kell elindítani
- `leveling.py` – az ütemezés számítása, mentés és betöltés
- `murlok.py` – a spec-pontszámok lekérése a Murlok.io-ról
- `wow_data.py` – a kasztok, specek és fajok listája
- `tests/` – automatikus tesztek

## Tesztek

```
python -m unittest discover -s tests -v
```

A felület tesztjeihez grafikus kijelző kell (Linuxon kijelző nélkül pl.
`xvfb-run python -m unittest discover -s tests`); ha nincs, ezek kimaradnak.
