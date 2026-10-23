"""GAEB DA XML 3.3: write a BoQ (X83 tender, X84 bid) and read one back.

Covers the subset this project exchanges: project info, BoQ categories (Titel), items with ordinal
number, quantity, unit, unit price and total, short and long text, and bidder text complements
(Bieterangaben, e.g. the offered product). Unknown elements are ignored when reading.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from xml.sax.saxutils import escape

from lxml import etree

NS_TMPL = "http://www.gaeb.de/GAEB_DA_XML/DA{dp}/3.3"


@dataclass
class GaebItem:
    oz: str
    short: str
    long: str
    qty: float | None
    unit: str
    up: float | None = None
    it: float | None = None
    bidder_texts: dict[str, str] = field(default_factory=dict)
    line: int = 0  # source line in the XML file, for evidence links


@dataclass
class GaebDoc:
    dp: int  # data phase: 83 = tender, 84 = bid
    project: str
    boq_label: str
    boq_date: str
    company: str | None
    categories: dict[str, str]
    items: list[GaebItem]


def _p(text: str) -> str:
    return f"<p><span>{escape(text)}</span></p>"


def write(dp: int, project: str, boq_label: str, boq_date: str, categories: dict[str, str], items: list[GaebItem], company: str | None = None) -> str:
    by_cat: dict[str, list[GaebItem]] = {}
    for it in items:
        by_cat.setdefault(it.oz.split(".")[0], []).append(it)
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<GAEB xmlns="{NS_TMPL.format(dp=dp)}">',
        "<GAEBInfo><Version>3.3</Version><VersDate>2021-05</VersDate><ProgSystem>ble-sim</ProgSystem></GAEBInfo>",
        f"<PrjInfo><NamePrj>{escape(project)}</NamePrj><LblPrj>{escape(project)}</LblPrj><Cur>EUR</Cur><CurLbl>Euro</CurLbl></PrjInfo>",
        f"<Award><DP>{dp}</DP><AwardInfo><Cur>EUR</Cur></AwardInfo>",
    ]
    if company:
        out.append(f"<CTR><Address><Name1>{escape(company)}</Name1></Address></CTR>")
    out.append(
        f'<BoQ ID="BoQ1"><BoQInfo><Name>LV</Name><LblBoQ>{escape(boq_label)}</LblBoQ><Date>{boq_date}</Date>'
        "<BoQBkdn><Type>BoQLevel</Type><Length>2</Length><Num>Yes</Num></BoQBkdn>"
        "<BoQBkdn><Type>Item</Type><Length>4</Length><Num>Yes</Num></BoQBkdn></BoQInfo><BoQBody>"
    )
    for cat in sorted(by_cat):
        out.append(f'<BoQCtgy RNoPart="{cat}"><LblTx>{_p(categories.get(cat, cat))}</LblTx><BoQBody><Itemlist>')
        for it in by_cat[cat]:
            out.append(f'<Item RNoPart="{it.oz.split(".")[1]}">')
            if it.qty is not None:
                out.append(f"<Qty>{it.qty:.3f}</Qty>")
            out.append(f"<QU>{escape(it.unit)}</QU>")
            if it.up is not None:
                out.append(f"<UP>{it.up:.2f}</UP>")
            if it.it is not None:
                out.append(f"<IT>{it.it:.2f}</IT>")
            comp = "".join(
                f'<TextComplement Kind="Bidder" MarkLbl="{escape(k)}"><ComplBody><span>{escape(v)}</span></ComplBody></TextComplement>'
                for k, v in it.bidder_texts.items()
            )
            out.append(
                f"<Description><CompleteText><DetailTxt><Text>{_p(it.long)}</Text>{comp}</DetailTxt>"
                f"<OutlineText><OutlTxt><TextOutlTxt>{_p(it.short)}</TextOutlTxt></OutlTxt></OutlineText></CompleteText></Description>"
            )
            out.append("</Item>")
        out.append("</Itemlist></BoQBody></BoQCtgy>")
    out.append("</BoQBody></BoQ></Award></GAEB>")
    return "\n".join(out) + "\n"


def _text(el: etree._Element | None) -> str:
    if el is None:
        return ""
    return " ".join(" ".join(el.itertext()).split())


def _num(el: etree._Element | None) -> float | None:
    if el is None or not (el.text or "").strip():
        return None
    return float(el.text.strip())


def read(data: bytes) -> GaebDoc:
    root = etree.fromstring(data, parser=etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False))
    ns = root.nsmap.get(None, "")
    q = (lambda tag: f"{{{ns}}}{tag}") if ns else (lambda tag: tag)
    dp_el = root.find(f"{q('Award')}/{q('DP')}")
    dp = int(dp_el.text) if dp_el is not None and dp_el.text else 0
    project = _text(root.find(f"{q('PrjInfo')}/{q('NamePrj')}"))
    info = root.find(f".//{q('BoQInfo')}")
    label = _text(info.find(q("LblBoQ"))) if info is not None else ""
    date = _text(info.find(q("Date"))) if info is not None else ""
    company = _text(root.find(f".//{q('CTR')}//{q('Name1')}")) or None
    cats: dict[str, str] = {}
    items: list[GaebItem] = []
    for cat in root.iter(q("BoQCtgy")):
        rn = cat.get("RNoPart", "")
        cats[rn] = _text(cat.find(q("LblTx")))
        for item in cat.iter(q("Item")):
            ct = item.find(f"{q('Description')}/{q('CompleteText')}")
            long_el = ct.find(f"{q('DetailTxt')}/{q('Text')}") if ct is not None else None
            short_el = ct.find(f".//{q('TextOutlTxt')}") if ct is not None else None
            bidder = {c.get("MarkLbl", "Bieterangabe"): _text(c.find(q("ComplBody"))) for c in item.iter(q("TextComplement")) if c.get("Kind") == "Bidder"}
            items.append(
                GaebItem(
                    oz=f"{rn}.{item.get('RNoPart', '')}",
                    short=_text(short_el),
                    long=_text(long_el),
                    qty=_num(item.find(q("Qty"))),
                    unit=_text(item.find(q("QU"))),
                    up=_num(item.find(q("UP"))),
                    it=_num(item.find(q("IT"))),
                    bidder_texts=bidder,
                    line=item.sourceline or 0,
                )
            )
    return GaebDoc(dp, project, label, date, company, cats, items)
