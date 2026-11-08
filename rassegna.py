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
    """Vero se una delle parole compare nel testo come parola intera
    ("tav" non trova "tavolo"); con l'asterisco finale basta l'inizio
    della parola ("aten*" trova "ateneo" e "atenei")."""
    for p in parole:
        if p.endswith("*"):
            schema = r"(?<!\w)" + re.escape(p[:-1])
        else:
            schema = r"(?<!\w)" + re.escape(p) + r"(?!\w)"
        if re.search(schema, testo):
            return True
    return False


def gruppi_del_tema(tema: dict, imp: dict) -> list[dict]:
    """I gruppi di fonti del tema, nell'ordine in cui compaiono nella pagina.

    Ogni gruppo ha due elenchi di siti:
    - "intere": se ne prende tutto quello che hanno pubblicato nelle ultime
      ore (siti di settore, o sezioni di un sito come theguardian.com/environment);
    - "ricerca": se ne prendono solo gli articoli che rispondono alle ricerche
      del tema (giornali che parlano di tutto).
    Un tema può definire gruppi suoi con [[tema.gruppo]]; altrimenti valgono
    i tre gruppi standard.
    """
    if tema.get("gruppo"):
        gruppi = [{"nome": g["nome"], "intere": g.get("fonti", []), "ricerca": g.get("testate", []),
                   "max": g.get("max_articoli", tema.get("max_articoli", imp["max_articoli"]))}
                  for g in tema["gruppo"]]
    else:
        m = tema.get("max_articoli", imp["max_articoli"])
        gruppi = [
            {"nome": "Giornali", "intere": [], "ricerca": imp.get("fonti_autorevoli", []), "max": m},
            {"nome": "Giornali locali", "intere": [],
             "ricerca": imp.get("fonti_locali", []) + tema.get("fonti_locali", []), "max": m},
            {"nome": "Stampa specializzata", "intere": tema.get("fonti_specialistiche", []),
             "ricerca": [], "max": m},
        ]
    return [g for g in gruppi if g["intere"] or g["ricerca"]]


def ricerche_del_tema(tema: dict, imp: dict) -> list[dict]:
    """Le ricerche del tema, ciascuna con la sua lingua. query può essere una
    ricerca sola o un elenco (con troppe alternative in una ricerca sola
    Google News torna a ignorare il limite di tempo); con ricerche = [...]
    ogni ricerca ha anche lingua e paese suoi."""
    if "ricerche" in tema:
        return [{"query": r["query"], "lingua": r.get("lingua", imp["lingua"]),
                 "paese": r.get("paese", imp["paese"])} for r in tema["ricerche"]]
    query = tema.get("query", [])
    query = query if isinstance(query, list) else [query]
    return [{"query": q, "lingua": imp["lingua"], "paese": imp["paese"]} for q in query]


def solo_dominio(sito: str) -> str:
    """"theguardian.com/environment" -> "theguardian.com"."""
    return sito.split("/")[0]


