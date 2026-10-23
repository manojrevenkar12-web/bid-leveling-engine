# Held-out set v1: first run

Run once on 2026-10-23 21:10:50. The bids were written as scripts by an agent that read only `heldout/WRITING_BIDS.md` and the
BoQs, never the engine, and rendered into the documents bidders send. This file is not regenerated; later runs go to
`latest.json`. If the engine is changed after studying these results, this set becomes a regression set and a new one is written.

**Findings: precision 23.6%, recall 75.6%** (34 found, 110 false, 11 missed).

| Deviation | Found | False | Missed |
|---|---|---|---|
| Arithmetic error (EP × qty ≠ total) | 2 | 0 | 1 |
| Position added | 3 | 41 | 0 |
| Priced as included | 2 | 0 | 1 |
| Position not priced | 3 | 69 | 0 |
| Missing price | 3 | 0 | 0 |
| Priced an outdated BoQ version | 2 | 0 | 0 |
| Unit price outlier | 2 | 0 | 1 |
| Other product than reference | 4 | 0 | 0 |
| Quantity changed | 2 | 0 | 1 |
| Reservation in cover letter | 6 | 0 | 5 |
| Long text changed (spec) | 3 | 0 | 0 |
| Speculative (unbalanced) pricing | 1 | 0 | 1 |
| Unit changed | 1 | 0 | 1 |

| Route | Lines | Matched correctly | By position number alone |
|---|---|---|---|
| gaeb | 87 | 100.0% | 100.0% |
| pdf_text | 121 | 94.2% | 50.4% |
| xlsx | 59 | 66.1% | 50.8% |
| ocr | 31 | 54.8% | 0.0% |

BoQ version identified: 11 of 11 bids.

| Search | Queries | Hit@1 | Hit@3 |
|---|---|---|---|
| plain | 20 | 75.0% | 90.0% |
| construction | 20 | 90.0% | 95.0% |

## Missed

- H91-B4 (ocr): speculative_pricing  – Aushub, Wasserhaltung, Z2-Entsorgung, Betonstahl und Schlitze ca. +48 %, Rest ca. -10 %
- H91-B4 (ocr): price_outlier 04.0030 – EP 6,80 EUR/St, marktüblich ca. 65-70 EUR
- H91-B5 (pdf_text): reservation  – liability: Haftung für Folgeschäden auf Auftragssumme begrenzt
- H92-B1 (gaeb): reservation  – validity: Angebot nur bis 15.11.2026 gültig
- H92-B2 (pdf_text): reservation  – escalation: Preisgleitung Zement/Estrich bei Auftrag nach 31.12.2026
- H92-B3 (xlsx): qty_changed 08.0010 – 3824 -> 3284
- H92-B3 (xlsx): unit_changed 03.0060 – m -> St
- H92-B3 (xlsx): included_price 06.0050 – als enthalten angegeben
- H92-B3 (xlsx): arithmetic_error 05.0010 – GP mit 877 statt 887 m2 gerechnet
- H92-B4 (ocr): reservation  – payment: Abschläge binnen 10 Tagen ohne Abzug
- H92-B5 (pdf_text): reservation  – schedule: Fristen nur bei Zuschlag bis 15.12.2026

## False findings

