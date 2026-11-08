#!/usr/bin/env python3
"""Rassegna stampa automatica.

Legge i temi da temi.toml, cerca gli articoli delle ultime ore su Google News
e scrive una pagina HTML in docs/ (pubblicata con GitHub Pages), più una copia
nell'archivio. Usa solo la libreria standard di Python (3.11+).

Uso:
    python3 rassegna.py              # report di oggi
    python3 rassegna.py --temi altro.toml
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import tomllib
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROMA = ZoneInfo("Europe/Rome")
QUI = Path(__file__).resolve().parent
DOCS = QUI / "docs"
DATI = QUI / "dati"

MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
        "agosto", "settembre", "ottobre", "novembre", "dicembre"]
GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]


# ---------------------------------------------------------------- raccolta

def url_google_news(query: str, ore: int, lingua: str, paese: str) -> str:
    q = f"{query} when:{ore}h"
    params = {"q": q, "hl": lingua, "gl": paese, "ceid": f"{paese}:{lingua}"}
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode(params)


def scarica(url: str, tentativi: int = 3) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (rassegna-stampa)"})
    for i in range(tentativi):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except Exception as e:  # rete instabile: riprova
            if i == tentativi - 1:
                raise
            print(f"  errore ({e}), riprovo…", file=sys.stderr)
            time.sleep(3 * (i + 1))
    return b""


def normalizza(titolo: str) -> str:
    t = titolo.lower()
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def dominio(url: str) -> str:
    host = urllib.parse.urlparse(url).hostname or ""
    return host.lower().removeprefix("www.")


def appartiene(host: str, domini: list[str]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domini)


def leggi_feed(query: str, ore: int, imp: dict) -> list[dict]:
    url = url_google_news(query, ore, imp["lingua"], imp["paese"])
    radice = ET.fromstring(scarica(url))
    voci = []
    for item in radice.iter("item"):
        titolo = (item.findtext("title") or "").strip()
        fonte_el = item.find("source")
        fonte = (fonte_el.text or "").strip() if fonte_el is not None else ""
        host = dominio(fonte_el.get("url", "")) if fonte_el is not None else ""
        # Google News aggiunge " - Nome testata" alla fine del titolo
        if fonte and titolo.endswith(" - " + fonte):
            titolo = titolo[: -len(fonte) - 3].strip()
        try:
            quando = parsedate_to_datetime(item.findtext("pubDate") or "")
        except (TypeError, ValueError):
            continue
        voci.append({"titolo": titolo, "fonte": fonte, "dominio": host,
                     "link": (item.findtext("link") or "").strip(), "quando": quando})
    time.sleep(1)  # gentilezza verso Google News
    return voci


def contiene(testo: str, parole: list[str]) -> bool:
    """Vero se una delle parole compare nel testo come inizio di parola
    ("aten" trova "atenei", ma "cia" non trova "denuncia")."""
    return any(re.search(r"(?<!\w)" + re.escape(p), testo) for p in parole)


def cerca(tema: dict, imp: dict) -> list[dict]:
    """Articoli del tema, divisi in gruppi di fonti (giornali, stampa specializzata).

    Google News ignora il limite di tempo quando una ricerca combina parole e
    un elenco di siti, e restituisce al massimo 100 risultati ordinati per
    pertinenza: così gli articoli del giorno restano fuori. Per questo:
    - per i giornali si usa la ricerca del tema, filtrando poi per dominio,
      più una ricerca del tema ristretta ai siti, per non perdere nulla;
    - per la stampa specializzata si prende tutto quello che i siti hanno
      pubblicato nelle ultime ore (pochi siti per volta) e si filtra per
      parole nel titolo.
    """
    ore = tema.get("ore", imp["ore"])
    da = datetime.now(timezone.utc) - timedelta(hours=ore)
    escludi = [p.lower() for p in tema.get("escludi", [])]
    parole = [p.lower() for p in tema.get("parole", [])]
    fonti_escluse = [f.lower() for f in imp.get("fonti_escluse", [])]
    autorevoli = imp.get("fonti_autorevoli", [])
    specialistiche = tema.get("fonti_specialistiche", [])

    generale = leggi_feed(tema["query"], ore, imp)
    gruppi: list[tuple[str, list[dict]]] = []
    if autorevoli:
        cand = list(generale)
        for i in range(0, len(autorevoli), 15):
            siti = " OR ".join("site:" + d for d in autorevoli[i:i + 15])
            cand += leggi_feed(f"({tema['query']}) ({siti})", ore, imp)
        gruppi.append(("Giornali", [c for c in cand if appartiene(c["dominio"], autorevoli)]))
    if specialistiche:
        cand = list(generale)
        for i in range(0, len(specialistiche), 5):
            cand += leggi_feed(" OR ".join("site:" + d for d in specialistiche[i:i + 5]), ore, imp)
        gruppi.append(("Stampa specializzata",
                       [c for c in cand if appartiene(c["dominio"], specialistiche)]))
    if not gruppi:  # nessun elenco di fonti: si prende tutto
        gruppi = [("", generale)]

    risultato, visti = [], set()
    for gruppo, candidati in gruppi:
        candidati.sort(key=lambda c: c["quando"], reverse=True)
        per_fonte: dict[str, int] = {}
        scelti = []
        for c in candidati:
            t = c["titolo"].lower()
            chiave = normalizza(c["titolo"])
            if (c["quando"] < da or len(chiave) < 20 or chiave in visti
                    or chiave == normalizza(c["fonte"])
                    or (parole and not contiene(t, parole))
                    or contiene(t, escludi)
                    or any(f in c["fonte"].lower() or f in c["dominio"] for f in fonti_escluse)):
                continue
            if per_fonte.get(c["fonte"], 0) >= imp["max_per_fonte"]:
                continue
            visti.add(chiave)
            per_fonte[c["fonte"]] = per_fonte.get(c["fonte"], 0) + 1
            scelti.append({**c, "quando": c["quando"].astimezone(ROMA).isoformat(), "gruppo": gruppo})
            if len(scelti) >= imp["max_articoli"]:
                break
        risultato += scelti
    return risultato


def titoli_precedenti(oggi: str, giorni: int = 7) -> set[str]:
    """Titoli già usciti nei report dei giorni prima, per non ripeterli."""
    if not DATI.exists():
        return set()
    file = sorted(f for f in DATI.glob("*.json") if f.stem < oggi)[-giorni:]
    visti = set()
    for f in file:
        dati = json.loads(f.read_text(encoding="utf-8"))
        visti |= {normalizza(a["titolo"]) for t in dati["temi"] for a in t["articoli"]}
    return visti


# ---------------------------------------------------------------- pagina

def data_estesa(d: datetime) -> str:
    return f"{GIORNI[d.weekday()]} {d.day} {MESI[d.month - 1]} {d.year}"


CSS = """
:root{--sfondo:#fff;--testo:#1a1a1a;--tenue:#6b6b6b;--riga:#e4e4e4;--accento:#17B4D4;--chip:#f2f8fa}
@media (prefers-color-scheme:dark){:root{--sfondo:#141618;--testo:#ececec;--tenue:#9a9a9a;--riga:#2c3034;--accento:#3cc6e2;--chip:#1d2428}}
*{box-sizing:border-box}
body{margin:0;background:var(--sfondo);color:var(--testo);font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
main{max-width:760px;margin:0 auto;padding:28px 16px 64px}
header{border-bottom:3px solid var(--accento);padding-bottom:14px;margin-bottom:18px}
h1{font-family:Georgia,"Times New Roman",serif;font-size:2rem;line-height:1.15;margin:0 0 4px}
.data{color:var(--tenue);margin:0}
nav{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 28px}
nav a{background:var(--chip);color:var(--testo);text-decoration:none;border-radius:999px;padding:4px 12px;font-size:.9rem}
nav a span{color:var(--accento);font-weight:600;margin-left:4px}
section{margin-bottom:36px}
h2{font-family:Georgia,"Times New Roman",serif;font-size:1.45rem;margin:0 0 6px;scroll-margin-top:12px}
h2 small{font-family:inherit;font-size:.85rem;color:var(--tenue);font-weight:normal;margin-left:6px}
h3{font-size:.8rem;text-transform:uppercase;letter-spacing:.06em;color:var(--accento);margin:18px 0 0}
ul{list-style:none;margin:0;padding:0}
li{padding:10px 0;border-bottom:1px solid var(--riga)}
li a{color:var(--testo);text-decoration:none;font-weight:600}
li a:hover{color:var(--accento)}
.meta{display:block;color:var(--tenue);font-size:.85rem;margin-top:2px}
.vuoto{color:var(--tenue);font-style:italic}
footer{color:var(--tenue);font-size:.85rem;border-top:1px solid var(--riga);padding-top:14px}
footer a{color:var(--accento)}
"""


def pagina(titolo: str, corpo: str, profondita: int = 0) -> str:
    return f"""<!doctype html>
<html lang="it"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(titolo)}</title>
<style>{CSS}</style>
</head><body><main>
{corpo}
</main></body></html>
"""


def ancora(nome: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalizza(nome)).strip("-")


def html_report(imp: dict, dati: dict, link_archivio: str) -> str:
    ora = datetime.fromisoformat(dati["generato"])
    nav = "".join(
        f'<a href="#{ancora(t["nome"])}">{html.escape(t["nome"])}<span>{len(t["articoli"])}</span></a>'
        for t in dati["temi"]
    )
    sezioni = []
    for t in dati["temi"]:
        if t.get("errore"):
            righe = f'<p class="vuoto">Ricerca non riuscita: {html.escape(t["errore"])}</p>'
        elif not t["articoli"]:
            righe = '<p class="vuoto">Nessun articolo nuovo.</p>'
        else:
            voci, gruppo = [], None
            for a in t["articoli"]:
                if a.get("gruppo") and a["gruppo"] != gruppo:
                    gruppo = a["gruppo"]
                    voci.append(f'</ul><h3>{html.escape(gruppo)}</h3><ul>')
                q = datetime.fromisoformat(a["quando"])
                quando = f"{q.day} {MESI[q.month - 1][:3]}, {q:%H:%M}"
                voci.append(
                    f'<li><a href="{html.escape(a["link"])}" target="_blank" rel="noopener">'
                    f'{html.escape(a["titolo"])}</a>'
                    f'<span class="meta">{html.escape(a["fonte"])} · {quando}</span></li>'
                )
            righe = ("<ul>" + "".join(voci) + "</ul>").replace("<ul></ul>", "")
        sezioni.append(
            f'<section><h2 id="{ancora(t["nome"])}">{html.escape(t["nome"])}'
            f'<small>{len(t["articoli"])} articoli · ultime {t["ore"]} ore</small></h2>{righe}</section>'
        )
    corpo = f"""<header><h1>{html.escape(imp["titolo"])}</h1>
<p class="data">{data_estesa(ora).capitalize()} · aggiornata alle {ora:%H:%M}</p></header>
<nav>{nav}</nav>
{''.join(sezioni)}
<footer>Articoli da Google News, solo dalle testate scelte in temi.toml, senza quelli già usciti nelle rassegne della settimana.
<a href="{link_archivio}">Archivio</a></footer>"""
    return pagina(f'{imp["titolo"]} – {data_estesa(ora)}', corpo)


def html_archivio(imp: dict) -> str:
    giorni = sorted((f.stem for f in (DOCS / "archivio").glob("????-??-??.html")), reverse=True)
    voci = "".join(
        f'<li><a href="{g}.html">{data_estesa(datetime.fromisoformat(g)).capitalize()}</a></li>'
        for g in giorni
    )
    corpo = f"""<header><h1>{html.escape(imp["titolo"])}: archivio</h1>
<p class="data"><a href="../">Torna alla rassegna di oggi</a></p></header>
<ul>{voci}</ul>"""
    return pagina(f'{imp["titolo"]} – archivio', corpo)


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--temi", default=str(QUI / "temi.toml"))
    args = ap.parse_args()

    config = tomllib.loads(Path(args.temi).read_text(encoding="utf-8"))
    imp = {"titolo": "Rassegna stampa", "ore": 24, "max_articoli": 15, "max_per_fonte": 4,
           "lingua": "it", "paese": "IT"}
    imp.update(config.get("impostazioni", {}))

    adesso = datetime.now(ROMA)
    oggi = adesso.date().isoformat()
    gia_usciti = titoli_precedenti(oggi)

    temi, errori = [], 0
    for tema in config["tema"]:
        print(f"→ {tema['nome']}")
        voce = {"nome": tema["nome"], "ore": tema.get("ore", imp["ore"]), "articoli": []}
        try:
            articoli = cerca(tema, imp)
            voce["articoli"] = [a for a in articoli if normalizza(a["titolo"]) not in gia_usciti]
            print(f"  {len(articoli)} trovati, {len(voce['articoli'])} nuovi")
        except Exception as e:
            errori += 1
            voce["errore"] = str(e)
            print(f"  ERRORE: {e}", file=sys.stderr)
        temi.append(voce)

    if errori == len(temi):
        print("Tutte le ricerche sono fallite: non aggiorno il report.", file=sys.stderr)
        return 1

    dati = {"generato": adesso.isoformat(timespec="minutes"), "temi": temi}
    DATI.mkdir(exist_ok=True)
    (DATI / f"{oggi}.json").write_text(json.dumps(dati, ensure_ascii=False, indent=1), encoding="utf-8")

    (DOCS / "archivio").mkdir(parents=True, exist_ok=True)
    (DOCS / "archivio" / f"{oggi}.html").write_text(html_report(imp, dati, "index.html"), encoding="utf-8")
    (DOCS / "index.html").write_text(html_report(imp, dati, "archivio/"), encoding="utf-8")
    (DOCS / "archivio" / "index.html").write_text(html_archivio(imp), encoding="utf-8")
    (DOCS / ".nojekyll").touch()
    print(f"Report scritto in {DOCS / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
