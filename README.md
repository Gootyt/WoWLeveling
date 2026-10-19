# WoWLeveling – szintezés tervező

Grafikus felületű Python program World of Warcraft karakterek szintezésének
megtervezéséhez és követéséhez.

- Megadható a szintezés kezdete, az a dátum, amikorra az **első**, illetve az
  **utolsó** karakternek el kell érnie a célszintet, valamint a **kezdőszint** és a
  **célszint**. A **célitemlevel** is megadható (nem kötelező).
- A két céldátum egy gombnyomással **kiszámolható a karakterek mostani
  szintjéből** (az eddigi tempó alapján).
- A szintek **két tizedesjegy pontosságúak** (pl. `83,45`: a 83-as szint 45%-ánál
  tart a karakter). Tizedesvesszővel és -ponttal is beírhatók.
- Új karakterek vehetők fel. Csak a név kötelező; megadható a realm, a faj, a
  kaszt, a spec, az itemlevel, a Raider.io pontszám és a jelenlegi szint is (szint
  nélkül a karakter a kezdőszintről indul). A spec választólistája mindig a kiválasztott kaszt specjeit kínálja, a
  realm mező pedig a már használt realmeket. A karakterek szintje lehet a
  kezdőszint alatt vagy a célszint felett is.
- **Combó ajánlása:** a program javasol egy class/spec/faj combót a választott
  frakcióban (Alliance vagy Horde), amilyen leginkább hiányzik a listáról. A szerep
  (a DPS-en belül melee és ranged) és a páncéltípus annyi százalékra törekszik,
  amennyi az összes combóban az aránya (pl. a combók kb. 12%-a tank); a kasztból, a
  specből és a fajból a legkevésbé használtat ajánlja.
- A főablak **Gear** gombja a karakterlista egy változatát nyitja meg külön
  ablakban, saját rendezéssel. Ebben a szintezéssel kapcsolatos oszlopok (szint,
  kezdés, céldátum, mai cél, szinteltérés, hátra, napi tempó, állapot) helyett az
  „Itemlevel” után a **tervezett itemlevel** és az **itemlevel-eltérés** látszik,
  alapból az eltérés szerint rendezve (lásd lent), és a sorok nincsenek színezve. A
  kijelölt karakternek itt az itemlevele módosítható, és aki elérte a
  célitemlevelt, lekerül a listáról.
- A főablak **Mythic+** gombja a Gear ablak változatát nyitja meg külön ablakban,
  saját rendezéssel. Ebben a tervezett itemlevel és az itemlevel-eltérés helyett a
  Raider.io oszlop után a **tervezett Raider.io** és a **Raider.io-különbözet**
  látszik (lásd lent), alapból a különbözet szerint rendezve; alul pedig a kijelölt
  karakter Raider.io pontszáma állítható.
- A karakterek listája **külön ablakban** nyílik meg. Karakterenként látszik a
  céldátum, a **mai cél** (amilyen szintet a mai nap végéig el kell érni), a
  **szinteltérés** (hány szinttel jár a terv előtt vagy mögött), a hátralévő napok,
  a szükséges napi tempó és az állapot (színkódolva). A spec mellett a **role** is
  látszik (Tank, Healer, Melee DPS vagy Ranged DPS), a specből számolva; spec
  nélkül csak akkor, ha a kaszt minden specje ugyanaz (pl. Mage: Ranged DPS).
- A lista alján látszik, hányadik napja tart a szintezés, és hogy a karakterek
  együtt **melyik nap szintjén állnak** (pl. „a 8. nap szintjén állnak – 3 nappal a
  mai cél mögött”).
- **Előretekintés:** ha minden karakter teljesítette a mai célt, a lista
  automatikusan a holnapi célokat mutatja; ha azt is, a holnaputániakat, és így
  tovább. A lista tetején lévő jelölőnégyzettel ki- és bekapcsolható.
- A lista oszlopai **automatikusan** olyan szélesek, amennyit a tartalmuk kíván;
  ha a tartalom szélesebb lesz, az ablak is nő (legfeljebb a képernyő szélességéig).
- A karakterlista mindig az **állapot szerint rendezve** nyílik meg: elöl a
  legsürgősebbek (lejárt céldátum, lemaradás), a végén a célszintet már elért
  karakterek. A fejlécre kattintva bármelyik oszlop szerint átrendezhető.