def cerca(tema: dict, imp: dict) -> list[dict]:
    """Articoli del tema, divisi in gruppi di fonti.

    Google News ignora il limite di tempo quando una ricerca combina parole e
    un elenco di siti, e restituisce al massimo 100 risultati ordinati per
    pertinenza: così gli articoli del giorno restano fuori. Per questo:
    - per i giornali si usa la ricerca del tema, filtrando poi per dominio,
      più una ricerca del tema ristretta ai siti;
    - per i siti presi interi (stampa specializzata) si prende tutto quello
      che hanno pubblicato nelle ultime ore (pochi siti per volta) e si filtra
      per parole nel titolo.
    Ogni articolo va nel gruppo del dominio più specifico che lo comprende:
    torino.corriere.it, se è tra i locali, batte corriere.it tra i nazionali.
    """
    ore = tema.get("ore", imp["ore"])
    da = datetime.now(timezone.utc) - timedelta(hours=ore)
    escludi = [p.lower() for p in tema.get("escludi", [])]
    parole = [p.lower() for p in tema.get("parole", [])]
    fonti_escluse = [f.lower() for f in imp.get("fonti_escluse", [])]
    gruppi = gruppi_del_tema(tema, imp)
    ricerche = ricerche_del_tema(tema, imp)

    candidati = []
    for r in ricerche:
        candidati += leggi_feed(r["query"], ore, r)
    if not gruppi:  # nessun elenco di fonti: si prende tutto
        gruppi = [{"nome": "", "intere": [], "ricerca": [], "max": imp["max_articoli"]}]
    # i siti presi interi si cercano nell'edizione di Google News del tema
    # (per i siti in inglese quella italiana restituisce poco o niente)
    edizione = {"lingua": tema.get("lingua", imp["lingua"]), "paese": tema.get("paese", imp["paese"])}
    for g in gruppi:
        siti = g["intere"]
        for i in range(0, len(siti), 5):
            voci = leggi_feed(" OR ".join("site:" + d for d in siti[i:i + 5]), ore, edizione)
            candidati += [{**v, "intera": True} for v in voci]
        siti = g["ricerca"]
        for r in ricerche:
            for i in range(0, len(siti), 15):
                elenco = " OR ".join("site:" + d for d in siti[i:i + 15])
                candidati += leggi_feed(f"({r['query']}) ({elenco})", ore, r)

    def gruppo_di(host: str) -> str | None:
        migliore, lunghezza = None, -1
        for g in gruppi:
            domini = [solo_dominio(d) for d in g["intere"] + g["ricerca"]]
            if not domini:
                return g["nome"]
            for d in domini:
                if (host == d or host.endswith("." + d)) and len(d) > lunghezza:
                    migliore, lunghezza = g["nome"], len(d)
        return migliore

    massimo = {g["nome"]: g["max"] for g in gruppi}
    max_per_fonte = tema.get("max_per_fonte", imp["max_per_fonte"])
    # prima i siti presi interi, poi i giornali; a parità, i più recenti
    candidati.sort(key=lambda c: c["quando"], reverse=True)
    candidati.sort(key=lambda c: not c.get("intera"))
    scelti = {g["nome"]: [] for g in gruppi}
    per_fonte: dict[tuple[str, str], int] = {}
    visti = set()
    for c in candidati:
        gruppo = gruppo_di(c["dominio"])
        t = c["titolo"].lower()
        chiave = normalizza(c["titolo"])
        if (gruppo is None or c["quando"] < da or len(chiave) < 20 or chiave in visti
                or chiave == normalizza(c["fonte"])
                or (parole and not contiene(t, parole))
                or contiene(t, escludi)
                or any(f in c["fonte"].lower() or f in c["dominio"] for f in fonti_escluse)):
            continue
        if (per_fonte.get((gruppo, c["fonte"]), 0) >= max_per_fonte
                or len(scelti[gruppo]) >= massimo[gruppo]):
            continue
        visti.add(chiave)
        per_fonte[(gruppo, c["fonte"])] = per_fonte.get((gruppo, c["fonte"]), 0) + 1
        c.pop("intera", None)
        scelti[gruppo].append({**c, "quando": c["quando"].astimezone(ROMA).isoformat(), "gruppo": gruppo})
    return [a for g in gruppi for a in scelti[g["nome"]]]


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
h3 span{color:var(--tenue);font-weight:normal;margin-left:4px}
.filtro{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 14px}
.filtro button{font:inherit;font-size:.9rem;cursor:pointer;border:1px solid var(--accento);background:transparent;color:var(--testo);border-radius:6px;padding:5px 12px}
.filtro button[aria-pressed="true"]{background:var(--accento);color:#fff}
body[data-filtro] .gruppo{display:none}
body[data-filtro] .gruppo h3{display:none}
body[data-filtro] section.a-parte .gruppo{display:block}
body[data-filtro] section.a-parte .gruppo h3{display:block}
.desc{color:var(--tenue);font-size:.9rem;margin:0 0 4px}
ul{list-style:none;margin:0;padding:0}
li{padding:10px 0;border-bottom:1px solid var(--riga)}
li a{color:var(--testo);text-decoration:none;font-weight:600}
li a:hover{color:var(--accento)}
.meta{display:block;color:var(--tenue);font-size:.85rem;margin-top:2px}
.vuoto{color:var(--tenue);font-style:italic}
footer{color:var(--tenue);font-size:.85rem;border-top:1px solid var(--riga);padding-top:14px}
footer a{color:var(--accento)}
#aggiorna{margin-top:12px;font-size:.9rem}
#aggiorna button{font:inherit;cursor:pointer;border-radius:6px;padding:5px 12px;border:1px solid var(--accento);background:transparent;color:var(--testo)}
#agg-bottone{background:var(--accento)!important;color:#fff!important;font-weight:600}
#agg-bottone:disabled{opacity:.6;cursor:wait}
#agg-stato{color:var(--tenue);margin-left:8px}
#agg-stato a,#aggiorna details a{color:var(--accento)}
#aggiorna details{margin-top:8px;color:var(--tenue)}
#aggiorna summary{cursor:pointer;width:max-content}
.agg-riga{display:flex;gap:6px;flex-wrap:wrap}
#agg-token{flex:1;min-width:180px;font:inherit;padding:5px 8px;border:1px solid var(--riga);border-radius:6px;background:var(--sfondo);color:var(--testo)}
"""


JS_FILTRO = """
(function(){
  var bott = document.querySelectorAll('.filtro button');
  if (!bott.length) return;
  var stile = document.createElement('style');
  document.head.appendChild(stile);
  function scegli(f){
    bott.forEach(function(b){ b.setAttribute('aria-pressed', b.dataset.f === f ? 'true' : 'false'); });
    if (f === 'tutti') { delete document.body.dataset.filtro; stile.textContent = ''; }
    else { document.body.dataset.filtro = f; stile.textContent = 'body[data-filtro] .gruppo[data-g="' + f + '"]{display:block}'; }
    document.querySelectorAll('.n').forEach(function(n){
      var c = JSON.parse(n.dataset.conti); n.textContent = c[f] || 0;
    });
    try { localStorage.setItem('rassegna-filtro', f); } catch (e) {}
  }
  bott.forEach(function(b){ b.addEventListener('click', function(){ scegli(b.dataset.f); }); });
  var salvato = null;
  try { salvato = localStorage.getItem('rassegna-filtro'); } catch (e) {}
  if (salvato && document.querySelector('.filtro button[data-f="' + salvato + '"]')) scegli(salvato);
})();
"""

# Pulsante "Aggiorna ora": avvia il workflow con l'API di GitHub usando un
# token personale che resta solo nel browser di chi lo inserisce.
JS_AGGIORNA = """
(function(){
  var box = document.getElementById('aggiorna');
  if (!box) return;
  var bottone = document.getElementById('agg-bottone');
  var stato = document.getElementById('agg-stato');
  var impost = document.getElementById('agg-impost');
  var campo = document.getElementById('agg-token');
  var CHIAVE = 'rassegna-token';
  var WORKFLOW = 'rassegna.yml';

  // utente/repository: dall'impostazione, altrimenti dall'indirizzo di GitHub Pages
  var repo = box.dataset.repo;
  if (!repo && /\\.github\\.io$/.test(location.hostname)) {
    var utente = location.hostname.split('.')[0];
    var primo = location.pathname.split('/')[1];
    repo = utente + '/' + (primo || location.hostname);
  }
  var linkActions = repo ? 'https://github.com/' + repo + '/actions/workflows/' + WORKFLOW : null;
  document.querySelectorAll('.agg-link-actions').forEach(function(a){
    if (linkActions) a.href = linkActions; else a.removeAttribute('href');
  });

  function leggiToken(){ try { return localStorage.getItem(CHIAVE) || ''; } catch (e) { return ''; } }
  function scriviToken(t){ try { t ? localStorage.setItem(CHIAVE, t) : localStorage.removeItem(CHIAVE); } catch (e) {} }
  function mostra(testo, html){ stato[html ? 'innerHTML' : 'textContent'] = testo; }
  function aggiornaCampo(){ campo.value = ''; campo.placeholder = leggiToken() ? 'Token salvato in questo browser' : 'github_pat_…'; }
  aggiornaCampo();

  document.getElementById('agg-salva').addEventListener('click', function(){
    var t = campo.value.trim();
    if (!t) return;
    scriviToken(t); aggiornaCampo(); impost.open = false;
    mostra('Token salvato. Ora puoi premere «Aggiorna ora».');
  });
  document.getElementById('agg-cancella').addEventListener('click', function(){
    scriviToken(''); aggiornaCampo(); mostra('Token cancellato da questo browser.');
  });

  function api(percorso, opzioni){
    opzioni = opzioni || {};
    opzioni.headers = {
      'Accept': 'application/vnd.github+json',
      'Authorization': 'Bearer ' + leggiToken(),
      'X-GitHub-Api-Version': '2022-11-28'
    };
    return fetch('https://api.github.com/repos/' + repo + percorso, opzioni);
  }
  var attendi = function(ms){ return new Promise(function(r){ setTimeout(r, ms); }); };

  async function aspettaPubblicazione(){
    var prima = document.body.dataset.generato;
    for (var i = 0; i < 40; i++) {
      await attendi(10000);
      try {
        var r = await fetch(location.pathname + '?v=' + Date.now(), { cache: 'no-store' });
        var testo = await r.text();
        var m = testo.match(/data-generato="([^"]+)"/);
        if (m && m[1] !== prima) { location.reload(); return; }
      } catch (e) {}
    }
    mostra('La rassegna è pronta ma la pagina non si è ancora aggiornata: ricaricala tra qualche minuto.');
  }

  async function avvia(){
    if (!repo) { mostra('Non riesco a capire quale sia il repository: indicalo in temi.toml (impostazione «repository»).'); return; }
    if (!leggiToken()) {
      impost.open = true;
      mostra('Per avviarla da qui serve un token (vedi sotto). In alternativa avviala <a href="' + linkActions + '" target="_blank" rel="noopener">da GitHub</a> con «Run workflow».', true);
      return;
    }
    bottone.disabled = true;
    var partenza = new Date(Date.now() - 5000).toISOString();
    try {
      var r = await api('/actions/workflows/' + WORKFLOW + '/dispatches', {
        method: 'POST', body: JSON.stringify({ ref: box.dataset.ramo || 'main' })
      });
      if (r.status === 401 || r.status === 403 || r.status === 404) {
        mostra('GitHub ha rifiutato il token: forse è scaduto o non ha il permesso «Actions: Read and write» su questo repository.');
        bottone.disabled = false; return;
      }
      if (!r.ok) throw new Error('risposta ' + r.status);
      mostra('Avviata. Preparo la rassegna, ci vogliono un paio di minuti…');
      var run = null;
      for (var i = 0; i < 60; i++) {
        await attendi(8000);
        var lista = await (await api('/actions/workflows/' + WORKFLOW + '/runs?event=workflow_dispatch&per_page=1')).json();
        run = lista.workflow_runs && lista.workflow_runs[0];
        if (!run || run.created_at < partenza) continue;
        if (run.status !== 'completed') { mostra('In corso su GitHub…'); continue; }
        break;
      }
      if (!run || run.status !== 'completed') {
        mostra('Ci sta mettendo più del solito: controlla <a href="' + linkActions + '" target="_blank" rel="noopener">su GitHub</a>.', true);
      } else if (run.conclusion === 'success') {
        mostra('Fatta. Aspetto che GitHub Pages pubblichi la nuova pagina (di solito meno di un minuto)…');
        await aspettaPubblicazione();
      } else {
        mostra('Non è riuscita: <a href="' + run.html_url + '" target="_blank" rel="noopener">vedi il dettaglio su GitHub</a>.', true);
      }
    } catch (e) {
      mostra('Errore di collegamento con GitHub (' + e.message + '). Riprova o avviala <a href="' + linkActions + '" target="_blank" rel="noopener">da GitHub</a>.', true);
    }
    bottone.disabled = false;
  }
  bottone.addEventListener('click', avvia);
})();
"""


def pagina(titolo: str, corpo: str, generato: str = "") -> str:
    return f"""<!doctype html>
