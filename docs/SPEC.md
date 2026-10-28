# PostalPrint — specifikation

> Lokalt Windows-program, der printer modtageradresser til breve på en 100 × 150 mm termisk labelprinter.
> Dokumentet beskriver, hvad programmet gør, og hvorfor det er bygget, som det er.
> Alle navne og adresser i dokumentet er **fiktive eksempler**.

---

## 1. Formål og afgrænsning

**Formål:** Spare tid og undgå håndskrevne adresser for små webshops og foreninger, der sender mange breve (fx dao-breve i boblekuvert med fysisk brevmærke).

**Programmet:**
- Tager imod en modtageradresse via tastaturet med så få tryk som muligt.
- Validerer adressen og kræver, at fejl rettes før print.
- Genererer en PDF og printer den **automatisk** på labelprinteren (uden printdialog).
- Gemmer alle printede etiketter i en lokal historik (JSON pr. måned).
- Gemmer selve PDF'en for hver printet etiket, så den kan findes og printes manuelt, hvis printeren fx ikke printede korrekt (se afsnit 9).

**Programmet gør ikke:**
- Køber porto eller laver stregkoder, dao-logoer eller officielle forsendelseslabels.
- Har plads til frimærke på etiketten. Frimærket sættes direkte på kuverten i øverste højre hjørne, *uden for* etiketten.
- Understøtter udland (kun Danmark i version 1).
- Bruger ordrenumre. Ordrer findes i historikken på navn og adresse.

**Designprincipper:**
- Så nemt som muligt at bruge: tastaturet først, få klik, klare fejlbeskeder.
- Enkelt: ingen database, ingen cloud, ingen frontend-frameworks.
- Alt kører lokalt, og alle persondata bliver på computeren (afsnit 13).
- Brugerfladen er på dansk. Kode, kommentarer og tests er på engelsk.

---

## 2. Hardware og miljø

| | |
|---|---|
| Printer | Generisk termisk labelprinter, typisk 203 dpi |
| Medie | Standard 100 × 150 mm klistermærker (GLS-format) |
| OS | Windows 10/11 |
| Uden printer | Print-tilstanden `file` åbner PDF'en i stedet, så programmet kan udvikles og afprøves uden printer |

**Konsekvenser af termisk print:**
- Kun sort, ingen grå og ingen farver.
- Linjer mindst 0,5 pt tykke, ellers forsvinder de.
- Ingen store sorte flader (spild og varme).

---

## 3. Teknologi

| Del | Valg | Begrundelse |
|---|---|---|
| Sprog | Python 3.12+ | God PDF-understøttelse, enkelt at vedligeholde |
| Webserver | Flask | Lille og lytter kun på `127.0.0.1` |
| PDF | ReportLab | Sidestørrelse angives præcist i mm |
| UI | HTML + CSS + vanilla JavaScript | Ingen build-step, intet framework |
| Print | SumatraPDF (gratis, Windows) via kommandolinje | Printer direkte uden dialog og uden skalering |
| Lagring | JSON-filer | Læsbare og nemme at tage backup af |
| Tests | pytest + pypdf | pypdf bruges til at måle PDF'ens størrelse i tests |
| Postnumre | GeoNames (CC BY 4.0) | Fri liste uden API-nøgle. DAWA lukkede 1. oktober 2026 |
| Online-adressetjek | OpenStreetMap Nominatim | Gratis, ingen API-nøgle, finder danske husnumre |
| Pakning | `pyproject.toml` + PyInstaller | Én `.exe` med Python indbygget til brugere uden Python |
| CI | GitHub Actions | Tests ved hvert push, `.exe` bygges og udgives ved version-tags |

Afhængighederne er låst til præcise versioner i `pyproject.toml`, så en frisk installation opfører sig ens.

---

## 4. Arkitektur

Koden er en Python-pakke i `src/` opdelt efter domæne:

```
PostalPrint/
├── src/postalprint/
│   ├── __main__.py             # Opstart: server, eget vindue (Edge app-tilstand), kommandolinje
│   ├── paths.py                # Hvor data ligger (ved siden af .exe eller i projektmappen)
│   ├── addresses/              # Adresser
│   │   ├── validation.py       # Offline-validering (lag 1) + normalisering af felter
│   │   ├── online_check.py     # Online-adressetjek (lag 2) via OpenStreetMap Nominatim
│   │   ├── postcodes.py        # Opslag postnr → by
│   │   └── postnumre.json      # {"8000": "Aarhus C", "8700": "Horsens", ...}
│   ├── labels/                 # Etiketter
│   │   ├── layout.py           # Hvor teksten står (bruges af både PDF og live preview)
│   │   └── pdf.py              # Tegner etiket og kalibreringsside som PDF
│   ├── printing/
│   │   └── printers.py         # Print-tilstande: file | dialog | sumatra
│   ├── storage/
│   │   └── store.py            # Config, historik, etiket-PDF'er, backup. Atomisk skrivning
│   └── web/                    # Brugerflade
│       ├── app.py              # Flask: routes, binder domænerne sammen
│       ├── templates/index.html
│       └── static/             # app.js, style.css
├── tests/                      # Samme opdeling som src/ + conftest.py (fiktive data, netværk slået fra)
├── scripts/
│   ├── build_exe.py            # Bygger PostalPrint.exe + zip med vejledning
│   └── build_postnumre.py      # Bygger postnumre.json fra GeoNames
├── docs/
│   ├── SPEC.md                 # Dette dokument
│   └── images/                 # Screenshots til README (kun fiktive data)
├── .github/workflows/          # tests.yml og release.yml
├── data/                       # ← I .gitignore! Alt med persondata ligger her (afsnit 9)
├── start.bat                   # Start fra kildekoden: installerer første gang og åbner vinduet
├── pyproject.toml              # Pakke, afhængigheder, pytest-opsætning
├── README.md
└── LICENSE                     # MIT
```

**Princip:** `addresses`, `labels`, `printing` og `storage` kender ikke til Flask. De kan testes isoleret og genbruges, fx til en senere WooCommerce-integration. Kun `web` binder dem sammen.

### Dataflow ved print

```
[Formular] --Enter--> POST /api/labels/print
                        ├─ validation.validate()          → fejl? 422 + felt-fejl → UI markerer felter
                        ├─ online_check.check_address()   → advarsel? (kun hvis online-tjek er slået til)
                        ├─ advarsler og ikke force?       → 409 → UI viser advarsler, næste Enter sender force
                        ├─ pdf.render_label()             → PDF-bytes
                        ├─ store.save_label_pdf()         → data/historik/2026/2026-10/<filnavn>.pdf
                        └─ printers.print_pdf()           → SumatraPDF sender til printeren
[UI] viser bekræftelse: "Kom etiketten pænt ud?"
   Enter → POST /api/labels/<id>/confirm → gemmes i historikken → formularen tømmes
   Esc   → POST /api/labels/<id>/reprint → samme PDF printes igen, bekræftelsen bliver stående
```

Etiketten gemmes **først i historikken ved bekræftelse**, for programmet kan ikke se, om papiret satte sig fast.
**PDF'en gemmes derimod allerede før print**, så den findes, selvom printet fejler eller aldrig bekræftes.

---

## 5. Etiketlayout

### Fysiske mål
- **Medie:** 100 × 150 mm. PDF-siden laves **stående 100 × 150 mm**, så den matcher printerdriveren præcist. Så sker der ingen auto-rotation eller skalering.
- **Indhold:** Tegnes **roteret 90°**, så det læses liggende (150 × 100) på kuverten. Rotationsretningen er en indstilling (`rotation: 90 | 270`), fordi printere fører etiketten forskelligt ind.
- **Margin:** 15 mm hele vejen rundt → indholdsfelt **120 × 70 mm** (liggende).
- Intet frimærkefelt.

### Skitse (liggende, som den sidder på kuverten)

