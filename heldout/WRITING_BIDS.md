# Writing held-out bids

A held-out set is a handful of bids written by someone who has not seen the engine, so the engine
is tested on wording, numbering and mistakes it was never tuned on. You write each bid as a YAML
"bid script"; the project renders it into the document the bidder would send (a GAEB file, a PDF
from estimating software, a spreadsheet, or a printed and scanned PDF). You also write the answer
key: every deviation you put into the bid.

## What you get

`heldout/<set>/tenders/<tender>/LV_v1.md` (and `LV_v2.md` when the client issued an addendum): the
bill of quantities (Leistungsverzeichnis) with ordinal numbers (OZ), short texts, quantities, units
and long texts. These are what the bidders price.

## What you write

One file per bid: `heldout/<set>/bids/<tender>/<bid-id>.yaml`, bid ids `<tender>-B1`, `-B2`, ...

```yaml
company: Bauunternehmung Beispiel GmbH        # any realistic German company name
format: pdf            # gaeb | pdf | xlsx | scan
priced_version: v2     # the BoQ version this bidder priced (v1 if they missed the addendum)
include_long_text: false   # pdf/scan only: print the long text under each line
letter:                # the cover letter, sentence by sentence, in German, in your own words
  - "Sehr gerne bieten wir Ihnen die ausgeschriebenen Leistungen wie folgt an."
  - "..."
lines:                 # in the order the bidder prints them
  - shown_no: "03.0010"     # what the bidder prints as position number: the OZ, their own numbering, or ""
    prices_oz: "03.0010"    # the BoQ position this line prices (answer key); null for a line the BoQ does not have
    short: "Sauberkeitsschicht C8/10"   # the bidder's short text: copy, shorten, abbreviate as estimators do
    long: null              # only if include_long_text (or format gaeb): the long text as the bidder prints it
    qty: 288                # the quantity the bidder prints
    unit: m2
    ep: 14.20               # unit price in EUR; null = left blank
    gp: 4089.60             # total in EUR; normally ep x qty, null = left blank
    included: false         # true = "enthalten" instead of a price
    product: null           # offered product (Bieterangabe) for positions that name a Leitfabrikat
deviations:            # the answer key: everything in this bid the client should be told about
  - {type: qty_changed, oz: "03.0040", detail: "1024 -> 980"}
```

Deviation types (use exactly these):

| type | meaning | oz |
|---|---|---|
| missing_price | a position with no price (ep and gp blank) | the position |
| included_price | priced as "enthalten" / 0 | the position |
| arithmetic_error | gp is not ep x qty | the position |
| qty_changed | the bidder printed a different quantity than the BoQ version they priced | the position |
| unit_changed | a different unit than the BoQ | the position |
| missing_position | a BoQ position the bid leaves out entirely | the position |
| extra_position | a line the BoQ does not contain | null (put the short text in detail) |
| spec_downgrade | the long text was changed to a weaker specification (thinner, lower class, lower fire rating ...) | the position |
| product_alternative | a different product than the Leitfabrikat is offered | the position |
| price_outlier | a unit price wildly off the market (roughly 3x or a quarter of a normal price) | the position |
| speculative_pricing | margin loaded onto positions whose quantities usually grow (earthworks, dewatering, disposal, reinforcement, slots) and taken off the rest | null |
| outdated_version | priced v1 although v2 was issued | null |
| reservation | a cover-letter sentence that qualifies the price or terms (validity, escalation, exclusions, payment, schedule, liability) | null (put the kind in detail) |

Guidelines: make most bids mostly correct, as real bids are; vary the format, numbering and
abbreviations; write cover letters with both ordinary sentences and reservations phrased your own
way; prices should be plausible for German construction in 2026. Do not read anything in this
repository except this file and the `LV_*.md` files of your set.

Also write `heldout/<set>/search_queries.yaml`: 15 to 25 queries an estimator might type to find a
position in these BoQs, each with the OZ of the right answers:

```yaml
queries:
  - {tender: H91, q: "Stahlbetondecke", expect: ["03.0050"]}
```

## Writing the tenders too (set v2 onwards)

From set v2 the tenders are written blind as well. For each tender write
`heldout/<set>/tenders/<tender>/LV_v1.yaml` (and `LV_v2.yaml` for an addendum: the client's revised
BoQ, with some quantities changed, a position added or removed, or a long text changed):

```yaml
project: Neubau Feuerwehrgerätehaus Musterstadt
date: 2026-10-01                # issue date of this version
label: LV Rohbau v1
trades: {"01": Baustelleneinrichtung, "02": Erdarbeiten}   # Titel number -> name
positions:
  - {oz: "02.0010", short: "Oberboden abtragen", long: "Oberboden ... lagern.", qty: 850, unit: m2}
```

Position numbers are `TT.PPPP` (Titel, position). Units: m, m2, m3, St, psch, t, kg, h. Write
the short and long texts the way a German planner writes an LV, with specification details
(classes, thicknesses, fire ratings, reference products as "Leitfabrikat: X oder gleichwertig").
The project renders the GAEB file from this; bids are then written against it as above.
