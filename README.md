# Rassegna stampa automatica

Ogni mattina GitHub Actions cerca su Google News gli articoli delle ultime ore sui temi in [`temi.toml`](temi.toml) e pubblica una pagina con titoli, testate e link, raggruppati per tema. Le rassegne dei giorni precedenti restano nell'archivio.

Temi attuali: Ponte sullo Stretto, università, sanità italiana, concessioni idroelettriche, aree interne, filiera agroalimentare.

## Come funziona

- `rassegna.py` legge i temi, interroga il feed RSS di Google News e scrive `docs/index.html`, `docs/archivio/AAAA-MM-GG.html` e i dati grezzi in `dati/AAAA-MM-GG.json`. Usa solo la libreria standard di Python (3.11 o successivo), quindi non c'è niente da installare.
- Gli articoli già usciti nelle rassegne dei sette giorni precedenti non vengono ripetuti.
- `.github/workflows/rassegna.yml` lo esegue ogni giorno alle 5:00 UTC (le 6 in inverno, le 7 con l'ora legale) e salva i file nel repository. GitHub Pages pubblica la cartella `docs`.

## Messa online (una volta sola)

1. Crea un repository su GitHub e caricaci questa cartella.
2. Su GitHub: **Settings → Pages → Build and deployment**: Source "Deploy from a branch", branch `main`, cartella `/docs`.
3. **Actions → Rassegna stampa → Run workflow** per lanciare la prima rassegna senza aspettare la mattina dopo.

La pagina sarà su `https://<utente>.github.io/<nome-repository>/`.

## Cambiare i temi

Si modifica solo `temi.toml`. Per ogni tema:

- `query`: la ricerca su Google News, con la sintassi del sito (virgolette, `OR`, `-parola`);
- `parole`: almeno una deve comparire nel titolo, altrimenti l'articolo viene scartato. È il filtro più importante: senza, Google News restituisce anche pagine che citano il tema solo nella barra laterale;
- `escludi`: parole che fanno scartare l'articolo se compaiono nel titolo;
- `ore`: per i temi con poche notizie al giorno, una finestra più lunga.

In `[impostazioni]`, `fonti_escluse` elenca le testate da scartare sempre.

## Provarlo sul proprio computer

```bash
python3 rassegna.py
open docs/index.html
```

Sul Mac, se Python è stato installato da python.org e dà errore `CERTIFICATE_VERIFY_FAILED`:

```bash
SSL_CERT_FILE=/etc/ssl/cert.pem python3 rassegna.py
```

## Limiti

- I link passano da Google News, che reindirizza all'articolo originale.
- Le Actions programmate possono partire con qualche minuto di ritardo e GitHub le sospende se il repository resta senza attività per 60 giorni (i commit quotidiani della rassegna dovrebbero bastare a tenerlo attivo).