- H91-B2 (pdf_text): extra_position  – Added position not in the BoQ: “Stb.-Decke Ortbeton”.
- H91-B2 (pdf_text): missing_position 03.0050 – 03.0050 “Stahlbetondecke als Ortbetondecke herstellen” is not in the bid.
- H91-B4 (ocr): extra_position  – Added position not in the BoQ: “Z2-Material entsorgen”.
- H91-B4 (ocr): extra_position  – Added position not in the BoQ: “Rechteckstütze”.
- H91-B4 (ocr): extra_position  – Added position not in the BoQ: “Stürze”.
- H91-B4 (ocr): extra_position  – Added position not in the BoQ: “Schlitze”.
- H91-B4 (ocr): extra_position  – Added position not in the BoQ: “Hohlkehlen”.
- H91-B4 (ocr): extra_position  – Added position not in the BoQ: “Innentüren”.
- H91-B4 (ocr): extra_position  – Added position not in the BoQ: “Brandschutztüren”.
- H91-B4 (ocr): extra_position  – Added position not in the BoQ: “Fensterbänke innen”.
- H91-B4 (ocr): missing_position 02.0010 – 02.0010 “Oberboden abtragen und seitlich lagern” is not in the bid.
- H91-B4 (ocr): missing_position 02.0020 – 02.0020 “Baugrube ausheben, Boden laden und abfahren” is not in the bid.
- H91-B4 (ocr): missing_position 02.0030 – 02.0030 “Arbeitsraum verfüllen und verdichten” is not in the bid.
- H91-B4 (ocr): missing_position 02.0040 – 02.0040 “Schottertragschicht 0/32 herstellen” is not in the bid.
- H91-B4 (ocr): missing_position 02.0060 – 02.0060 “Belasteten Boden Z2 entsorgen” is not in the bid.
- H91-B4 (ocr): missing_position 03.0010 – 03.0010 “Sauberkeitsschicht aus Beton C8/10” is not in the bid.
- H91-B4 (ocr): missing_position 03.0020 – 03.0020 “Bodenplatte aus Stahlbeton herstellen” is not in the bid.
- H91-B4 (ocr): missing_position 03.0030 – 03.0030 “Stahlbetonwand außen herstellen” is not in the bid.
- H91-B4 (ocr): missing_position 03.0040 – 03.0040 “Stahlbetonwand innen herstellen” is not in the bid.
- H91-B4 (ocr): missing_position 03.0050 – 03.0050 “Stahlbetondecke als Ortbetondecke herstellen” is not in the bid.
- H91-B4 (ocr): missing_position 03.0060 – 03.0060 “Stahlbetonstütze rechteckig herstellen” is not in the bid.
- H91-B4 (ocr): missing_position 04.0010 – 04.0010 “Kalksandstein-Innenwand mauern” is not in the bid.
- H91-B4 (ocr): missing_position 04.0020 – 04.0020 “Ziegelmauerwerk außen, wärmedämmend” is not in the bid.
- H91-B4 (ocr): missing_position 04.0030 – 04.0030 “Fertigteilsturz einbauen” is not in the bid.
- H91-B4 (ocr): missing_position 04.0040 – 04.0040 “Schlitze in Mauerwerk herstellen” is not in the bid.
- H91-B4 (ocr): missing_position 04.0050 – 04.0050 “Brandwand aus Kalksandstein mauern” is not in the bid.
- H91-B4 (ocr): missing_position 09.0010 – 09.0010 “Bauwerksabdichtung mit Bitumenbahnen” is not in the bid.
- H91-B4 (ocr): missing_position 09.0020 – 09.0020 “Perimeterdämmung aus XPS verlegen” is not in the bid.
- H91-B4 (ocr): missing_position 09.0030 – 09.0030 “Flachdachabdichtung mit Kunststoffbahn” is not in the bid.
- H91-B4 (ocr): missing_position 09.0040 – 09.0040 “Gefälledämmung Flachdach verlegen” is not in the bid.
- H91-B4 (ocr): missing_position 09.0050 – 09.0050 “Hohlkehle und Anschluss abdichten” is not in the bid.
- H91-B4 (ocr): missing_position 10.0010 – 10.0010 “Innentür mit Stahlzarge liefern und montieren” is not in the bid.
- H91-B4 (ocr): missing_position 10.0020 – 10.0020 “Brandschutztür T30 liefern und montieren” is not in the bid.
- H91-B4 (ocr): missing_position 10.0030 – 10.0030 “Innenfensterbank aus Holzwerkstoff” is not in the bid.
- H92-B2 (pdf_text): extra_position  – Added position not in the BoQ: “Decke Ortbeton REI 90”.
- H92-B2 (pdf_text): extra_position  – Added position not in the BoQ: “Stütze Stb. 30/30”.
- H92-B2 (pdf_text): extra_position  – Added position not in the BoQ: “Treppenlauf FT”.
- H92-B2 (pdf_text): extra_position  – Added position not in the BoQ: “GK-Unterdecke abgeh.”.
- H92-B2 (pdf_text): extra_position  – Added position not in the BoQ: “Dispersion Wand 2x”.
- H92-B2 (pdf_text): extra_position  – Added position not in the BoQ: “Deckenanstrich”.
- H92-B2 (pdf_text): missing_position 03.0050 – 03.0050 “Stahlbetondecke als Ortbetondecke herstellen” is not in the bid.
- H92-B2 (pdf_text): missing_position 03.0060 – 03.0060 “Stahlbetonstütze rechteckig herstellen” is not in the bid.
- H92-B2 (pdf_text): missing_position 03.0080 – 03.0080 “Fertigteiltreppe einbauen” is not in the bid.
- H92-B2 (pdf_text): missing_position 05.0030 – 05.0030 “Abgehängte Gipskartondecke herstellen” is not in the bid.
- H92-B2 (pdf_text): missing_position 08.0010 – 08.0010 “Dispersionsanstrich auf Wänden” is not in the bid.
- H92-B2 (pdf_text): missing_position 08.0030 – 08.0030 “Deckenflächen streichen” is not in the bid.
- H92-B3 (xlsx): extra_position  – Added position not in the BoQ: “BP C30/37 XC2 30cm”.
- H92-B3 (xlsx): extra_position  – Added position not in the BoQ: “AW STB 25cm glatt”.
- H92-B3 (xlsx): extra_position  – Added position not in the BoQ: “IW STB 20cm SB2”.
- H92-B3 (xlsx): extra_position  – Added position not in the BoQ: “DE STB 24cm REI90”.
- H92-B3 (xlsx): extra_position  – Added position not in the BoQ: “STÜ 30x30 C35/45”.
- H92-B3 (xlsx): extra_position  – Added position not in the BoQ: “FT-Treppe”.
- H92-B3 (xlsx): extra_position  – Added position not in the BoQ: “MSW CW75 2x GKB”.
- H92-B3 (xlsx): extra_position  – Added position not in the BoQ: “Akustik-UD gelocht”.
- H92-B3 (xlsx): extra_position  – Added position not in the BoQ: “VSS CW50 GKBI”.
- H92-B3 (xlsx): extra_position  – Added position not in the BoQ: “Revi-Klappe 60x60”.
- H92-B3 (xlsx): extra_position  – Added position not in the BoQ: “ZE CT-C25-F4 55mm”.
- H92-B3 (xlsx): extra_position  – Added position not in the BoQ: “HE CT-C30-F5”.
- H92-B3 (xlsx): extra_position  – Added position not in the BoQ: “TSD MW 30mm”.
- H92-B3 (xlsx): extra_position  – Added position not in the BoQ: “RDS PE 100mm”.

## Search queries not answered in the top 3

- Mutterboden abschieben