```
┌──────────────────────────────────────────────────────┐
│  15 mm                                               │
│     Afsender: Firmanavn · Eksempelvej 1 ·            │  9 pt, normal
│     1234 Eksempelby                                  │
│     ─────────────────────────────────────────────    │  0,75 pt linje
│                                                      │
│     Modtagers Navn                                   │  Fed, stor
│     c/o Testklubben (valgfri)                        │
│     Vejnavn 12, 2. tv                                │
│     8700 Horsens                                     │
│                                                 15 mm│
└──────────────────────────────────────────────────────┘
```

### Typografi
- Font: **Helvetica** og **Helvetica-Bold** (indbygget i PDF, understøtter æøå).
- Afsender: 9 pt (ned til 7 pt ved lange adresser), højst to linjer, foranstillet "Afsender:". Under den en tynd vandret linje.
- Modtager: Helvetica-Bold. **Auto-fit:** start ved 26 pt og formindsk i trin på 1 pt, indtil den længste linje passer i 120 mm bredde og alle linjer passer i højden. Minimum 14 pt.
- Linjeafstand: 1,25 × fontstørrelse.
- Modtagerblokken placeres i bunden af indholdsfeltet, med afsenderen øverst.
- Live preview i brugerfladen bruger præcis det samme layout som PDF'en (`labels/layout.py`), så det, man ser, er det, der printes.

### Beslutning: intet kryds over afsender
Et kryds over en adresse betyder traditionelt **"denne adresse er ugyldig"**, fx på genbrugte kuverter. Postsorteringen kan derfor tolke det som, at returadressen ikke gælder. Afsenderen adskilles i stedet tydeligt ved at:
1. Stå øverst i lille skrift, foranstillet "Afsender:".
2. Være adskilt fra modtageren af en vandret linje.
3. Have markant mindre skrift end modtageren (9 pt mod 14–26 pt fed).

Det følger dao's vejledning, hvor brevmærket sidder øverst til højre og modtageradressen skal være tydelig.

### Kalibreringsetiket
`pdf.render_calibration()` laver en testside med:
- En ramme præcis 15 mm fra kanten.
- Streger for hver 10 mm langs to kanter.
- Teksten "100 × 150 mm – mål med lineal" i samme retning som en rigtig etiket.

Den printes fra Indstillinger og bekræfter, at printeren hverken skalerer eller roterer forkert.

---

## 6. Felter og validering

### Felter (i tab-rækkefølge)

| # | Felt | Påkrævet | Note |
|---|---|---|---|
| 1 | Navn | Ja | 2–60 tegn |
| 2 | Adresse | Ja | Vej + husnummer (+ etage/dør) |
| 3 | Postnummer | Ja | 4 cifre. Udfylder By automatisk |
| 4 | By | Ja | Auto-udfyldt, men kan altid overskrives |
| 5 | Ekstra linje | Nej | c/o, forening osv. Printes mellem navn og adresse. Ligger sidst, så den normalt ikke koster et tab-tryk |

Land er fast "Danmark" og printes ikke på etiketten, da det er indenlandsk post.

### Normalisering (før validering)
- Trim mellemrum i start og slut. Erstat flere mellemrum (og linjeskift) med ét.
- Postnummer: fjern mellemrum og et "DK-"-præfiks, så "8 700" og "DK-8700" bliver "8700".
- Store og små bogstaver ændres ikke automatisk.

### Validering i to lag
Valideringen er delt i to lag, så de basale tjek altid virker, også uden internet.

| Lag | Modul | Kræver internet | Resultat |
|---|---|---|---|
| 1. Offline | `addresses/validation.py` (rene funktioner) | Nej | **Fejl** blokerer print. **Advarsler** kræver ekstra Enter |
| 2. Online | `addresses/online_check.py` | Ja | Kun **advarsler**. Springes stille over uden internet |

