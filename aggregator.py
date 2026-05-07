"""
Coupon scraper riusabile per qualsiasi e-commerce.

Fonti:
  1. Wayback Machine — pagine archiviate del sito con keyword promo.
  2. DuckDuckGo HTML — search engine senza API key, query mirate.
  3. Pagine del sito stesso — sezioni promo/blog/offerte.
  4. Aggregatori coupon IT/EU — Picodi, Coupert, Promocodius, ecc.

Validazione opzionale (solo siti WooCommerce): applica i candidati a
/wp-admin/admin-ajax.php per distinguere VALID/INVALID. Richiede --product-id.

Uso:
  python aggregator.py --url https://example.it
  python aggregator.py --url example.it --brand example --product-id 123
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from dataclasses import dataclass, field
from urllib.parse import quote_plus, urlparse

import httpx
from bs4 import BeautifulSoup


DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
DEFAULT_PATHS = ["/", "/blog/", "/offerte/", "/promozioni/", "/news/", "/shop/"]
DEFAULT_QUERY_TEMPLATES = [
    '{brand} coupon',
    '{brand} "codice sconto"',
    '{brand} promo',
    'site:{domain} coupon OR sconto',
]

COUPON_RE = re.compile(r"\b([A-Z0-9][A-Z0-9_-]{3,19})\b")
CONTEXT_HINTS = re.compile(
    r"(coupon|codice\s+sconto|promo\s*code|usa\s+il\s+codice|inserisci\s+il\s+codice|discount\s+code)",
    re.IGNORECASE,
)
BASE_STOPWORDS = {
    "HTTP", "HTTPS", "HTML", "HEAD", "BODY", "DIV", "SPAN", "WWW", "COM", "ORG",
    "IT", "NET", "EU", "DE", "FR", "ES", "GET", "POST", "JSON", "NULL", "TRUE",
    "FALSE", "WORDPRESS", "WOOCOMMERCE", "JAVASCRIPT", "FUNCTION", "RETURN",
    "VAR", "LET", "CONST", "MOZILLA", "WINDOWS", "APPLE", "WEBKIT", "GOOGLE",
    "FACEBOOK",
}


@dataclass
class Site:
    base_url: str
    brand: str
    domain: str
    product_id: str | None
    paths: list[str]
    user_agent: str
    stopwords: set[str]
    validate: bool


def build_site(args: argparse.Namespace) -> Site:
    raw = args.url if "://" in args.url else f"https://{args.url}"
    parsed = urlparse(raw)
    netloc = parsed.netloc or parsed.path
    if netloc.startswith("www."):
        netloc = netloc[4:]
    netloc = netloc.strip("/")
    if not netloc or "." not in netloc:
        sys.exit(f"URL invalido: {args.url!r}")
    scheme = parsed.scheme or "https"
    base_url = f"{scheme}://{netloc}"
    brand = (args.brand or netloc.split(".")[0]).lower()
    paths = [p.strip() for p in args.paths.split(",")] if args.paths else list(DEFAULT_PATHS)
    stopwords = set(BASE_STOPWORDS) | {brand.upper(), netloc.split(".")[0].upper()}
    return Site(
        base_url=base_url,
        brand=brand,
        domain=netloc,
        product_id=args.product_id,
        paths=paths,
        user_agent=args.user_agent,
        stopwords=stopwords,
        validate=args.validate and args.product_id is not None,
    )


def fetch(client: httpx.Client, url: str) -> str:
    try:
        r = client.get(url, timeout=15, follow_redirects=True)
        if r.status_code == 200:
            return r.text
    except httpx.HTTPError as e:
        print(f"  ! fetch fail {url}: {e}")
    return ""


def wayback_urls(client: httpx.Client, site: Site) -> list[str]:
    """CDX API: URL archiviati del sito con keyword promo."""
    cdx = (
        "https://web.archive.org/cdx/search/cdx"
        f"?url={site.domain}/*&output=json&fl=timestamp,original&filter=statuscode:200"
        "&collapse=urlkey&limit=500"
    )
    raw = fetch(client, cdx)
    if not raw:
        return []
    try:
        rows = json.loads(raw)[1:]
    except (ValueError, IndexError):
        return []
    keywords = ("coupon", "promo", "sconto", "offert", "saldi", "buono", "discount")
    out = []
    for ts, orig in rows:
        if any(k in orig.lower() for k in keywords):
            out.append(f"https://web.archive.org/web/{ts}/{orig}")
    return out


def ddg_search(client: httpx.Client, query: str, limit: int = 15) -> list[str]:
    """DuckDuckGo HTML, no API key."""
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    html = fetch(client, url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.select("a.result__a"):
        href = a.get("href", "")
        if href.startswith("http"):
            links.append(href)
    return links[:limit]


def site_promo_pages(site: Site) -> list[str]:
    return [site.base_url.rstrip("/") + p for p in site.paths]


def build_aggregators(brand: str) -> list[dict]:
    """Aggregatori coupon. shop_pattern costruito dinamicamente dal brand."""
    b = re.escape(brand)
    brand_re = re.compile(b, re.I)
    return [
        {
            "name": "Picodi",
            "search": "https://www.picodi.com/it/cerca?q={q}",
            "shop_pattern": re.compile(rf"/it/[a-z0-9-]*{b}[a-z0-9-]*", re.I),
            "code_selectors": [".code", "[data-code]", ".coupon-code", "strong.c-code"],
            "data_attrs": ["data-code", "data-clipboard-text"],
        },
        {
            "name": "Coupert",
            "search": "https://it.coupert.com/search?q={q}",
            "shop_pattern": re.compile(rf"/coupons?/[a-z0-9-]*{b}[a-z0-9-]*", re.I),
            "code_selectors": [".code", ".coupon-code", "[data-code]"],
            "data_attrs": ["data-code", "data-clipboard-text"],
        },
        {
            "name": "Promocodius",
            "search": "https://promocodius.com/search?q={q}",
            "shop_pattern": re.compile(rf"/store/[a-z0-9-]*{b}[a-z0-9-]*", re.I),
            "code_selectors": [".coupon-code", ".code", "[data-code]"],
            "data_attrs": ["data-code"],
        },
        {
            "name": "Codicesconto",
            "search": "https://www.codicesconto.com/?s={q}",
            "shop_pattern": brand_re,
            "code_selectors": [".coupon-code", ".code", "strong"],
            "data_attrs": ["data-code", "data-clipboard"],
        },
        {
            "name": "Couponsenzalimiti",
            "search": "https://www.couponsenzalimiti.com/?s={q}",
            "shop_pattern": brand_re,
            "code_selectors": [".coupon-code", ".code", "strong", "code"],
            "data_attrs": ["data-code"],
        },
    ]


def scrape_aggregator(client: httpx.Client, agg: dict, site: Site) -> set[str]:
    """Cerca shop su un aggregatore, segui primi match, estrai codici."""
    out: set[str] = set()
    search_url = agg["search"].format(q=quote_plus(site.brand))
    print(f"  ? {agg['name']}: {search_url}")
    html = fetch(client, search_url)
    if not html:
        return out

    out |= extract_codes_from_page(html, agg, site)

    soup = BeautifulSoup(html, "html.parser")
    shop_links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if agg["shop_pattern"].search(href):
            if href.startswith("/"):
                p = urlparse(search_url)
                href = f"{p.scheme}://{p.netloc}{href}"
            if href not in shop_links:
                shop_links.append(href)
        if len(shop_links) >= 3:
            break

    for link in shop_links:
        print(f"    -> {link}")
        page = fetch(client, link)
        out |= extract_codes_from_page(page, agg, site)
        time.sleep(random.uniform(0.8, 1.5))

    return out


def extract_codes_from_page(html: str, agg: dict, site: Site) -> set[str]:
    """Estrai codici via selettori CSS + attributi data-* aggregatore."""
    if not html:
        return set()
    soup = BeautifulSoup(html, "html.parser")
    out: set[str] = set()

    for attr in agg.get("data_attrs", []):
        for el in soup.find_all(attrs={attr: True}):
            val = (el.get(attr) or "").strip().upper()
            if 4 <= len(val) <= 20 and re.fullmatch(r"[A-Z0-9_-]+", val) and val not in site.stopwords:
                out.add(val)

    for sel in agg.get("code_selectors", []):
        for el in soup.select(sel):
            t = (el.get_text() or "").strip().upper()
            if 4 <= len(t) <= 20 and re.fullmatch(r"[A-Z0-9_-]+", t) and t not in site.stopwords:
                out.add(t)

    out |= extract_candidates(html, site)
    return out


def extract_candidates(html: str, site: Site) -> set[str]:
    """Estrae codici plausibili da HTML, prioritizza match vicino a hint."""
    if not html:
        return set()
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    out = set()

    for m in CONTEXT_HINTS.finditer(text):
        window = text[max(0, m.start() - 80): m.end() + 200]
        for c in COUPON_RE.findall(window.upper()):
            if c not in site.stopwords and not c.isdigit():
                out.add(c)

    for tag in soup.find_all(["code", "strong", "b", "kbd"]):
        t = (tag.get_text() or "").strip().upper()
        if 4 <= len(t) <= 20 and re.fullmatch(r"[A-Z0-9_-]+", t) and t not in site.stopwords:
            out.add(t)

    return out


def get_nonce(client: httpx.Client, site: Site) -> str:
    html = fetch(client, f"{site.base_url}/cart/")
    m = re.search(r'"apply_coupon_nonce":"([a-f0-9]+)"', html)
    if m:
        return m.group(1)
    soup = BeautifulSoup(html, "html.parser")
    inp = soup.find("input", {"name": "security"})
    return inp["value"] if inp else ""


def validate_coupon(client: httpx.Client, site: Site, code: str, nonce: str) -> str:
    r = client.post(
        f"{site.base_url}/wp-admin/admin-ajax.php",
        data={"action": "apply_coupon", "security": nonce, "coupon_code": code},
        timeout=15,
    )
    soup = BeautifulSoup(r.text, "html.parser")
    if soup.select_one(".woocommerce-message"):
        return "VALID"
    if soup.select_one(".woocommerce-error"):
        return "INVALID"
    return "UNKNOWN"


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Scopri coupon attivi/storici per un e-commerce, senza brute-force.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--url", required=True, help="URL del sito target (es. https://example.it).")
    ap.add_argument("--brand", help="Keyword brand per ricerche/aggregatori. Default: SLD del dominio.")
    ap.add_argument("--product-id", help="ID prodotto WooCommerce per validazione coupon.")
    ap.add_argument("--no-validate", dest="validate", action="store_false",
                    help="Salta lo step di validazione WooCommerce.")
    ap.add_argument("--paths", help="Path promo separati da virgola (default: /,/blog/,/offerte/,...).")
    ap.add_argument("--user-agent", default=DEFAULT_UA)
    ap.add_argument("--limit-wayback", type=int, default=30, help="Max URL Wayback da scaricare.")
    ap.add_argument("--limit-ddg", type=int, default=15, help="Max risultati per query DDG.")
    ap.set_defaults(validate=True)
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    site = build_site(args)
    headers = {"User-Agent": site.user_agent, "Referer": f"{site.base_url}/cart/"}
    candidates: set[str] = set()

    print(f"[*] target: {site.base_url}  brand: {site.brand}")

    with httpx.Client(headers=headers) as client:
        print("[1] Wayback Machine...")
        for u in wayback_urls(client, site)[: args.limit_wayback]:
            print(f"  . {u}")
            candidates |= extract_candidates(fetch(client, u), site)
            time.sleep(0.5)

        print("[2] DuckDuckGo...")
        for tpl in DEFAULT_QUERY_TEMPLATES:
            q = tpl.format(brand=site.brand, domain=site.domain)
            print(f"  ? {q}")
            for link in ddg_search(client, q, limit=args.limit_ddg):
                candidates |= extract_candidates(fetch(client, link), site)
                time.sleep(random.uniform(0.8, 1.5))

        print("[3] Pagine sito...")
        for u in site_promo_pages(site):
            candidates |= extract_candidates(fetch(client, u), site)

        print("[4] Aggregatori coupon...")
        for agg in build_aggregators(site.brand):
            try:
                candidates |= scrape_aggregator(client, agg, site)
            except Exception as e:
                print(f"  ! {agg['name']} fail: {e}")
            time.sleep(random.uniform(1.0, 2.0))

        print(f"\n=> {len(candidates)} candidati: {sorted(candidates)}\n")

        if not candidates:
            return 0

        if not site.validate:
            print("[5] Validazione saltata (manca --product-id o --no-validate).")
            return 0

        print("[5] Validazione su WooCommerce...")
        client.get(f"{site.base_url}/?add-to-cart={site.product_id}")
        nonce = get_nonce(client, site)
        if not nonce:
            print("  ! Nonce non trovato. Verifica che il carrello abbia prodotti e che il sito sia WooCommerce.")
            return 1

        for code in sorted(candidates):
            status = validate_coupon(client, site, code, nonce)
            mark = {"VALID": "[OK]", "INVALID": "[X]", "UNKNOWN": "[?]"}[status]
            print(f"  {mark} {code} -> {status}")
            time.sleep(random.uniform(1.2, 2.0))

    return 0


if __name__ == "__main__":
    sys.exit(main())
