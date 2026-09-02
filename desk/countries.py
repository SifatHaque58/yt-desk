"""Locales the desk can ask InnerTube for.

`gl` is the market YouTube should rank for. The exit IP still wins — these
only set `hl`/`gl` on the WEB client. PIA region is chosen in the VPN app.
"""

COUNTRIES = [
    {"code": "US", "name": "United States", "hl": "en"},
    {"code": "GB", "name": "United Kingdom", "hl": "en"},
    {"code": "CA", "name": "Canada", "hl": "en"},
    {"code": "AU", "name": "Australia", "hl": "en"},
    {"code": "BR", "name": "Brazil", "hl": "pt"},
    {"code": "MX", "name": "Mexico", "hl": "es"},
    {"code": "AR", "name": "Argentina", "hl": "es"},
    {"code": "CO", "name": "Colombia", "hl": "es"},
    {"code": "CL", "name": "Chile", "hl": "es"},
    {"code": "ES", "name": "Spain", "hl": "es"},
    {"code": "FR", "name": "France", "hl": "fr"},
    {"code": "DE", "name": "Germany", "hl": "de"},
    {"code": "IT", "name": "Italy", "hl": "it"},
    {"code": "NL", "name": "Netherlands", "hl": "nl"},
    {"code": "TR", "name": "Turkey", "hl": "tr"},
    {"code": "SA", "name": "Saudi Arabia", "hl": "ar"},
    {"code": "AE", "name": "United Arab Emirates", "hl": "ar"},
    {"code": "EG", "name": "Egypt", "hl": "ar"},
    {"code": "MA", "name": "Morocco", "hl": "ar"},
    {"code": "QA", "name": "Qatar", "hl": "ar"},
    {"code": "KW", "name": "Kuwait", "hl": "ar"},
    {"code": "PK", "name": "Pakistan", "hl": "en"},
    {"code": "IN", "name": "India", "hl": "hi"},
    {"code": "BD", "name": "Bangladesh", "hl": "bn"},
    {"code": "ID", "name": "Indonesia", "hl": "id"},
    {"code": "JP", "name": "Japan", "hl": "ja"},
    {"code": "KR", "name": "South Korea", "hl": "ko"},
    {"code": "PH", "name": "Philippines", "hl": "en"},
    {"code": "NG", "name": "Nigeria", "hl": "en"},
    {"code": "ZA", "name": "South Africa", "hl": "en"},
]


NEWS_QUERY = {
    "ar": "أخبار",
    "bn": "খবর",
    "de": "Nachrichten",
    "en": "news",
    "es": "noticias",
    "fr": "actualités",
    "hi": "समाचार",
    "id": "berita",
    "it": "notizie",
    "ja": "ニュース",
    "ko": "뉴스",
    "nl": "nieuws",
    "pt": "notícias",
    "tr": "haberler",
}


def get(code: str) -> dict:
    code = (code or "").upper()
    for row in COUNTRIES:
        if row["code"] == code:
            return row
    return COUNTRIES[0]


def news_query(hl: str) -> str:
    lang = (hl or "en").split("-")[0]
    return NEWS_QUERY.get(lang, "news")