### Lag 1 – Fejl (blokerer print)
- Afsenderen er ikke udfyldt i Indstillinger (standardværdierne er tomme, se afsnit 9).
- Påkrævet felt er tomt (navn, adresse, postnummer, by).
- **Navn:** under 2 eller over 60 tegn, eller ingen bogstaver (fx kun tal).
- **Adresse skal være vejnavn + husnummer**, fx "Fiktivvej 12", "Fiktivvej 12B" eller "Fiktivvej 12, 2. tv". Begge dele tjekkes:
  - Intet bogstav → "mangler et vejnavn".
  - Intet tal → "mangler husnummer".
  - Tallet står først, fx "12 Fiktivvej" → "husnummeret skal stå efter vejnavnet".
  - Husnummer 0 → fejl. Husnummer er 1–999 med evt. ét bogstav.
  - Et 4-cifret tal i adressen, fx "Fiktivvej 12, 8700 Horsens" → "postnummeret skal stå i sit eget felt".
- **Postnummer:** ikke præcis 4 cifre, eller findes ikke i `postnumre.json` (fx Grønland og Færøerne).
- **By** indeholder tal (typisk et postnummer skrevet i byfeltet).
- **Tegn der ikke kan printes:** etikettens skrift (Helvetica, Windows-1252) kan ikke vise fx emoji eller polske/tyrkiske bogstaver som "ł" og "Ş". Æ, ø, å, é, ü osv. virker.
- Et felt er for bredt til at kunne være på etiketten, selv ved 14 pt.

### Lag 1 – Advarsler (kræver ekstra Enter for at fortsætte)
- By matcher ikke postnummerets officielle navn, fx "8700 Horsenss".
- Samme navn og adresse er printet inden for de seneste 14 dage (mulig dublet).
- Navnet ligner en adresse (fx "Fiktivvej 12" i navnefeltet).
- Ekstra linje gentager navn eller adresse.

### Lag 2 – Online-adressetjek (advarsler)
- Slår op i **OpenStreetMap Nominatim**. Ingen konto og ingen API-nøgle.
- Sender **kun vejnavn, husnummer og postnummer**, aldrig modtagerens navn, etage eller dør.
- Kører i baggrunden under indtastning (efter 0,7 sek. pause) og viser "✓ Adressen findes" eller en advarsel under felterne. Ved print bruges det gemte resultat, så print ikke bliver langsommere.
- Mulige advarsler:
  - Husnummeret findes ikke på vejen i det postnummer.
  - Adressen findes ikke i det postnummer, men i andre (op til tre vises, fx "findes i 8382 Hinnerup").
  - Adressen blev slet ikke fundet (tjek stavningen).
- Er internettet nede, eller svarer tjenesten ikke inden for 4 sek., springes tjekket over. Det blokerer **aldrig** print. Postbokse springes også over.
- Nominatims brugsregler overholdes: højst 1 opslag pr. sekund, tydelig User-Agent og cache i hukommelsen.
- Kan slås fra under Indstillinger → Adressetjek.
- OpenStreetMap kan mangle helt nye adresser. Derfor er det kun en advarsel.

### Postnummer → by
- `postnumre.json` indlæses én gang i browseren (ca. 30 KB), så opslaget er øjeblikkeligt. Serveren validerer igen.
- JavaScript holder styr på, om byen blev auto-udfyldt:
  - Når postnummeret har 4 cifre og byfeltet er tomt **eller** auto-udfyldt → udfyld byen og spring fokus over byfeltet.
  - Er byen skrevet i hånden → overskrives den aldrig.
