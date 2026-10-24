import re
from urllib.parse import urlparse

CURRENCIES = {
    "€": "EUR",
    "eur": "EUR",
    "$": "USD",
    "usd": "USD",
    "£": "GBP",
    "gbp": "GBP",
    "zł": "PLN",
    "pln": "PLN",
    "kr": "SEK",
    "sek": "SEK",
    "chf": "CHF",
    "mex$": "MXN",
    "mxn": "MXN",
}

TLD_COUNTRY = {
    "es": "ES",
    "de": "DE",
    "fr": "FR",
    "it": "IT",
    "pt": "PT",
    "nl": "NL",
    "be": "BE",
    "at": "AT",
    "pl": "PL",
    "se": "SE",
    "uk": "UK",
    "mx": "MX",
    "ar": "AR",
    "cl": "CL",
    "us": "US",
}

CURRENCY_COUNTRY = {
    "EUR": "ES",
    "USD": "US",
    "GBP": "UK",
    "PLN": "PL",
    "SEK": "SE",
    "CHF": "CH",
    "MXN": "MX",
}

SAMPLE_RE = re.compile(
    r"\b("
    r"muestras?\b|free sample|sample pack|tester|probador|"
    r"sachet|vial|travel size|miniatura de perfume|"
    r"prueba gratuita|free trial|d[ií]as de prueba|per[ií]odo de prueba|"
    r"versi[oó]n de prueba|trial only|muster(probe)?|probeabo|"
    r"[eé]chantillon|campione omaggio|amostra gr[aá]tis"
    r")\b",
    re.I,
)

PERCENT_RE = re.compile(
    r"(?:[-–—−]\s*|(?:descuento|rebaja|ahorra|save|off|reduziert|r[eé]duction)\s+(?:del?\s+)?)(9\d)\s*%",
    re.I,
)

PRICE_RE = re.compile(
    r"(?P<cur1>€|£|\$|EUR|USD|GBP|PLN|zł)?\s*"
    r"(?P<num>\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})|\d{1,3}(?:,\d{3})*(?:\.\d{2})|\d+(?:[.,]\d{2})?)"
    r"\s*(?P<cur2>€|£|\$|EUR|USD|GBP|zł|PLN)?",
    re.I,
)


def parse_amount(text: str) -> float | None:
    if text is None:
        return None
    raw = str(text).strip().replace("\xa0", " ")
    if not raw:
        return None
    if re.fullmatch(r"0+(?:[.,]0+)?", raw):
        return 0.0
    match = PRICE_RE.search(raw)
    if not match:
        digits = re.sub(r"[^\d,.\-]", "", raw)
        if not digits:
            return None
        return _number(digits)
    return _number(match.group("num"))


def parse_money(text: str) -> tuple[float | None, str | None]:
    if text is None:
        return None, None
    raw = str(text).replace("\xa0", " ")
    match = PRICE_RE.search(raw)
    if not match:
        amount = parse_amount(raw)
        return amount, _currency_from(raw)
    amount = _number(match.group("num"))
    cur = _currency_from(match.group("cur1") or match.group("cur2") or raw)
    return amount, cur


def _number(num: str) -> float | None:
    num = num.replace(" ", "")
    if not num:
        return None
    if "," in num and "." in num:
        if num.rfind(",") > num.rfind("."):
            num = num.replace(".", "").replace(",", ".")
        else:
            num = num.replace(",", "")
    elif "," in num:
        parts = num.split(",")
        if len(parts[-1]) == 2:
            num = num.replace(".", "").replace(",", ".")
        else:
            num = num.replace(",", "")
    try:
        return float(num)
    except ValueError:
        return None


def _currency_from(token: str | None) -> str | None:
    if not token:
        return None
    low = token.lower().strip()
    for key, code in CURRENCIES.items():
        if key in low:
            return code
    return None


def discount_pct(price: float | None, reference: float | None) -> float | None:
    if price is None or reference is None or reference <= 0:
        return None
    if price < 0:
        return None
    pct = (1 - price / reference) * 100
    if pct < 0:
        return 0.0
    if pct > 100:
        return 100.0
    return round(pct, 1)


def percent_in_text(text: str) -> float | None:
    if not text:
        return None
    found = [int(m.group(1)) for m in PERCENT_RE.finditer(text)]
    return float(max(found)) if found else None


def is_sample(*parts: str) -> bool:
    blob = " ".join(p for p in parts if p)
    return bool(SAMPLE_RE.search(blob))


DIGITAL_RE = re.compile(
    r"kindle|e-?book|\bebook\b|\bpdf\b|descargable|imprimible|plantilla digital|"
    r"videojuego|steam|cd-?key|c[oó]digo digital|clave (de )?activaci|"
    r"playstation|nintendo e?shop|xbox (live|game pass)|watch face|"
    r"suscripci[oó]n|licencia digital|\bsoftware\b|audiolibro|"
    r"google play|app store|d[eé]mat[eé]rialis|curso online|webinar|"
    r"patr[oó]n (de costura|pdf|descargable)",
    re.I,
)


def is_digital(*parts: str) -> bool:
    blob = " ".join(p for p in parts if p)
    return bool(DIGITAL_RE.search(blob))


def domain_of(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def country_of(url: str, currency: str | None = None) -> str:
    host = domain_of(url)
    parts = host.split(".")
    if len(parts) >= 2 and parts[-2] == "co" and parts[-1] == "uk":
        return "UK"
    tld = parts[-1] if parts else ""
    if tld in TLD_COUNTRY and tld != "com":
        return TLD_COUNTRY[tld]
    if currency and currency in CURRENCY_COUNTRY:
        return CURRENCY_COUNTRY[currency]
    if tld == "com":
        return CURRENCY_COUNTRY.get(currency or "", "US")
    return TLD_COUNTRY.get(tld, "")


PRODUCT_TYPES = [
    ("videojuego", ("juego", "game", "steam", "epic games", "nintendo", "playstation")),
    ("robot aspirador", ("robot aspirador", "friegasuelos", "conga", "roomba", "roborock")),
    ("bicicleta", ("bicicleta", "e-bike", "ebike", "bici ")),
    ("patinete", ("patinete", "scooter")),
    ("informática", ("portátil", "portatil", "laptop", "monitor", "ssd", "teclado", "auricular")),
    ("móvil", ("iphone", "smartphone", "móvil", "movil", "galaxy", "pixel ")),
    ("televisor", ("televisor", "smart tv", "oled", "qled")),
    ("electrodoméstico", ("cafetera", "freidora", "airfryer", "nevera", "lavadora", "horno")),
    ("deporte", ("maillot", "zapatilla", "running", "fitness")),
    ("hogar", ("sofá", "sofa", "colchón", "lampara", "lámpara")),
    ("descargable", ("pdf", "imprimible", "patrón", "patron", "descargable", "plantilla")),
    ("moda", ("camiseta", "vestido", "chaqueta", "pantalón", "sudadera", "abrigo", "cazadora", "botas")),
]


def guess_type(*parts: str) -> str:
    blob = " ".join(p for p in parts if p).lower()
    for name, keys in PRODUCT_TYPES:
        if any(k in blob for k in keys):
            return name
    return "otros"
