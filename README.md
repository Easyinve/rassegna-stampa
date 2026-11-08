# Rassegna stampa automatica

Ogni mattina GitHub Actions cerca su Google News gli articoli delle ultime ore sui temi in [`temi.toml`](temi.toml) e pubblica una pagina con titoli, testate e link, raggruppati per tema. Le rassegne dei giorni precedenti restano nell'archivio.

Non entra tutto quello che trova Google News, ma solo tre gruppi di fonti, mostrati separati sotto ogni tema. I pulsanti in cima alla pagina permettono di vederne uno solo alla volta, e la pagina ricorda la scelta:

- **Giornali**: un elenco unico di testate nazionali autorevoli (agenzie, quotidiani, tv);
- **Giornali locali**: un elenco unico dei principali quotidiani locali, comprese le edizioni locali di Corriere e Repubblica, più quelli che ogni tema aggiunge per conto suo (per esempio StrettoWeb e Tempostretto per il Ponte, Salto.bz e La Provincia di Sondrio per l'idroelettrico);
- **Stampa specializzata**: un elenco diverso per ogni tema (per esempio Quotidiano Sanità e Nurse24 per la sanità, Staffetta Quotidiana e QualEnergia per l'idroelettrico, Roars e Orizzonte Scuola per l'università).

Temi attuali: Ponte sullo Stretto, grandi opere, università, sanità italiana, concessioni idroelettriche, aree interne, filiera agroalimentare.

In fondo c'è una sezione diversa, **Storie dal mondo**: reportage e approfondimenti internazionali su comunità (anche piccole), questioni ambientali locali e innovazioni nelle città. Ha gruppi suoi, per area: **Europa**, **Resto del mondo** e **Stati Uniti**, quest'ultimo con meno spazio, al massimo 5 articoli. Entrano per primi i siti dedicati a questi temi, presi interi: Positive News, The Ecologist, Huck, le sezioni Environment, Global development e Long read del Guardian, BBC Future, Mongabay, Dialogue Earth, Sixth Tone, Global Voices e altri. Nei posti rimasti entrano gli articoli di alcune grandi testate (Guardian, Le Monde, La Croix, Courrier international, El País, Al Jazeera, Scroll, Nippon.com) che rispondono a ricerche in inglese, francese e spagnolo. Ogni testata ha al massimo 2 articoli per gruppo. I pulsanti del filtro non la riguardano: resta sempre visibile per intero.

In questa sezione titoli e sommari sono **tradotti in italiano**, con il titolo originale in corsivo sotto. Per la traduzione si usa il servizio gratuito di Google Translate, lo stesso del sito: non serve una chiave e non si consumano token di Claude. Se un giorno il servizio non risponde, gli articoli restano in lingua originale. Il sommario c'è solo per i siti letti dal loro feed RSS. Google News dà solo il titolo, quindi gli articoli delle grandi testate e dei siti senza feed leggibile (Cities Today, Next City, New Internationalist, Rest of World) non hanno sommario.

## Come funziona

- `rassegna.py` legge i temi, interroga il feed RSS di Google News e scrive `docs/index.html`, `docs/archivio/AAAA-MM-GG.html` e i dati grezzi in `dati/AAAA-MM-GG.json`. Usa solo la libreria standard di Python (3.11 o successivo), quindi non c'è niente da installare.
- Gli articoli già usciti nelle rassegne dei sette giorni precedenti non vengono ripetuti.
- `.github/workflows/rassegna.yml` lo esegue ogni giorno alle 6:30 italiane e salva i file nel repository. GitHub Pages pubblica la cartella `docs`. GitHub ragiona in ora UTC e non conosce l'ora legale, quindi il workflow ha due orari (4:30 e 5:30 UTC) e tiene solo quello che corrisponde alle 6:30 in Italia; l'altro si chiude subito senza fare nulla.

## Messa online (una volta sola)

1. Crea un repository su GitHub e caricaci questa cartella.
2. Su GitHub: **Settings → Pages → Build and deployment**: Source "Deploy from a branch", branch `main`, cartella `/docs`.
3. **Actions → Rassegna stampa → Run workflow** per lanciare la prima rassegna senza aspettare la mattina dopo (le volte successive basta il pulsante nella pagina).

La pagina sarà su `https://<utente>.github.io/<nome-repository>/`.

## Il pulsante «Aggiorna ora»

In cima alla pagina c'è un pulsante che prepara subito una nuova rassegna, senza aspettare la mattina dopo. Dopo un paio di minuti la pagina si ricarica da sola con gli articoli aggiornati.

Una pagina di GitHub Pages è pubblica e statica, quindi per avviare il workflow il pulsante ha bisogno di un permesso: un **token personale** di GitHub, che si inserisce una volta sola in «Impostazioni del pulsante» e resta salvato solo nel browser in cui lo inserisci (mai nella pagina né nel repository). Su un altro computer o sul telefono va inserito di nuovo.

Per crearlo: [github.com/settings/personal-access-tokens/new](https://github.com/settings/personal-access-tokens/new) → *Repository access*: **Only select repositories** e scegli questo repository → *Permissions*: **Actions: Read and write**, nient'altro. Con questo token si può solo avviare e leggere le Actions di questo repository. Alla scadenza se ne crea uno nuovo.

Senza token, il pulsante indica il link alla pagina del workflow su GitHub, dove lo si avvia con **Run workflow**.

Se la pagina non è su `utente.github.io/nome-repository` (per esempio con un dominio personalizzato), in `temi.toml` va indicato `repository = "utente/nome-repository"`.

## Cambiare i temi

Si modifica solo `temi.toml`. Per ogni tema:

- `query`: la ricerca su Google News, con la sintassi del sito (virgolette, `OR`, `-parola`). Conviene non superare 6-7 alternative per ricerca: oltre, Google News ignora il limite di tempo e restituisce articoli vecchi. Se servono più alternative si scrive un elenco di ricerche brevi, `query = ['...', '...']`, come nel tema delle grandi opere;
- `parole`: almeno una deve comparire nel titolo, altrimenti l'articolo viene scartato. È il filtro più importante: senza, Google News restituisce anche pagine che citano il tema solo nella barra laterale. Le parole valgono intere (`"tav"` non trova "tavolo"); con l'asterisco finale basta l'inizio della parola (`"aten*"` trova "ateneo" e "atenei"). Maiuscole e minuscole non contano;
- `escludi`: parole che fanno scartare l'articolo se compaiono nel titolo, con le stesse regole;
- `ore`: per i temi con poche notizie al giorno, una finestra più lunga;
- `fonti_specialistiche`: i domini dei siti di settore per quel tema (es. `"quotidianosanita.it"`);
- `fonti_locali`: giornali locali da aggiungere, solo per quel tema, a quelli dell'elenco generale;
- `max_articoli`, `max_per_fonte`: limiti diversi da quelli generali, solo per quel tema.

Un tema può anche avere gruppi suoi al posto dei tre standard, come «Storie dal mondo»:

- ogni `[[tema.gruppo]]` ha un `nome`, le `fonti` prese intere (anche sezioni di un sito, per esempio `"theguardian.com/environment"`, oppure l'indirizzo del feed RSS del sito, `"https://grist.org/feed/"`, che dà anche il sommario e il link diretto; se il feed ha un nome strano si scrive `{ feed = "https://…", nome = "Huck" }`), le `testate` da cui si prendono solo gli articoli che rispondono alle ricerche e, se serve, un suo `max_articoli`;
- al posto di `query` si scrive `ricerche`, un elenco in cui ogni ricerca ha la sua lingua: `{ query = '...', lingua = "fr", paese = "FR" }`;
- `lingua` e `paese` del tema indicano l'edizione di Google News in cui cercare le fonti prese intere: per i siti in inglese serve `"en-GB"`/`"GB"`, perché l'edizione italiana non restituisce quasi niente;
- `descrizione` è la riga che compare sotto il titolo della sezione;
- `traduci = true` traduce in italiano titoli e sommari in altre lingue.

In `[impostazioni]`:

- `fonti_autorevoli` sono i domini dei giornali nazionali, `fonti_locali` quelli dei giornali locali, validi per tutti i temi. I sottodomini sono compresi, e quando un sito sta in due elenchi vince il dominio più specifico: `torino.corriere.it` è tra i locali, quindi Corriere Torino finisce lì e non tra i nazionali con `corriere.it`;
- `max_articoli` e `max_per_fonte` limitano quanti articoli entrano per gruppo e per testata, così una fonte molto prolifica non riempie la sezione da sola;
- `fonti_escluse` elenca le testate da scartare sempre.

Se si svuotano tutti gli elenchi di fonti, la rassegna torna a prendere articoli da tutte le fonti.

Per capire se un sito è indicizzato da Google News basta cercare `site:dominio.it` su [news.google.com](https://news.google.com).

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

- I link passano da Google News, che reindirizza all'articolo originale, tranne quelli dei siti letti dal loro feed.
- Le traduzioni sono automatiche: in genere comprensibili, a volte goffe (per esempio i nomi propri o i giochi di parole nei titoli).
- Google News ignora il limite di tempo quando una ricerca combina parole e un elenco di siti, e restituisce al massimo 100 risultati per ricerca. Lo script per questo fa più ricerche per tema (circa 40 in tutto, un minuto di esecuzione) e filtra date e titoli per conto suo.
- I siti che Google News non indicizza non compaiono, anche se sono nell'elenco.
- Le Actions programmate possono partire con qualche minuto di ritardo e GitHub le sospende se il repository resta senza attività per 60 giorni (i commit quotidiani della rassegna dovrebbero bastare a tenerlo attivo).