- Kilde: **GeoNames** (https://download.geonames.org/export/zip/DK.zip, CC BY 4.0, krediteres i README). DAWA lukkede 1. oktober 2026, og Datafordeleren kræver en API-nøgle. `scripts/build_postnumre.py` henter listen og skriver JSON. Scriptet køres igen, hvis der kommer nye postnumre.

### Indsæt en hel adresse
Indsættes en hel adresse i Navn-feltet (flere linjer, eller én linje med kommaer, fx kopieret fra en ordre), fordeles den automatisk i felterne:
- Linjen "1234 By" → postnummer og by.
- Linjen med vejnavn + husnummer → adresse. En etage/dør på sin egen linje (fx "2. tv") lægges på adressen.
- Første linje → navn. Øvrige linjer → ekstra linje. "Danmark" ignoreres.

---

## 7. Brugerflade

### Visuelt udtryk: Apple-inspireret, enkelt og rent
- Systemfont: `-apple-system, BlinkMacSystemFont, "Segoe UI Variable", "Segoe UI", system-ui, sans-serif`.
- Baggrund `#f5f5f7`, kort i hvidt med `border-radius: 12px` og en meget svag skygge.
- Tekst `#1d1d1f`, sekundær tekst `#6e6e73`, accentfarve `#0071e3`, fejl `#d70015`, advarsel `#b25000`.
- Felter: 44 px høje, 1 px lys grå kant og blå fokusring.
- Én primær knap: "Print" (blå, afrundet).
- Ingen gradienter, ingen ikoner for pyntens skyld og ingen animationer ud over korte fades (150 ms).
- Live forhåndsvisning af etiketten ved siden af formularen, i skala.
- Dark mode via `prefers-color-scheme`.

### Visninger (én HTML-side)
1. **Ny etiket** (standard)
2. **Historik**: liste grupperet pr. måned, søgefelt (navn, adresse, by), knapperne "Print igen" og "Åbn PDF" pr. række, samt "Åbn historikmappe" øverst (åbner `data/historik/` i Stifinder).
3. **Indstillinger**: afsender (postnr. udfylder by), print-tilstand, printer valgt fra en liste over Windows' printere, SumatraPDF-sti (findes automatisk), rotation, online-adressetjek til/fra og knap til kalibreringsetiket.

Første gang programmet startes, åbner det på Indstillinger med en velkomst, indtil afsenderen er udfyldt.

### Tastatur

| Tast | Handling |
|---|---|
| Tab / Shift+Tab | Næste/forrige felt (byfeltet springes over, når det er auto-udfyldt) |
| Enter (i alle felter) | Valider og print |
| Enter (i bekræftelsesboks) | "Ja, den kom pænt ud" → gem, ryd og fokus i Navn |
| Esc (i bekræftelsesboks) | Print igen |
| Esc (i formular) | Ryd formular |
| Ctrl+H | Historik |
| Ctrl+, | Indstillinger |
| Esc (i Historik/Indstillinger) | Tilbage til Ny etiket |

Ctrl+N bruges ikke, fordi browseren ikke lader en side overtage den.

### Fejlvisning
- Fejlfelter får rød kant og en kort tekst under feltet.
- Fokus hopper til **første** fejlfelt.
- Advarsler vises gult med teksten "Tryk Enter igen for at printe alligevel".

---

## 8. Print

`printing/printers.py` har tre tilstande, der vælges i Indstillinger:

| Tilstand | Bruges | Hvad sker der |
|---|---|---|
| `file` | Uden printer (standard) | PDF'en åbnes i standard PDF-viseren |
| `dialog` | Reserve | Browseren åbner PDF'en i en skjult iframe og viser printdialogen |
| `sumatra` | Med labelprinter | `SumatraPDF.exe -print-to "<printer>" -print-settings "noscale" -silent <fil>` |

- SumatraPDF kaldes med `subprocess.run([...], check=True, timeout=30)` og en argumentliste, aldrig en shell-streng.
- SumatraPDF findes automatisk i de typiske installationsmapper. Stien kan også angives i Indstillinger.
- Er der ikke valgt en printer, bruges Windows' standardprinter (`-print-to-default`).
- Fejl (printer offline, printer findes ikke, SumatraPDF ikke fundet, timeout) vises i bekræftelsesboksen med en forklaring og et link til PDF'en, så den kan printes manuelt.
- Midlertidige PDF'er i `data/tmp/` (kalibrering) ryddes ved opstart, hvis de er ældre end 1 dag. Etiket-PDF'er i `data/historik/` ryddes **aldrig** automatisk.

### Manuelt print, hvis noget går galt
Åbn historikmappen (knap i Historik, eller `data\historik\<år>\<år-måned>\` i Stifinder), find PDF'en på dato og navn, og print den fra en PDF-viser med **faktisk størrelse / ingen skalering**.

---

## 9. Lagring

Alt gemmes i mappen `data/`: ved siden af `PostalPrint.exe`, eller i projektmappen, når programmet køres fra kildekoden (`paths.py`). En anden mappe kan vælges med `--data-dir`.

### `data/config.json`
```json
{
  "sender": {
    "name": "",
    "street": "",
    "postcode": "",
    "city": ""
  },
  "print": {
    "mode": "file",
    "printer_name": "",
    "sumatra_path": "",
    "rotation": 90
  },
  "address_check": {
    "online": true
  }
}
```
Oprettes automatisk med disse standardværdier, hvis den mangler. Afsenderen er **tom som standard**, så ingen rigtig adresse står i koden. Den udfyldes første gang i Indstillinger og ligger derefter kun i `data/config.json`. Gamle config-filer får automatisk nye nøgler med standardværdier, når programmet opdateres.

### Historik: én fil og én PDF-mappe pr. måned
```
data/historik/2026/2026-10.json
data/historik/2026/2026-10/        ← PDF'er for oktober
data/historik/2026/2026-11.json
data/historik/2026/2026-11/
```
Månederne navngives med tal, så de sorterer korrekt. Indhold af JSON-filen:
```json
{
  "version": 1,
  "entries": [
    {
      "id": "b3f1c2e0-...",
      "printed_at": "2026-10-28T14:03:12+01:00",
      "recipient": {
        "name": "Test Testesen",
        "extra": "",
        "street": "Fiktivvej 12, 2. tv",
        "postcode": "8700",
        "city": "Horsens"
      },
      "sender": { "name": "Firmanavn", "street": "Eksempelvej 1", "postcode": "1234", "city": "Eksempelby" },
      "pdf_file": "2026/2026-10/2026-10-28_1403_Test Testesen_8700_b3f1c2e0.pdf",
      "reprints": 0
    }
  ]
}
```
Afsenderen gemmes også pr. post, så gamle etiketter kan genskabes præcist, selvom afsenderen senere ændres.
`pdf_file` er relativ til `data/historik/`, så hele `data/` kan flyttes til en anden PC.

### Etiket-PDF'er: én PDF pr. printet etiket
```
data/historik/2026/2026-10/2026-10-28_1403_Test Testesen_8700_b3f1c2e0.pdf
```
- Gemmes **før** print (se dataflow i afsnit 4).
- **Filnavn:** `<dato>_<ttmm>_<navn>_<postnr>_<første 8 tegn af id>.pdf`. Dato og tid først, så filerne sorterer kronologisk. Id'et gør navnet unikt, selvom samme person printes to gange samme minut.
- **Rensning af navnet:** tegn Windows ikke tillader (`< > : " / \ | ? *` og kontroltegn) fjernes, punktum og mellemrum i enden fjernes, og navnet afkortes til 40 tegn. Æ, ø og å beholdes. Bliver navnet tomt, bruges `ukendt`.
- PDF'en skrives atomisk på samme måde som JSON.
- Etiketter, der aldrig bliver bekræftet (fx fordi printeren fejlede), ligger stadig i mappen, men står ikke i historikken. Det er netop dem, der kan blive brug for at printe manuelt.
- **"Print igen" fra historikken** bruger den gemte PDF. Mangler den, genskabes den fra historikken og gemmes igen.

### Sikker skrivning
1. Skriv til `<fil>.tmp` (UTF-8).
2. `flush()` + `os.fsync()`.
3. `os.replace(tmp, fil)`. Det er atomisk på samme drev.

### Backup: løbende, ved hver ændring
Der tages en backup **hver gang historikken ændres**, dvs. ved bekræftelse af et print og ved "Print igen".
1. Efter en vellykket skrivning kopieres månedens JSON-fil til `data/backups/2026-10_2026-10-28T140312.json` (måned + tidsstempel).
2. **Ingen grænse:** programmet sletter aldrig backups. De fylder meget lidt (få KB pr. print) og ryddes manuelt efter behov.
3. Kun JSON-filerne tages med. PDF'erne kan genskabes fra historikken.
4. Gendannelse: kopiér den ønskede backup tilbage til `data/historik/<år>/<år-måned>.json`.

Backuppen ligger på samme disk og beskytter mod programfejl og ødelagte filer, ikke mod en død harddisk. Kopiér `data/` til et andet drev for at være sikker.

---

## 10. API (Flask, kun `127.0.0.1`)

| Metode | Sti | Formål |
|---|---|---|
| GET | `/` | UI |
| GET | `/api/postcodes` | Postnumre til frontend |
| POST | `/api/labels/preview` | Det præcise layout (i mm), som PDF'en vil få. Bruges af live preview |
| POST | `/api/address/check` | Online-adressetjek (lag 2), kaldes i baggrunden under indtastning |
| POST | `/api/labels/print` | Validér, generér, gem PDF og print. Svar 200 `{id, pdf_url, print_error, print_in_browser}`, 409 `{warnings}` eller 422 `{errors}` |
| POST | `/api/labels/<id>/confirm` | Gem i historikken med henvisning til den gemte PDF |
| POST | `/api/labels/<id>/reprint` | Print samme PDF igen |
| POST | `/api/labels/<id>/cancel` | Gem ikke i historikken. PDF'en bliver liggende |
| GET | `/api/labels/<id>/pdf` | Vis PDF'en for en ventende eller gemt etiket (genskabes, hvis den mangler) |
| GET | `/api/history?q=` | Søg i historikken (nyeste først, alle ord skal matche) |
| POST | `/api/history/<id>/reprint` | Print den gemte PDF igen og tæl `reprints` op |
| POST | `/api/history/folder/open` | Åbn `data/historik/` i Stifinder |
| GET/PUT | `/api/config` | Læs/gem indstillinger. PUT svarer 422 `{errors: {"sender.name": ...}}` ved fejl |
| GET | `/api/printers` | Windows' printere til listen i Indstillinger |
| POST | `/api/calibration/print` | Print kalibreringsetiket |
| GET | `/api/calibration/pdf` | Vis kalibrerings-PDF'en |

`print` sender `force: true`, når advarsler er bekræftet med ekstra Enter.

---

## 11. Installation og distribution

### Til brugere: færdig `.exe`
- `PostalPrint.exe` udgives under **Releases** på GitHub. Python er indbygget, så intet skal installeres.
- Den bygges automatisk af GitHub Actions (`.github/workflows/release.yml`), når et version-tag pushes (`git tag v1.0.0`, `git push origin v1.0.0`). Testene køres først. Releasen får både `PostalPrint.exe` og `PostalPrint-windows.zip` (exe + dansk vejledning).
- Data gemmes i `data/` ved siden af `.exe`'en.
- `.exe`'en er ikke kodesigneret, så Windows SmartScreen kan advare første gang ("Flere oplysninger" → "Kør alligevel").
- `.exe`-filen committes ikke i git. Binære filer gør repoet tungt og kan ikke diffes, og Releases er GitHubs sted til færdige programmer.

### Fra kildekoden: `start.bat`
Første gang opretter den et virtuelt miljø, installerer programmet (`pip install -e .`) og laver genvejen "PostalPrint" på skrivebordet. Derefter starter den programmet med `python -m postalprint`, som åbner det i sit eget vindue (Edge app-tilstand) på `http://127.0.0.1:5050`. Kører programmet allerede, åbnes kun vinduet. Ændres `pyproject.toml` (fx efter `git pull`), installeres afhængighederne igen automatisk.

### Udvikling
```
python -m venv .venv
.venv\Scripts\pip install -e .[dev]
.venv\Scripts\python -m postalprint --debug       # auto-genstart; --data-dir <mappe> bruger testdata
.venv\Scripts\pytest                              # alle tests
.venv\Scripts\python -m postalprint.labels.pdf    # eksempel-PDF'er uden Flask og printer
.venv\Scripts\python scripts\build_exe.py         # byg PostalPrint.exe lokalt
```
GitHub Actions kører testene på Windows ved hvert push og pull request (`.github/workflows/tests.yml`).

---

## 12. Opsætning af labelprinteren

1. Installer SumatraPDF (gratis).
2. I printerdriverens egenskaber: sæt papirstørrelsen til **100 × 150 mm** (opret en brugerdefineret størrelse, hvis den mangler), stående, og skalering 100 %/ingen.
3. I Indstillinger: udfyld afsender, vælg "Direkte til labelprinteren", og vælg printeren på listen.
4. Tryk "Print kalibreringsetiket" og mål med en lineal. Rammen skal være 15 mm fra kanten, og 10 mm-stregerne skal passe.
5. Står teksten på hovedet eller forkert vej: skift rotation mellem 90° og 270°, og print kalibreringen igen.

---

## 13. Privatliv og GDPR

Programmet behandler modtageres navne og adresser. Det er bygget, så de aldrig forlader computeren, og så det offentlige repo aldrig indeholder persondata.

### I programmet
- **Alle persondata ligger i `data/`**: historik, etiket-PDF'er, backups og afsenderens adresse. Intet gemmes andre steder.
- Serveren lytter kun på `127.0.0.1` og kan ikke nås fra andre computere.
- Request-logs er slået fra (uden for `--debug`), fordi søgninger i historikken kan indeholde navne.
- PDF-metadata indeholder ingen navne eller adresser.
- Det valgfri online-adressetjek sender kun vejnavn, husnummer og postnummer til OpenStreetMap, aldrig navnet. Det kan slås fra.
- Ingen analytics, ingen cookies, ingen eksterne scripts eller fonte i brugerfladen.
- Historik og backups slettes kun manuelt. Den, der bruger programmet, er dataansvarlig for modtagernes oplysninger og bør slette gamle data, når de ikke længere er nødvendige.

### I repoet
- `data/` står i `.gitignore`, ligesom `*.pdf`, `*.log`, `.env` og build-output.
- Afsenderen i standard-config er tom, så ingen rigtig adresse står i koden.
- Tests, eksempler, README, screenshots og dette dokument bruger kun fiktive data, fx "Test Testesen, Fiktivvej 12" og "Firmanavn, Eksempelvej 1, 1234 Eksempelby". Tests skriver altid til pytests `tmp_path` og slår netværket fra.
- Hemmeligheder (fx fremtidige API-nøgler) hører hjemme i `.env`, som ikke committes.
- `postnumre.json` er offentlige data fra GeoNames (CC BY 4.0) og krediteres i README.

---

## 14. Fremtid (ikke version 1)

- Datafordeleren (DAR) som alternativ kilde til adressetjek og autocomplete af vejnavne. `online_check.py` er bygget, så en ny kilde kan skiftes ind med samme returtype.
- WooCommerce: vælg en ordre og hent adressen automatisk via WooCommerce REST API (nøgler i en lokal `.env`).
- Eksport af historik til CSV.
- Knap i Indstillinger, der sletter historik og etiket-PDF'er ældre end X år.

---

## 15. Kilder

- dao: brevmærke i øverste højre hjørne, tydelig modtageradresse — https://dao.as/saadan-sender-du-breve/
- DAWA lukket 1. oktober 2026 — https://community.openstreetmap.org/t/dawa-adresse-api-lukker-den-1-oktober-2026-hvad-med-autoaws/148055
- Postnumre: GeoNames (CC BY 4.0) — https://download.geonames.org/export/zip/
- Online-adressetjek: OpenStreetMap Nominatim, brugsregler — https://operations.osmfoundation.org/policies/nominatim/