<html lang="it"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(titolo)}</title>
<style>{CSS}</style>
</head><body data-generato="{html.escape(generato)}"><main>
{corpo}
</main>
<script>{JS_FILTRO}{JS_AGGIORNA}</script>
</body></html>
"""


def html_aggiorna(imp: dict) -> str:
    return f"""<div id="aggiorna" data-repo="{html.escape(imp.get("repository", ""))}" data-ramo="{html.escape(imp.get("ramo", "main"))}">
<button type="button" id="agg-bottone">Aggiorna ora</button>
<span id="agg-stato" aria-live="polite"></span>
<details id="agg-impost"><summary>Impostazioni del pulsante</summary>
<p>Il pulsante avvia la rassegna su GitHub con un tuo <b>token personale</b>, che resta salvato solo in questo browser. Si crea una volta sola su
<a href="https://github.com/settings/personal-access-tokens/new" target="_blank" rel="noopener">github.com/settings/personal-access-tokens</a>:
in «Repository access» scegli <i>Only select repositories</i> e questo repository; in «Permissions» dai <i>Actions: Read and write</i> e nient'altro.</p>
<div class="agg-riga"><input id="agg-token" type="password" autocomplete="off" spellcheck="false" aria-label="Token di GitHub">
<button type="button" id="agg-salva">Salva</button><button type="button" id="agg-cancella">Cancella</button></div>
<p>Senza token puoi avviarla anche dalla <a class="agg-link-actions" target="_blank" rel="noopener">pagina del workflow su GitHub</a>, con «Run workflow».</p>
</details>
</div>"""


def ancora(nome: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalizza(nome)).strip("-")


def html_report(imp: dict, dati: dict, link_archivio: str, pulsante: bool = False) -> str:
    ora = datetime.fromisoformat(dati["generato"])
    # i pulsanti del filtro valgono per i gruppi standard; le sezioni con
    # gruppi loro ("a parte") restano sempre intere
    tutti_gruppi = []
    for t in dati["temi"]:
        if t.get("a_parte"):
            continue
        for g in t.get("gruppi", []):
            if g not in tutti_gruppi:
                tutti_gruppi.append(g)

    def conti(t: dict) -> str:
        c = {"tutti": len(t["articoli"])}
        if t.get("a_parte"):
            c.update({ancora(g): len(t["articoli"]) for g in tutti_gruppi})
            return html.escape(json.dumps(c))
        for a in t["articoli"]:
            g = ancora(a.get("gruppo", "")) or "tutti"
            if g != "tutti":
                c[g] = c.get(g, 0) + 1
        return html.escape(json.dumps(c))

    nav = "".join(
        f'<a href="#{ancora(t["nome"])}">{html.escape(t["nome"])}'
        f'<span class="n" data-conti="{conti(t)}">{len(t["articoli"])}</span></a>'
        for t in dati["temi"]
    )
    filtro = ""
    if len(tutti_gruppi) > 1:
        bottoni = ['<button type="button" data-f="tutti" aria-pressed="true">Tutte le fonti</button>']
        bottoni += [f'<button type="button" data-f="{ancora(g)}" aria-pressed="false">{html.escape(g)}</button>'
                    for g in tutti_gruppi]
        filtro = f'<div class="filtro" role="group" aria-label="Filtra per tipo di fonte">{"".join(bottoni)}</div>'
    sezioni = []
    for t in dati["temi"]:
        if t.get("errore"):
            righe = f'<p class="vuoto">Ricerca non riuscita: {html.escape(t["errore"])}</p>'
        elif not t["articoli"]:
            righe = '<p class="vuoto">Nessun articolo nuovo.</p>'
        else:
            def voce(a: dict) -> str:
                q = datetime.fromisoformat(a["quando"])
                quando = f"{q.day} {MESI[q.month - 1][:3]}, {q:%H:%M}"
                return (f'<li><a href="{html.escape(a["link"])}" target="_blank" rel="noopener">'
                        f'{html.escape(a["titolo"])}</a>'
                        f'<span class="meta">{html.escape(a["fonte"])} · {quando}</span></li>')
            nomi = t.get("gruppi") or [""]
            blocchi = []
            for g in nomi:
                articoli = [a for a in t["articoli"] if a.get("gruppo", "") == g]
                lista = ("<ul>" + "".join(voce(a) for a in articoli) + "</ul>") if articoli \
                    else '<p class="vuoto">Nessun articolo.</p>'
                titolo_g = f"<h3>{html.escape(g)} <span>{len(articoli)}</span></h3>" if g else ""
                blocchi.append(f'<div class="gruppo" data-g="{ancora(g) or "tutti"}">{titolo_g}{lista}</div>')
            righe = "".join(blocchi)
        classe = ' class="a-parte"' if t.get("a_parte") else ""
        desc = f'<p class="desc">{html.escape(t["descrizione"])}</p>' if t.get("descrizione") else ""
        sezioni.append(
            f'<section{classe}><h2 id="{ancora(t["nome"])}">{html.escape(t["nome"])}'
            f'<small><span class="n" data-conti="{conti(t)}">{len(t["articoli"])}</span> articoli'
            f' · ultime {t["ore"]} ore</small></h2>{desc}{righe}</section>'
        )
    corpo = f"""<header><h1>{html.escape(imp["titolo"])}</h1>
