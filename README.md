# promo-code-scraper

Scopre coupon attivi o storici per un qualsiasi e-commerce **senza brute-force**, aggregando fonti pubbliche.

## Fonti consultate

1. **Wayback Machine** — pagine archiviate del dominio con keyword promo (`coupon`, `sconto`, `offerta`, ...).
2. **DuckDuckGo HTML** — search engine senza API key, con query mirate al brand.
3. **Sito stesso** — path tipici tipo `/blog/`, `/offerte/`, `/promozioni/`.
4. **Aggregatori coupon IT/EU** — Picodi, Coupert, Promocodius, Codicesconto, Couponsenzalimiti.

I candidati estratti vengono filtrati con regex contestuali (parole-chiave nelle vicinanze) e una stopword list.

## Validazione (opzionale, solo WooCommerce)

Se il sito target gira su WooCommerce, lo script può applicare ogni candidato all'endpoint `wp-admin/admin-ajax.php` (`action=apply_coupon`) per distinguere `VALID` / `INVALID` / `UNKNOWN`. Richiede:

- `--product-id` di un prodotto reale (lo script lo aggiunge al carrello per ottenere il nonce).
- Sito che esponga `/cart/` con il pattern WooCommerce standard.

## Installazione

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Uso

```bash
# Solo discovery, nessuna validazione
python aggregator.py --url https://example.it --no-validate

# Discovery + validazione WooCommerce
python aggregator.py --url https://example.it --product-id 123

# Override brand (default: SLD del dominio)
python aggregator.py --url example.it --brand mio-shop

# Path promo custom
python aggregator.py --url https://example.it --paths "/,/saldi/,/black-friday/"
```

### Opzioni principali

| Flag | Default | Descrizione |
|------|---------|-------------|
| `--url` | (obbligatorio) | URL del sito target. |
| `--brand` | SLD del dominio | Keyword usata su DDG e aggregatori. |
| `--product-id` | — | ID prodotto WooCommerce per validazione. |
| `--no-validate` | — | Salta lo step di validazione. |
| `--paths` | `/,/blog/,/offerte/,/promozioni/,/news/,/shop/` | Path promo separati da virgola. |
| `--limit-wayback` | 30 | Max URL Wayback da scaricare. |
| `--limit-ddg` | 15 | Max risultati per query DuckDuckGo. |
| `--user-agent` | Mozilla generico | Override User-Agent HTTP. |

## Disclaimer

Strumento per ricerca pubblica (OSINT) e auditing del proprio store. Usa responsabilmente:

- Rispetta `robots.txt` e i Termini di Servizio dei siti consultati.
- Non usare per accedere a sconti non destinati a te o per abuso massivo di codici.
- Lo step di validazione genera traffico verso il sito target: usalo solo su domini di tua proprietà o con autorizzazione esplicita.

L'autore non è responsabile per usi impropri.

## Licenza

[MIT](LICENSE)