- A **Murlok.io** oszlopban a karakter specjének pontszáma látszik a
  [Murlok.io](https://murlok.io) Mythic+ rangsorából (a program magától lekéri).
- A program a [Raider.io](https://raider.io)-ról lekéri a karakterek itemlevelét
  és Mythic+ pontszámát a nevük, a realmjük és a beállított régió alapján, az üres
  faj-, kaszt- és specmezőket pedig kitölti. Ez magától történik a listaablakok
  megnyitásakor és új karakter hozzáadásakor, vagy bármikor a **„Frissítés a
  Raider.io-ról”** gombbal (lásd lent).
- **Statisztikák:** a főablak „M+ ilvl statisztika” gombja a Raider.io adataiból
  megmutatja, milyen itemlevelű játékosok viszik időben a Mythic+ kulcsokat,
  kulcsszintenként; a „Raid ilvl statisztika” a Warcraft Logs adataiból azt, hogy
  milyen itemlevellel ölik meg az aktuális raid bossait Normal, Heroic és Mythic
  nehézségen (lásd lent, „Statisztikák”).
- **Gear ajánló:** egy itemlevelhez (vagy egy karakteréhez) megmutatja, melyik
  tartalom (dungeon, Mythic+, delve, prey, raid, daily) ad még fejlesztést dropból
  vagy a Great Vaultból, melyikhez túl alacsony, és melyiket nőtted már ki. A
  Mythic+ és a raid sorok belépési ilvl-jét a statisztikákból **magától frissíti**:
  alapból hetente lefuttatja a háttérben a két statisztikát, és átviszi az
  eredményüket (lásd lent, „Gear ajánló”).
- **WoW addon:** a mellékelt WoWLeveling addon a játékban elmenti a karakterek
  szintjét (a tapasztalattal együtt), itemlevelét, Mythic+ pontszámát, faját,
  kasztját és specjét. A program a játék mappájának megadása után ezeket **minden
  indításkor**, futás közben pedig **amint a játék kiírja őket** magától (és
  bármikor az „Importálás most” gombbal) beolvassa. Az addon egy kis ablakban azt
  is mutatja, melyik karakter van a **legnagyobb lemaradásban** szintben,
  itemlevelben és Mythic+ pontszámban, mennyit kell elérnie, és mennyi hiányzik; a
  tervet a program szinkronizálja neki (lásd lent, „WoW addon”).
- A listában állítható a karakterek jelenlegi szintje és sorrendje, a karakterek
  szerkeszthetők és törölhetők.
- Minden változást automatikusan elment.

## Követelmények

- Python 3.8 vagy újabb, **tkinterrel** (más csomag nem kell).
  - Windows és macOS: a python.org telepítője tartalmazza a tkintert.
  - Linux: Debian/Ubuntu alatt `sudo apt install python3-tk`, Fedorán
    `sudo dnf install python3-tkinter`.
- A Murlok.io- és Raider.io-adatokhoz és a statisztikákhoz internetkapcsolat kell;
  a raid statisztikához saját (ingyenes) Warcraft Logs API-kulcs is.
- A `requests` csomag nem kell: ha telepítve van, a statisztikai programok azt
  használják, különben a beépített `httpcompat.py`-t (a szabványos urllib-bel).

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
   mezők nyilai egy egész szinttel léptetnek. A célitemlevel nem kötelező, két
   tizedesjegyig adható meg (pl. `326,55`). A régió (EU, US, KR vagy TW) a
   Raider.io-lekéréshez kell, alapból EU. Hibás érték esetén piros üzenet
   jelzi, mi a gond. A helyes beállításokat a program azonnal menti. A két
   céldátum melletti „Kiszámolás a mostani szintekből” gomb a karakterek eddigi
   tempójából számolja ki az első és az utolsó céldátumot (lásd lent); beállítás
   előtt megmutatja a régi és az új dátumokat, és rákérdez.
2. **Új karakter** (a főablak jobb oldalán): írd be a nevét (és ha akarod, a
   realmjét, faját, kasztját, specjét, itemlevelét, Raider.io pontszámát és jelenlegi szintjét),
   majd „Hozzáadás” vagy Enter. A realm, a faj, a kaszt és a spec listából
   választható, de bármit beírhatsz. Ha kasztot váltasz, és a már kiválasztott spec
   nem tartozik az új kaszthoz, a spec mező kiürül. Az itemlevel két
   tizedesjegyig (pl. `327` vagy `326,55`), a Raider.io pontszám egy
   tizedesjegyig adható meg (pl. `2543,7`); a weboldalról ezres elválasztóval
   másolt alak (`2,543.7`) is jó. Az új karakter a lista végére kerül. Ha a
   realmje meg van adva, a program rögtön lekéri a Raider.io-ról az adatait, és
   kitölti az üresen hagyott mezőket (itemlevel, pontszám, faj, kaszt, spec); az
   eredményt a mezők alatt írja ki (pl. ha a karakter nem található). A
   „Combó ajánlása…” gomb megkérdezi, hogy Alliance vagy Horde karaktert
   ajánljon, majd javasol egy combót (lásd lent), és kérésre kitölti vele a faj, a
   kaszt és a spec mezőt.
3. **Karakterlista**: a lista külön ablakban nyílik meg, és minden változásra
   azonnal frissül. A mellette lévő **Gear** gomb a lista Gear változatát nyitja meg
   egy másik ablakban: a rendezése független a karakterlistáétól, a szintezéssel
   kapcsolatos oszlopok helyett a tervezett itemlevel oszlopai vannak benne, és a
   célitemlevelt elért karakterek nem látszanak. A **Mythic+** gomb a Gear ablak
   változatát nyitja meg (saját rendezéssel): ebben a tervezett itemlevel helyett a
   tervezett Raider.io oszlopai vannak, és alul a Raider.io pontszám állítható.
4. **Haladás rögzítése**: jelöld ki a karaktert, írd be a jelenlegi szintjét
   (pl. `84,30`, majd Enter vagy „Beállítás”), vagy nyomd meg a „+1 szint”
   gombot. Billentyűvel: `+` / `-` egy szinttel feljebb/lejjebb, `Delete` törlés.
   A Gear ablakban ugyanígy az itemlevel („+1 itemlevel”), a Mythic+ ablakban a
   Raider.io pontszám („+1 pont”) állítható; ezek üresre is törölhetők. Minden
   ablakban dupla kattintásra (vagy a „Szerkesztés…” gombbal) a karakter minden
   adata módosítható.
5. **Rendezés**: a karakterlista mindig az „Állapot” szerint nyílik meg, a
   legsürgősebbel kezdve: lejárt céldátum, lemaradásban, ütemben, mai cél
   teljesítve, előrébb jár, még nem kezdődött, végül a célszintet elért (kész)
   karakterek. Azonos állapotban a szinteltérés dönt (elöl a leginkább lemaradt).
   Kattints egy oszlop fejlécére a más szerinti rendezéshez; újabb kattintásra
   megfordul az irány (a fejlécben ▲ = növekvő, ▼ = csökkenő). Ez csak addig tart,
   amíg az ablak nyitva van: újra megnyitva ismét az állapot szerint rendez (a Gear
   és a Mythic+ ablak a saját rendezését megtartja). A rendezés csak a nézetet
   változtatja meg, a karakterek sorrendjét nem. A # oszlopra kattintva visszakapod
   az eredeti sorrendet. Az üres értékek (pl. a kész karakterek mai célja) mindig a
   lista végére kerülnek, a „Kaszt” szerinti rendezés pedig kaszton belül spec
   szerint rendez.
6. **Sorrend**: a „▲ Feljebb” / „▼ Lejjebb” gombokkal, a # szerinti nézetben (a #
   oszlop fejlécére kattintva). A sorrend határozza meg, melyik karakternek kell
   elsőként, melyiknek utoljára elérnie a célszintet.
7. **Murlok.io szerinti sorrend**: ez a gomb az összes karakter sorrendjét
   beállítja a Murlok.io-pontszámok alapján, körönként. Az első körbe minden
   class/specből egy karakter kerül (a legmagasabb szintű), a körön belül a
   magasabb pontszámú spec van elöl; a második körbe ugyanígy a következő karakter
   minden class/specből, és így tovább. Akinek nincs pontszáma (nincs megadva vagy
   ismeretlen a class/spec), a lista végére kerül. A program átrendezés előtt
   rákérdez. A nézet rendezése utána sem változik (a karakterlistában marad az
   állapot szerinti); az új sorrend a # oszlopban látszik.
8. **Raider.io-adatok**: a listaablakok (karakterlista, Gear, Mythic+)
   megnyitásakor a program magától lekéri minden olyan karakter adatait,
   amelynél meg van adva a realm, ha a legutóbbi ilyen lekérés régebbi fél
   óránál. Ugyanígy lekéri egy karakterét, ha a szerkesztésnél megváltozik a
   neve vagy a realmje. A listaablakok tetején lévő „Frissítés a Raider.io-ról”
   gombbal bármikor újra lekérheted (lásd lent). A lekérés a háttérben fut, az
   állapota és az eredménye a gomb mellett látszik.
9. **Statisztikák**: a főablak „M+ ilvl statisztika” és „Raid ilvl statisztika”
   gombja egy-egy külön ablakot nyit. Állítsd be a lekérdezést, majd „Indítás”: a
   lekérdezés a háttérben fut, a táblázat menet közben frissül, a „Leállítás” az
   addigi adatokkal zárja le, a „CSV mentése…” pedig fájlba írja az eredményt
   (lásd lent). Az „Átvitel a gear ajánlóba” az eredmény mediánjait a gear ajánló
   belépési ilvl-jeibe írja.
10. **Gear ajánló**: a főablak „Gear ajánló” gombjával, vagy a Gear ablakban a
    kijelölt karakterhez a „Gear ajánló…” gombbal (lásd lent). A Mythic+ és a raid
    sorok belépési ilvl-jei a statisztikákból magától frissülnek; ennek állapota a
    főablak alján látszik.
11. **WoW addon**: a főablak „WoW addon” keretében add meg a World of Warcraft
    mappáját (beírva vagy a „Tallózás…” gombbal), és telepítsd az addont az
    „Addon telepítése…” gombbal. A program ezután minden indításkor beolvassa a
    játékban elmentett adatokat, futás közben pedig magától, amint a játék újakat
    ír ki (és bármikor az „Importálás most” gombbal; lásd lent).

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

**Céldátumok a mostani szintekből.** A „Kiszámolás a mostani szintekből” gomb a
mostani szinteket a tegnapi nap végéig elértnek tekinti: az eddigi tempó a
kezdőnaptól tegnapig a kezdőszint felett megszerzett szintek (legfeljebb a
célszintig) osztva a napok számával, a mai nap pedig már a hátralévő szintek első
napja.

- *Első céldátum:* amikor a lista első karaktere a saját eddigi tempójával eléri a
  célszintet. Ha például 10 nap alatt 44,50 szintet lépett (napi 4,45), és még
  44,50 szint van hátra, akkor ez a mai nappal együtt 10 nap. Ha még nem lépett túl
  a kezdőszinten, a program a karakterek együttes tempójával számol; ha már
  célszinten van, a céldátuma legkésőbb a tegnapi nap (a korábbi dátum megmarad).
- *Utolsó céldátum, egymás utáni ütemezésnél:* amikorra a karakterek együttes
  eddigi tempójával az összes hátralévő szint meglesz.
- *Utolsó céldátum, párhuzamos ütemezésnél:* a legkorábbi nap, amellyel a
  karakterek együtt (ugyanúgy számolva, mint a lista alján lévő napszint) éppen
  elérik a terv tegnapi célját. Aki pontosan a terv szerint halad, annak a
  céldátumai nem változnak.
- Az utolsó céldátum nem lehet korábbi az elsőnél. A számoláshoz legalább egy
  lezárt szintezési nap kell (a mai nap még nem számít bele), és legalább egy
  karakternek túl kell lépnie a kezdőszinten.

**Tervezett itemlevel (Gear ablak).** A Murlok.io szerinti sorrendben (ugyanaz,
mint a „Murlok.io szerinti sorrend” gombnál) az első karakter tervezett itemlevele a
célitemlevel − X, a másodiké az elsőé − X, és így tovább: a k-adiké célitemlevel −
k·X (0-nál nem kevesebb). Az **itemlevel-eltérés** a valós és a tervezett itemlevel
különbsége (+: a terv felett, −: alatta), a Gear ablak alapból eszerint rendez
növekvő sorrendben. X-et a program magától állítja be úgy, hogy ebben a sorrendben
a 2. sorban 0 legyen az eltérés, így az 1. sorban negatív: a (célitemlevel −
itemlevel) / sorszám hányadosok közül a második legnagyobb. X értéke a táblázat
fölött látszik.

- Aki elérte a célitemlevelt, lekerül a Gear listáról, és a program a maradék
  karakterekkel számol: a sorrend, a sorszámok és X is csak belőlük adódik. Hogy
  hány karakter került így le, a táblázat fölött látszik.
- Csak a megadott itemlevelű karakterek számítanak bele X-be, de tervezett
  itemlevelet minden (listán maradt) karakter kap. Kell hozzá célitemlevel (a
  főablakban) és legalább két, a célitemlevel alatti karakternél itemlevel.
- Murlok.io-pontszámok nélkül a sorrend a lista sorrendje.

**Tervezett Raider.io (Mythic+ ablak).** Ugyanabban a Murlok.io szerinti
sorrendben, mint a tervezett itemlevelnél, a k-adik karakter tervezett Raider.io
pontszáma a specje Murlok.io-pontszámának (100% − k·x)-szerese: az elsőé
(100% − x)-szerese, a másodiké (100% − 2x)-szerese, és így tovább (0-nál nem
kevesebb). A **Raider.io-különbözet** a valós és a tervezett pontszám különbsége
(+: a terv felett), a Mythic+ ablak alapból eszerint rendez növekvő sorrendben.
x-et a program magától állítja be úgy, hogy a második karakternél 0 legyen a
különbözet: ha a második karakter Raider.io pontszáma R, a specjéé a Murlok.io-n
M, akkor x = (1 − R/M) / 2. Az x értéke a táblázat fölött látszik.

- Ha a második karakternek nincs Raider.io vagy Murlok.io pontszáma, a sorrendben
  következő olyan karakter különbözete lesz 0, akinek mindkettő megvan.
- A célitemlevelt elért karakterek itt is kimaradnak. Murlok.io-pontszám nélküli
  karakter (nincs megadva vagy ismeretlen a class/spec) nem kap tervezett Raider.io
  pontszámot.

**Combó ajánlása.** A választott frakcióban létrehozható class/spec/faj combók
közül az a javaslat, amelyik leginkább hiányzik a listáról. A program a meglévő
karaktereket öt szempont szerint vizsgálja, ebben a sorrendben:

1. szerep (tank, healer, melee DPS, ranged DPS),
2. páncéltípus (cloth, leather, mail, plate),
3. kaszt,
4. spec,
5. faj.

A **szerepnél és a páncéltípusnál** nem az egyforma darabszám a cél, hanem az az
arány, ahogy a frakció összes class/spec/faj combója között előfordulnak. A Horde
419 combójából például 51 tank (12%), 65 healer (16%), 149 melee DPS (36%) és 154
ranged DPS (37%); a páncéltípusok közül 32% cloth, 26% leather, 22% plate és 19%
mail. Az a szerep (páncéltípus) jön előbb, amelyik ettől a legjobban elmarad: ahol
a meglévő karakterek száma a legkisebb ahhoz képest, amennyi az arány szerint egy
újabb karakterrel együtt járna neki. Így a karakterek eloszlása lépésről lépésre a
lehető legközelebb marad ezekhez az arányokhoz (üres listánál ezért ranged DPS és
cloth az első). A **kasztnál, a specnél és a fajnál** az jön előbb, amelyikből a
legkevesebb van.

Az a combó nyer, amelyik a szerep szerint hiányzik leginkább; ha ebben több is
egyforma, az, amelyik a páncéltípus szerint, és így tovább. Ha minden szempont
szerint egyformák, a magasabb Murlok.io-pontszámú class/spec az első (pontszámok
nélkül a kasztok ábécérendje dönt), a fajok közül pedig az alapfajok a
szövetséges (allied) fajok előtt. A javaslat mellett a program megmutatja a
számokat (a szerepnél és a páncéltípusnál a mostani és a combók közti arányt is) és
a következő három jelöltet.

- Csak a játékban létrehozható faj–kaszt kombinációkat ajánlja (Midnight, 12.1-es
  patch; pl. Evoker csak Dracthyr lehet). A 12.2-es patchben érkező Night Elf,
  Troll és Undead Paladin még nincs benne.
- A felismerhetetlen (kézzel beírt) kasztot, specet vagy fajt a számolás kihagyja.
  Spec nélkül a szerep csak akkor számít, ha a kaszt minden specje ugyanazt a
  szerepet tölti be (pl. Mage: ranged DPS, Rogue: melee DPS; a Hunter nem, mert a
  Beast Mastery és a Marksmanship ranged, a Survival melee).
- A Devourer Demon Hunter és az Augmentation Evoker ranged DPS-nek számít.
- A meglévő karaktereket frakciótól függetlenül számolja (a Pandaren, Dracthyr,
  Earthen és Haranir karakterek frakcióját a program nem tárolja).

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

**Raider.io-lekérés.** A program karakterenként egy kérést küld a Raider.io
nyilvános API-jának (`https://raider.io/api/v1/characters/profile`) a karakter
nevével, realmjével és a beállított régióval, és ezeket írja be a válaszból:

- **Itemlevel**: a felvett tárgyak átlagos itemlevele. A Raider.io ezt sokszor
  lefelé kerekítve, egész számként adja meg, ezért a program a tárgyak
  itemleveléből két tizedesre számolja ki, ahogy a játék is (16 hely, a kétkezes
  fegyver kétszer számít). Ha ez nem egyezik a Raider.io értékével (pl. mert
  hiányzik egy tárgy), a Raider.io egész értékét veszi; ilyenkor a kézzel beírt,
  ugyanilyen egész részű pontosabb érték (pl. 333,56 a 333 helyett) megmarad.
- **Raider.io pontszám**: az aktuális szezon összesített Mythic+ pontszáma.
- **Faj, kaszt és spec**: csak akkor, ha a mező üres. A spec a karakter
  Raider.io-n látható aktív specje, és csak akkor kerül be, ha a karakter
  kasztja ugyanaz, mint a Raider.io-n.

- A nagyobb értékeket (és az eddig üreseket) a program magától beírja. Ha a
  Raider.io kisebb itemlevelt vagy pontszámot mutat, mint ami be van írva, azt
  csak a gombbal indított lekérésnél írja át, és akkor is csak rákérdezés után:
  a Raider.io a karaktereket időnként frissíti a játékból, így az adata néhány
  órával régebbi is lehet a kézzel beírtnál.
- A magától induló lekérés nem kérdez és nem nyit ablakot: az eredménye (pl. „2
  karakter adata frissült, 1 karakter nem található, 1 kisebb értéket nem írtam
  át”) a gomb mellett látszik, új karakternél pedig a hozzáadás mezői alatt. A
  gombbal indított lekérés végén a program felsorolja, kit nem talált, és kinél
  hiányzik a realm.
- A realm nélküli karaktereket kihagyja. Akit a Raider.io nem ismer (elírt név
  vagy realm), annak az adatai nem változnak, a többieké ettől még frissül. Ha a
  Raider.io nem érhető el, a lekérés leáll, és a hiba a gomb mellett is látszik.
- Ha lekérés közben adsz hozzá új karaktert, az övé a futó lekérés után
  következik.
- Internetkapcsolat kell hozzá. A karakterek nevén, realmjén és a régión kívül a
  program nem küld semmit. A legutóbbi lekérés ideje az adatfájlba is bekerül.

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

## Statisztikák

A két statisztika a program mappájában lévő két önálló program
(`raiderio_ilvl_stats.py` és `wcl_raid_ilvl_stats.py`) ablakos változata: ugyanazt
számolják, csak a beállítások mezőkben vannak, az eredmény táblázatban látszik, és a
parancssori Ctrl+C helyett a „Leállítás” gomb állítja meg őket. Mindkettő
gyorsítótárat használ (a program mappájában, lásd „Adatok”), így egy újabb
lekérdezés csak azt tölti le, ami még nincs meg. Az ablakok mezői megmaradnak a
következő megnyitásra; az API-kulcsokat a „Megjegyzés ezen a gépen” bejelölésével
az `api_kulcsok.json` fájlba menti a program (titkosítás nélkül). A gear ajánló
automatikus frissítése is az ablakokban beállított értékekkel, és az elmentett
kulcsokkal futtatja a lekérdezéseket (lásd „Gear ajánló”).

**M+ ilvl statisztika (Raider.io).** Kulcsszintenként: hány futás és hány
játékos adata került bele, valamint a játékosok itemlevelének átlaga, mediánja,
25. percentilise (P25: a játékosok negyedének ennél kisebb az itemlevele),
minimuma és maximuma. Egy futás csapatának itemlevelei a futás idejéből valók
(`mythic-plus/run-details`).

- **Forrás:** a *ranglista* a régió legjobb pontszámú futásait olvassa (oldalanként
  20 futás) – gyors, de csak a magas kulcsokat éri el, mert a ranglista mindig a
  legmagasabb pontszámmal kezd. A *guildek* a megadott guildek (`Név@realm`, több
  vesszővel; más régióból `Név@realm@us`) tagjainak legutóbbi futásait olvassák –
  így minden kulcsszint előjön.
- **A csapattagok guildjeit is bejárja:** a talált csapatok tagjainak guildjeit
  is beolvassa, majd azok csapataiét, és így tovább; ez nagyon sokáig futhat (a
  „legfeljebb N guild” korlátozza, vagy a „Leállítás”). Guildeknél alapból be van
  kapcsolva, a ranglistánál nincs (ott a ranglista oldalai után kezdi).
- **Kulcsszintek:** csak ezeket gyűjti (pl. `2-10` vagy `18,19,20`; üresen mind);
  **legfeljebb N futás szintenként:** egy szintből ennyi után nem gyűjt többet, és
  ha minden kért szint megvan, leáll.
- **Itemlevel:** a tartományon kívüli itemlevelű játékos kimarad (a csapat többi
  tagja számít); **csak az utolsó N nap** futásai; **csak az időben teljesített
  futások** (alapból igen).
- **A korábban letöltött futásokat is beszámolja** (alapból ki): alapból csak az
  számít, amit a mostani lekérdezés elér – a gyorsítótár csak a letöltést spórolja
  meg. Bekapcsolva a gyorsítótárban lévő összes idei szezonbeli futás is
  beleszámít, bármelyik korábbi lekérdezés (ranglista vagy guildek) töltötte le,
  ha megfelel a szűrőknek: a régió, a kulcsszintek, az utolsó N nap, az időben
  teljesítés, az itemlevel-tartomány és a „legfeljebb N futás szintenként” (a
  legújabbak előbb). Az affix nem szűri őket. Ezeket a lekérdezés előtt számolja
  be (a táblázat azonnal megtelik), és a lekérdezés nem számolja őket újra; a
  csapataik guildjeit nem járja be. Így a minta attól is függ, mit kérdeztél le
  korábban: a ranglista főleg magas kulcsokat hoz, a guildek minden szintet.
- **Ranglista:** hány oldalt olvasson (API-kulcs nélkül legfeljebb 100),
  **minden dungeon külön** (alacsonyabb kulcsokat is elér), **affix** (pl. a csak
  a +2…+5 kulcsokon élő `lindormis-guidance`-szel a ranglista is eléri a kis
  kulcsokat).
- **Raider.io API-kulcs** (nem kötelező, https://raider.io/settings/apps):
  nagyobb lekérési keretet ad.

**Raid ilvl statisztika (Warcraft Logs).** Az aktuális raid bossaira
nehézségenként (Normal, Heroic, Mythic) és bossonként: a kill-ek száma, valamint
az itemlevel átlaga, mediánja, 25. percentilise, minimuma és maximuma, a végén
az összes bossra együtt. Egy adatpont egy kill: a harcban részt vevő játékosok
átlagos itemlevele („Raid átlag / kill”); kérésre a játékosok egyéni itemlevele
is („Játékosok egyéni itemlevele”, bossonként és nehézségenként N kill
játékosaiból – ez drága: kb. 11 API-pont / kill, az óránkénti keret 3600 pont,
elfogyásakor a program kivár).

- **API-kulcs** (egyszer kell): https://www.warcraftlogs.com/api/clients →
  „Create Client”; név bármi, Redirect URL pl. `http://localhost`, a „Public
  Client” ne legyen bepipálva. A kapott Client ID-t és Client Secretet írd be az
  ablak tetején.
- **Raid:** üresen a legújabb aktív raid; különben a neve (részlet) vagy a
  Warcraft Logs-os zóna száma.
- **Minta:** az utolsó N nap reportjaiból ennyi oldalnyit olvas, oldalanként
  ennyi reporttal (az időszakot egyenletesen lefedve); **régió:** csak ennek a
  régiónak a guildjei. A több logger által feltöltött ugyanazon kill-t egyszer
  számolja.
- **Kihagyott bossok:** a Warcraft Logs a raid zónájába sorolja a Lair / world
  bossokat is; ezeket alapból kihagyja.
- **Minden újra letöltése:** a gyorsítótárban lévő adatok helyett mindent újra
  lekér.

**Parancssorból** a két program ugyanúgy futtatható, mint eddig (minden
beállításuk leírása a fájlok elején olvasható), pl.:

```
python raiderio_ilvl_stats.py --guild "Solutions@ragnaros" --levels 2,3,4,5,6,7,8,9,10 --csv live.csv
python wcl_raid_ilvl_stats.py --days 14 --pages 150 --csv stat.csv
```

## Gear ajánló

A „WoW Gearing Ajánló” HTML-oldal a programban. Add meg az itemlevelt (vagy
válassz karaktert a megadott itemlevelűek közül – ha az itemlevele változik, az
ajánló is követi), és a táblázat minden tartalomról megmondja, megéri-e:

| Ajánlás | Jelentés |
|---|---|
| Irány farmolni! | a drop még fejleszt (megjegyzés: mennyit) |
| Csak Vaultért | a drop már nem, de a Great Vault még fejleszt |
| Túl alacsony ilvl | a belépési ilvl alatt vagy (megjegyzés: mennyi hiányzik) |
| Túlfejlett vagy | már a Vault sem fejleszt |

A sorrend: előbb az ajánlottak (a legnagyobb fejlesztés elöl), aztán a csak
Vaultért érdemesek, a túl magasak (a legközelebbi elöl), végül a kinőttek. A
tartalomtípusok (Dungeon, Mythic+, Delve, Prey, Raid, Világ / Daily) ki-be
kapcsolhatók; a Delve és a Prey csoportból alapból csak a legjobb elérhető tier
látszik („Minden Delve/Prey tier mutatása”). Itemlevel nélkül minden sor látszik,
értékelés nélkül.

**A belépési ilvl-ek frissítése (adatátvitel).** A Mythic+ sorok belépési ilvl-je
a kulcsszint játékosainak medián itemlevele (M+ ilvl statisztika), a raid soroké a
boss kill-jeinek medián itemlevele az adott nehézségen (Raid ilvl statisztika, a
„raid átlag / kill” mérőszám). Ahol nincs adat (a statisztikában nem szereplő
kulcsszint, még meg nem ölt boss), ott a belépési ilvl marad; az „Összes boss” sor
nem számít. A frissített értékek az adatfájlba kerülnek, az „Alapértékek
visszaállítása” gomb törli őket.

**Automatikus frissítés.** A program indításkor (és amíg nyitva van, percenként
ellenőrizve) a háttérben lefuttatja azt a statisztikát, amelynek az eredménye a
beállított napoknál (alapból 7) régebben került át a gear ajánlóba, és az
eredményt **kérdés nélkül** átviszi. A lekérdezés az adott statisztikai ablakban
utoljára beállított értékekkel fut (ha még nem nyitottad meg, az alapértékekkel:
M+ – a régió ranglistájának 5 oldala; raid – az utolsó 7 nap), a raidhez a
Warcraft Logs API-kulcs kell (az ablakban a „Megjegyzés ezen a gépen”
bejelölésével elmentve). Közben nyugodtan dolgozhatsz:

- Az állapota a főablak alján és a gear ajánló alján látszik (fut, mikor frissült
  és hány belépési ilvl változott, vagy mi volt a gond).
- A statisztikai ablak gombjával megnyitva a futó frissítés (utána az eredménye)
  látszik, a „Leállítás” megállítja; bezárva az ablakot a háttérben fut tovább.
- Ami nem sikerült (vagy leállítottad), azzal a program a következő indításig nem
  próbálkozik újra magától; a gear ajánló „Frissítés most” gombja bármikor
  elindítja mindkét statisztikát.
- A gear ajánló alján kapcsolható ki, és ott állítható, hány naponta fusson.

Kézzel is át lehet vinni:

- a statisztikai ablakokból, az „Átvitel a gear ajánlóba” gombbal, a lekérdezés
  után (ez is számít frissítésnek, ehhez igazodik az automatikus);
- a gear ajánlóban az „Importálás CSV-ből…” gombbal a statisztikák CSV-jéből
  (`live.csv`, `stat.csv` – a parancssori programok `--csv` kimenete, vagy a
  „CSV mentése…” gombé). Egyszerre több fájl is választható.

Kézi átvitelnél átírás előtt a program megmutatja, mi változik, és rákérdez.

**HTML mentése.** A „HTML mentése…” gomb elmenti a „WoW Gearing Ajánló”
HTML-oldalt a program mostani adataival (böngészőben is használható). A
`wow-gearing-ajanlo-refaktoralt.html` sablonban csak a számok cserélődnek, minden
más ugyanaz marad.

A tartalmak listája (belépési, drop és Vault ilvl-ek) a `gearing.py` elején van
(`GROUPS`); új szezonnál ott kell átírni.

## WoW addon

Az `addon/WoWLeveling` mappában lévő addon a játékban minden karakterről, amellyel
belépsz, elmenti:

- a nevét, a realmjét és a régióját,
- a faját, a kasztját és az aktív specjét,
- a szintjét két tizedesjegyre, a tapasztalattal együtt (pl. 85-ös szint, a
  következő szinthez szükséges tapasztalat 29%-a: `85.29`; a százalékot lefelé
  kerekíti, mint a program), mellette a tapasztalat pontos értékét is,
- a felvett tárgyak átlagos itemlevelét (amit a karakterlap is mutat),
- az aktuális szezon Mythic+ pontszámát.

**Telepítés.** A főablak „WoW addon” keretében add meg a World of Warcraft
mappáját (pl. `C:\Program Files (x86)\World of Warcraft`; a „Tallózás…” gombbal ki
is választhatod), majd kattints az „Addon telepítése…” gombra: a program a
`_retail_\Interface\AddOns\WoWLeveling` mappába másolja az addont (frissíteni is
így lehet). Kézzel is bemásolhatod oda az `addon\WoWLeveling` mappát. Ha a játék
fut, írd be a chatbe: `/reload`. A karakterválasztó „AddOns” gombjával
ellenőrizheted, hogy be van-e kapcsolva.

**Mentés.** Az addon játék közben folyamatosan frissíti az adatokat (a
tapasztalatnál, szintlépéskor, a felszerelés vagy a spec cseréjekor és egy Mythic+
kör után), de fájlba a játék csak kilépéskor, kijelentkezéskor (karakterváltáskor
is) és `/reload` után írja ki őket – máskor egy addon sem tudja kiíratni –,
fiókonként ide (kilépéskor az addon már nem olvas a játékból, mert az ekkor a
tapasztalatra és a specre 0-t ad vissza, így a legutóbbi, játék közbeni állapot
kerül a fájlba):

```
World of Warcraft\_retail_\WTF\Account\<FIÓK>\SavedVariables\WoWLeveling.lua
```

Ha játék közben azonnal kell, a `/wowleveling mentés` parancs vagy a lemaradás
ablakának „Mentés” gombja (ez előbb megkérdezi) újratölti a felületet, mintha
`/reload`-ot írtál volna: ilyenkor egy pár másodperces töltőképernyő után a fájl
már a friss adatokat tartalmazza.

Az addon régebbi (1.2 előtti) változata az egész szintet és mellette a
tapasztalatot mentette; a program az ilyen mentéseket is beolvassa, a telepített
addont pedig a következő szinkronizáláskor frissíti (lásd lent). Az 1.3.1 előtti
változatok a kilépéskor kapott nullákat is elmentették (`xp = 0`, `xpMax = 0`,
`specID = 0`), ezért náluk egész szint áll a fájlban: ez a karakter következő
belépése után javul ki. Az addon a változatát is beírja a mentésbe; ha a
legutóbbi mentést még régebbi változat írta, a program szól, hogy az új a játék
következő indításakor vagy `/reload` után töltődik be.

Játék közben a `/wowleveling` (vagy `/wowlvl`) parancs kiírja a karakter
elmentett adatait, a `/wowleveling lista` az összes elmentett karakterét, a
`/wowleveling ablak` be- és kikapcsolja a lemaradás ablakát (lásd lent), a
`/wowleveling mentés` pedig most rögtön kiíratja az adatokat (lásd fent).

**Importálás.** A program **minden indításkor magától** beolvassa a mentéseket,
és bármikor az „Importálás most” gombbal. **Futás közben is figyeli** őket: amint
a játék új mentést ír ki (kilépéskor, karakterváltáskor, `/reload` vagy a
„Mentés” után), néhány másodpercen belül magától beolvassa – nem kell újraindítani
a programot, és gombra sem kell kattintani. Útvonalként a World of Warcraft
mappáját érdemes megadni, de jó a `_retail_`, a `WTF`, egy fiók mappája vagy maga
a `WoWLeveling.lua` fájl is; több fiók mentéseit is beolvassa. Ha nincs megadva
útvonal, indításkor a szokásos telepítési helyeken keresi (Windowson a Program
Files mappában, macOS-en az Applications mappában).

- A listán lévő karaktereket **név és realm szerint** párosítja; a kis- és
  nagybetűk, az ékezetek és a realm szóközei nem számítanak (`Zoltan` = `Zôltan`,
  `TwistingNether` = `Twisting Nether`). A realm nélküli karaktert név szerint, ha
  egyértelmű; ilyenkor a realmjét is kitölti.
- A **szint**, az **itemlevel** és a **Raider.io pontszám** (a játékbeli Mythic+
  pontszám, ha nem nulla) a játékbeli értékre változik, a név a játékbeli
  írásmódra. A realm, a faj, a kaszt és a spec csak az üres mezőbe kerül be (a spec
  csak akkor, ha a kaszt is ugyanaz).
- Egy mentést csak egyszer használ fel: ha a programban kézzel átírsz egy adatot,
  azt csak a játékból jövő újabb mentés írja felül.
- A listán még nem szereplő karaktereket indításkor csak felsorolja. Az
  „Importálás most” gomb megkérdezi, melyek kerüljenek fel: a bejelöltek a lista
  végére kerülnek, a magasabb szintűek előbb. Akiket nem jelölsz be, azokat a
  program megjegyzi, és többé nem kínálja fel (ha mégis kell valamelyik, vedd fel
  kézzel – az adatai ugyanúgy frissülnek).
- Az eredmény (és az esetleges hiba) a „WoW addon” keretben látszik; a gombbal
  indított importálás a változásokat egy üzenetben is felsorolja.

**A lemaradás ablaka.** Az addon egy kis, egérrel áthelyezhető ablakban mutatja,
hogy a program terve szerint

| Sor | melyik karakter | cél | hiányzik |
|---|---|---|---|
| Szint | a legnagyobb szinteltérésű (a leginkább lemaradt) | az a szint, amellyel 0 lenne az eltérése (a mai cél) | ennyi szint |
| Itemlevel | a legnagyobb itemlevel-eltérésű | a tervezett itemlevele | ennyi itemlevel |
| Mythic+ | a legnagyobb Raider.io-különbözetű | a tervezett pontszáma | ennyi pont |

Ha senki sincs lemaradásban, ezt írja ki; ha egy terv nem számolható (pl. nincs
célitemlevel), az okát. Az ablak ugyanazt számolja, mint a program (a
karakterlista, a Gear és a Mythic+ ablak), az előretekintéssel együtt: a mai
napot a gép órájából veszi, így napok múlva is a napi célokkal számol. Bezárni a
sarkában lévő X-szel, újra megnyitni a `/wowleveling ablak` paranccsal lehet; a
helyét és azt, hogy látszik-e, megjegyzi. Az X melletti „Mentés” gomb most rögtön
kiíratja az adatokat a program számára (a felület újratöltésével, lásd fent).

- **Szinkronizálás:** a program a terv adatait (a karaktereket a szintjükkel,
  itemlevelükkel, pontszámukkal és a terv beállításaival) a telepített addon
  mappájába írja (`PlanData.lua`): magától minden változás után, és a „WoW addon”
  keret „Szinkronizálás” gombjával. A játék az addon fájljait belépéskor és
  `/reload` után olvassa be, így a változás ezután látszik az ablakban. Ha az
  addon régebbi változat, a program a szinkronizáláskor frissíti is.
- **Automatikus frissítés:** ha a három kiírt karakter valamelyikével játszol, az
  ablak a játékbeli adatokból magától frissül (tapasztalat, szintlépés,
  felszerelés, Mythic+ pontszám), és ezt a lábléc jelzi. Ha közben más karakter
  kerül a legnagyobb lemaradásba, azt mutatja. A többi karakterhez az addon a
  saját mentéseit is felhasználja, ha azok újabbak annál, amit a program már
  beolvasott (pl. ha ugyanabban a játékmenetben több karakterrel is játszol).

Az addon a Midnight 12.1-es patchéhez készült. Ha egy újabb patch után a játék
elavultnak („Out of date”) jelzi, az AddOns ablakban kapcsold be a „Load out of
date AddOns” lehetőséget, vagy írd át a `WoWLeveling.toc` fájl `## Interface:`
sorában a számot az új verzióéra.

## Adatok

A beállítások és a karakterek a program mappájában lévő `szintezes_adatok.json`
fájlba kerülnek (egyszerű, olvasható JSON). Ha ezt a fájlt elmented, az adataid is
megvannak. A program korábbi (maximum szintes) változatának adatfájlját is
beolvassa: ilyenkor a kezdőszint 1,00, a célszint a korábbi maximum szint lesz. Ha
a fájl megsérül, a program átnevezi (`szintezes_adatok.hibas-<időpont>.json`, így
nem vész el), és alapbeállításokkal indul.

A statisztikák a fájljaikat az adatfájl mellé teszik: `raiderio_ilvl_cache.json`
és `wcl_cache.sqlite` (a letöltött adatok gyorsítótára – bármikor törölhető, csak
újra le kell tölteni őket), valamint – ha kéred – `api_kulcsok.json` (az
API-kulcsok).

Az addon mentéseinek beolvasásához és a terv szinkronizálásához a program az
adatfájlban megjegyzi a WoW mappáját, karakterenként a legutóbb felhasznált mentés
idejét, és azokat a karaktereket, amelyeket nem kértél fel a listára. A gear
ajánló automatikus frissítéséhez a beállításait és azt, hogy a két statisztika
eredménye mikor került át utoljára.

## Fájlok

- `wow_leveling.py` – a grafikus felület, ezt kell elindítani
- `leveling.py` – az ütemezés számítása, mentés és betöltés
- `murlok.py` – a spec-pontszámok lekérése a Murlok.io-ról
- `raiderio.py` – az itemlevelek és a Raider.io pontszámok lekérése a Raider.io-ról
- `recommend.py` – a combóajánlás
- `stats_windows.py` – a két statisztikai ablak
- `raiderio_ilvl_stats.py` – Mythic+ itemlevel-statisztika a Raider.io-ról (önállóan
  is futtatható)
- `wcl_raid_ilvl_stats.py` – raid itemlevel-statisztika a Warcraft Logs-ról
  (önállóan is futtatható)
- `httpcompat.py` – a `requests` csomag pótlása a szabványos urllib-bel
- `gearing.py` – a gear ajánló adatai és számolása, az adatátvitel a
  statisztikákból
- `gear_advisor.py` – a gear ajánló ablaka
- `wow-gearing-ajanlo-refaktoralt.html` – a gear ajánló HTML-oldala (a „HTML
  mentése…” sablonja)
- `wow_data.py` – a kasztok, specek, szerepek, páncéltípusok, fajok, frakciók és
  a választható faj–kaszt kombinációk
- `wow_addon.py` – a WoWLeveling addon mentéseinek beolvasása és importálása, a
  terv átadása az addonnak
- `addon/WoWLeveling/` – a WoW addon: `WoWLeveling.toc`, `WoWLeveling.lua` (mentés
  és az ablak), `Plan.lua` (a lemaradások számolása, mint a programban),
  `PlanData.lua` (a program által szinkronizált terv)
- `tests/` – automatikus tesztek (a `tests/addon_harness.lua` a játék nélkül,
  utánzott játékkörnyezetben futtatja az addont, a `tests/plan_harness.lua` pedig
  véletlen terveken összeveti a számolását a programéval)

## Tesztek

```
python -m unittest discover -s tests -v
```

A felület tesztjeihez grafikus kijelző kell (Linuxon kijelző nélkül pl.
`xvfb-run python -m unittest discover -s tests`); ha nincs, ezek kimaradnak. Az
addon tesztjéhez Lua-értelmező kell (`lua5.1`, `luajit` vagy `lua`); ha nincs, ez
a teszt kimarad.