<p class="data">{data_estesa(ora).capitalize()} · aggiornata alle {ora:%H:%M}</p>
{html_aggiorna(imp) if pulsante else ""}</header>
{filtro}
<nav>{nav}</nav>
{''.join(sezioni)}
<footer>Articoli da Google News, solo dalle testate scelte in temi.toml, senza quelli già usciti nelle rassegne della settimana.
<a href="{link_archivio}">Archivio</a></footer>"""
    return pagina(f'{imp["titolo"]} – {data_estesa(ora)}', corpo, dati["generato"])


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
        voce = {"nome": tema["nome"], "ore": tema.get("ore", imp["ore"]),
                "gruppi": [g["nome"] for g in gruppi_del_tema(tema, imp)], "articoli": []}
        if tema.get("gruppo"):
            voce["a_parte"] = True  # gruppi suoi: i pulsanti del filtro non la riguardano
        if tema.get("descrizione"):
            voce["descrizione"] = tema["descrizione"]
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
    (DOCS / "index.html").write_text(html_report(imp, dati, "archivio/", pulsante=True), encoding="utf-8")
    (DOCS / "archivio" / "index.html").write_text(html_archivio(imp), encoding="utf-8")
    (DOCS / ".nojekyll").touch()
    print(f"Report scritto in {DOCS / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
