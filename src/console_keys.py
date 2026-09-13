"""Console keys — platform/region classifier, AKS console pages, bucket table [R45].

R45 (Romain, 2026-09-12): the AKS feed tool will let us OVERWRITE the region — i.e. the
region/PLATFORM bucket — per target page, so console keys (Xbox One / Xbox Series X|S /
PS4 / PS5 / Nintendo Switch) become enterable. AKS has SEPARATE product pages per
platform (``buy-<slug>-<kind>-compare-prices/``, kind ∈ ``ps4 ps5 xbox-one xbox-series
nintendo-switch nintendo-switch-2``, PC = ``cd-key``), linked from a tab bar
``<ul class="aks-offer-tabulations">`` on every page of the game (verified read-only
2026-09-12: Hades PC 26712 · PS5 85105 · PS4 85104 · Xbox Series 85103 · Xbox One 85102 ·
Switch 47979).

This module is PURE (``re`` / ``dataclasses`` / ``typing`` / ``urllib.parse`` only; NO
``src.matcher`` import — the matcher imports us). It answers four questions, all
deterministic, all fail-closed (doubt → an explicit ``console: … (R45)`` skip reason,
never a guessed platform, never a partial family list):

1. ``classify_console(name, url, merchant)`` — what platform(s) does the MERCHANT declare
   for this feed row (title grammar first, URL grammar only when the title declares no
   generation), does it also name PC/Windows (Play Anywhere candidate), and what is the
   title once the console/store/region furniture is removed (``resolve_name`` — used for
   the AKS slug AND the R01/R16 identity guards; edition words are KEPT).
2. ``console_marker_in_url(url)`` — the fix for the real leak of 2026-09-11 (Gamivo
   "Riders Republic Premium Edition United States", platform ONLY in the URL
   ``…/riders-republic-xbox-xbox-one-series-us-premium``, entered as a PC PUBLISHER GLOBAL
   offer): the ``precheck_skip`` console gate read the TITLE only.
3. ``extract_console_pages(body)`` / ``extract_page_platform(body)`` — the tab bar of an
   AKS page → ``{kind: url}`` and the page's own platform meta.
4. ``console_page_identity(aks_name)`` — "Hades Xbox Series" → "Hades" so the console
   page identity can be compared with the anchor page (Elden Ring's Switch 2 tab points
   to ANOTHER product, "Elden Ring Tarnished Edition Nintendo Switch 2").

The bucket ids/labels come from the feed modal's region catalog (867 entries, identical on
9 catalogs 2026-09-10/12). Absent bucket = fail-closed: no Switch 2 bucket, no PS5 EU/US/UK,
no gift console bucket. Label ``306`` is the only one carrying a BOM (U+FEFF) in the master
text — ``CONSOLE_REGION_LABELS`` stores it WITHOUT the BOM (the rendered text has none).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

# ── §2 tables ────────────────────────────────────────────────────────────────────────
# Platform families = keys of REGION_IDS like the PC platforms. XBOX_PC is the Play
# Anywhere TARGET bucket family (never a merchant-declared family — merchants write
# "/ Windows", "PC/XBOX …"; the AKS PC page's "official platforms: Xbox Play Anywhere"
# decides, matcher §3.5.f).
CONSOLE_FAMILIES = ("XBOX_ONE", "XBOX_SERIES", "XBOX_PC", "PS4", "PS5", "SWITCH")
CONSOLE_PAGE_KIND = {
    "XBOX_ONE": "xbox-one", "XBOX_SERIES": "xbox-series", "XBOX_PC": "cd-key",
    "PS4": "ps4", "PS5": "ps5", "SWITCH": "nintendo-switch",
}
CONSOLE_PAGE_KINDS = ("ps4", "ps5", "xbox-one", "xbox-series", "nintendo-switch",
                      "nintendo-switch-2", "cd-key")
# family → {base region: catalog id} (§0 table; PS5 has ONE bucket — a "PS5 … [EU]" key
# has no bucket and fails closed in the matcher: "no region id for PS5/eu (R45)").
CONSOLE_REGION_IDS: dict[str, dict[str, str]] = {
    "XBOX_ONE": {"global": "24", "eu": "24eu", "us": "24us", "uk": "226"},
    "XBOX_SERIES": {"global": "300", "eu": "302", "us": "303", "uk": "305"},
    "XBOX_PC": {"global": "306", "eu": "241", "us": "242", "uk": "240"},
    "PS4": {"global": "88", "eu": "88eu", "us": "88us", "uk": "88uk"},
    "PS5": {"global": "88ps5h"},
    "SWITCH": {"global": "99", "eu": "99eu", "us": "99us", "uk": "992"},
}
# id → catalog master text WITHOUT the " (id)" suffix and WITHOUT the BOM, verbatim
# otherwise (capitalisation included: "Xbox Series Uk Game Code" is how AKS spells 305).
# The submitter types this text into Selectize and re-resolves the id live.
CONSOLE_REGION_LABELS: dict[str, str] = {
    "24": "Xbox One Game Code",
    "24eu": "Xbox Game Code EUROPE",
    "24us": "Xbox Game Code US",
    "226": "Xbox Game Code UK",
    "300": "Xbox Series",
    "302": "Xbox Series EU Game Code",
    "303": "Xbox Series US Game Code",
    "305": "Xbox Series Uk Game Code",
    "306": "Xbox/PC GLOBAL",
    "241": "XBOX/PC EU",
    "242": "XBOX/PC US",
    "240": "XBOX/PC UK",
    "88": "Playstation Game Code GLOBAL",
    "88eu": "Playstation Game Code EUROPE",
    "88us": "Playstation Game Code US",
    "88uk": "Playstation Game Code UK",
    "88ps5h": "PS5",
    "99": "NINTENDO GAME CODE GLOBAL",
    "99eu": "Nintendo GAME CODE EU",
    "99us": "Nintendo GAME CODE US",
    "992": "Nintendo GAME CODE UK",
}
CONSOLE_PLATFORM_LABEL = {
    "XBOX_ONE": "Xbox One", "XBOX_SERIES": "Xbox Series X|S",
    "XBOX_PC": "Xbox / PC (Play Anywhere)", "PS4": "PS4", "PS5": "PS5",
    "SWITCH": "Nintendo Switch",
}

# The families a MERCHANT can declare (never XBOX_PC, never Switch 2 — those are the
# matcher's target bucket and a skip respectively).
_DECLARABLE = ("XBOX_ONE", "XBOX_SERIES", "PS4", "PS5", "SWITCH")

# Reason strings (§2). Byte-exact — feed_status routes on the "console:" prefix.
SKIP_SWITCH_2 = "console: Switch 2 has no AKS bucket (R45)"
SKIP_XBOX_360 = "console: Xbox 360 (R45)"
SKIP_NO_GENERATION = "console: no declared generation (R45)"
SKIP_PC_ONLY = "console: PC-only Xbox Live key (R45)"


def _skip_not_a_game(marker: str) -> str:
    return f"console: {marker} — not a game (R45)"


@dataclass(frozen=True)
class ConsoleSignal:
    """What the merchant row declares about its console platform(s).

    ``families``: families DECLARED by the merchant, order of appearance, deduplicated,
    among XBOX_ONE / XBOX_SERIES / PS4 / PS5 / SWITCH (never XBOX_PC, never Switch 2).
    ``pc_declared``: the platform phrase names PC / Windows next to a console family
    ("Xbox Series X|S / Windows", "PC/XBOX One/Series X|S", "(Xbox Series X/S, PC)").
    ``resolve_name``: the title without its console/store/region markers (edition KEPT)
    — the slug source AND the text the R01/R16 identity guards read.
    ``skip_reason``: a fail-closed "console: … (R45)" skip, or None (families may be
    empty or not when a skip is set).
    """

    families: tuple[str, ...]
    pc_declared: bool
    resolve_name: str
    skip_reason: str | None


# ── title tokens ─────────────────────────────────────────────────────────────────────
# Same whole-word console tokens as matcher.CONSOLE_TOKENS (kept in sync by hand — this
# module must not import the matcher).
_TITLE_MARKER_TOKENS = ("XBOX", "PLAYSTATION", "PS4", "PS5", "PSN", "NINTENDO", "SWITCH")
# URL PATH tokens that prove a console row (dash/slash-delimited). SWITCH alone is NOT one
# (Kinguin "switch-galaxy-ultra-steam-cd-key" is a Steam game); NINTENDO/PSN/XBOX/… are.
_URL_MARKER_TOKENS = frozenset({"xbox", "playstation", "psn", "nintendo", "ps4", "ps5"})


def _padded_upper(text: str) -> str:
    """" GAME XBOX ONE " — punctuation → spaces, uppercased, padded (whole-word scans)."""

    return " " + re.sub(r"[^A-Z0-9]+", " ", text.upper()) + " "


def _path_tokens(url: str) -> list[str]:
    """Lower-case alnum tokens of the URL PATH (query dropped, never the stored URL)."""

    try:
        path = urlparse(url).path
    except ValueError:
        path = url
    return [t for t in re.split(r"[^a-z0-9]+", path.lower()) if t]


def console_marker_in_url(url: str) -> bool:
    """A console token in the URL PATH (XBOX / PLAYSTATION / PSN / NINTENDO / PS4 / PS5 as
    dash/slash segments; NOT a bare SWITCH) — the Gamivo/Eneba leak fix: those merchants
    carry the platform in the URL only ("…/riders-republic-xbox-xbox-one-series-us-premium").
    Hosts are irrelevant; the query string is ignored."""

    return any(t in _URL_MARKER_TOKENS for t in _path_tokens(url))


# ── title grammar ────────────────────────────────────────────────────────────────────
# One tokenizer for BOTH family extraction and resolve_name: a "furniture run" is a
# maximal sequence of platform / store / delivery / region items separated by
# " / , & + | - – — : ( ) [ ]" or spaces. Items are matched case-insensitively, EXCEPT the
# 2-letter region codes which must be UPPERCASE ("The Last of Us" must never lose "Us";
# Kinguin writes "US", "EU", "CA"). Longer alternatives come first (regex alternation).
#
# Every item alternative is a NAMED group so the parser knows what it hit:
#   xone / xseries / x360 / xbare / ps5 / ps4 / sw2 / switch / nbare / swbare / pc
#   store (XBOX LIVE, PSN, NINTENDO ESHOP, MICROSOFT STORE, PLAYSTATION NETWORK, NINTENDO…)
#   deliv (DOWNLOAD CODE, DIGITAL KEY, DIGITAL CODE, CD KEY)   weak (KEY, GIFT, ACCOUNT…)
#   region (EU, EUROPE, UNITED STATES, …)   lang ("EN", "EN/PL/CS" — Gamivo tails)
_XS = r"(?:\s*X\s*[|/]\s*S|\s*XS)"                       # "X|S" ≡ "X/S" ≡ "XS"
# Region words of the merchant grammars (long names case-insensitive; the 2-letter codes
# UPPERCASE only — "The Last of Us" must never lose "Us", Kinguin writes "US" / "EU" / "CA").
_REGION_ALT = (
    r"EUROPEAN\s+UNION|UNITED\s+STATES|UNITED\s+KINGDOM|NORTH\s+AMERICA|SOUTH\s+AFRICA|"
    r"HONG\s+KONG|MIDDLE\s+EAST|LATIN\s+AMERICA|UNITED\s+ARAB\s+EMIRATES|EU\s+WEST|EUROPE|"
    r"GLOBAL|WORLDWIDE|LATAM|EMEA|ASIA|CANADA|AUSTRALIA|ARGENTINA|TURKEY|POLAND|COLOMBIA|MEXICO|"
    r"JAPAN|GERMANY|AUSTRIA|ROMANIA|SINGAPORE|INDIA|BRAZIL|CHINA|KOREA|RUSSIA|USA|"
    r"(?-i:EU|US|UK|WW|NA|ROW|CA|AU|AR|TR|PL|CO|ZA|MX|JP|DE|AT|HK|SG|IN|BR|RU|GCC|CIS|UAE|EU/UK|EU/NA)"
)
_ITEM = (
    r"(?P<xone>XBOX\s+ONE)"
    r"|(?P<x360>XBOX\s+360)"
    r"|(?P<xseries>XBOX\s+SERIES(?:" + _XS + r"|\s+X\b|\s+S\b)?)"
    r"|(?P<series>SERIES" + _XS + r")"                    # "Xbox One / Series X|S"
    r"|(?P<store>XBOX\s+LIVE|PLAYSTATION\s+NETWORK|PSN|NINTENDO\s+ESHOP|ESHOP|MICROSOFT\s+STORE)"
    r"|(?P<xbare>XBOX)"
    r"|(?P<ps5>PLAYSTATION\s*5|PS5)"
    r"|(?P<ps4>PLAYSTATION\s*4|PS4)"
    r"|(?P<sw2>(?:NINTENDO\s+)?SWITCH\s+2)"
    r"|(?P<switch>NINTENDO\s+SWITCH)"
    r"|(?P<nbare>NINTENDO|PLAYSTATION)"
    r"|(?P<swbare>SWITCH)"
    r"|(?P<pc>PC|WINDOWS(?:\s*1[01])?)"
    r"|(?P<deliv>DOWNLOAD\s+CODE|DIGITAL\s+(?:KEY|CODE)|CD\s*KEY|OFFICIAL\s+KEY)"
    r"|(?P<weak>KEYS?|GIFT|ACCOUNT|ACCESS)"
    r"|(?P<region>" + _REGION_ALT + r")"
    r"|(?P<lang>(?-i:[A-Z]{2}(?:/[A-Z]{2})+))"           # "EN/PL/CS/RU/TR" (before a region)
)
_SEP = r"(?:\s*(?:[/,&+|:()\[\]]|-|–|—|\bAND\b|\bOR\b)\s*|\s+)"
# The run = optional opening bracket, an item, then (separator + item)*, optional closing
# bracket. The second item occurrence gets its group names prefixed ("z…") because Python
# refuses duplicate group names in one pattern; only the whole match is used from it.
_RUN_RE = re.compile(
    r"(?<![A-Z0-9'])(?:[(\[]\s*)?(?:" + _ITEM + r")(?![A-Z0-9])"
    r"(?:" + _SEP + r"+(?:" + _ITEM.replace("(?P<", "(?P<z") + r")(?![A-Z0-9]))*"
    r"(?:\s*[)\]])?",
    re.IGNORECASE,
)
# The same alternation, unnamed, to walk the items INSIDE a run.
_ITEM_RE = re.compile(r"(?<![A-Z0-9'])(?:" + _ITEM + r")(?![A-Z0-9])", re.IGNORECASE)

# Runs anchored by one of these groups are ALWAYS removed from resolve_name; a run made of
# weak / region / pc items only is removed when bracketed or at the TAIL of the title.
_ANCHOR_GROUPS = frozenset({"xone", "x360", "xseries", "series", "store", "xbare", "ps5",
                            "ps4", "sw2", "switch", "nbare", "deliv"})
_FAMILY_OF_GROUP = {"xone": "XBOX_ONE", "xseries": "XBOX_SERIES", "series": "XBOX_SERIES",
                    "ps5": "PS5", "ps4": "PS4", "switch": "SWITCH"}


def _item_group(match: "re.Match[str]") -> str:
    for name, value in match.groupdict().items():
        if value is not None:
            return name
    return ""            # unreachable: every alternative is a named group


@dataclass(frozen=True)
class _TitleParse:
    families: tuple[str, ...]
    pc_declared: bool
    switch_2: bool
    xbox_360: bool


def _parse_title(name: str) -> _TitleParse:
    """Families / PC flag / Switch 2 / Xbox 360 from EVERY platform run of the title."""

    families: list[str] = []
    pc_declared = False
    switch_2 = xbox_360 = False
    for run in _RUN_RE.finditer(name):
        run_families: list[str] = []
        run_pc = False
        for item in _ITEM_RE.finditer(run.group(0)):
            group = _item_group(item)
            if group == "sw2":
                switch_2 = True
            elif group == "x360":
                xbox_360 = True
            elif group == "pc":
                run_pc = True
            elif group in _FAMILY_OF_GROUP:
                run_families.append(_FAMILY_OF_GROUP[group])
        # PC/Windows counts only NEXT TO a declared console family (the same run) —
        # "PC Building Simulator (Xbox One)" is not a PC declaration.
        if run_pc and run_families:
            pc_declared = True
        for fam in run_families:
            if fam not in families:
                families.append(fam)
    return _TitleParse(tuple(families), pc_declared, switch_2, xbox_360)


# ── non-game markers ─────────────────────────────────────────────────────────────────
# Whole-word on the padded upper title. Currencies (V-BUCKS / VC / POINTS …) stay with
# CATEGORY_SKIP upstream; here only the console-store cards / subscriptions / accounts.
_NON_GAME_TITLE_RES = tuple(re.compile(p) for p in (
    r" GAME PASS ",
    r" XBOX LIVE GOLD ",
    r" XBOX LIVE CARDS? ",
    r" XBOX (?:LIVE )?GIFT CARDS? ",
    r" PSN CARDS? ",
    r" PLAYSTATION (?:NETWORK )?(?:CARDS?|CREDITS?|PLUS|STORE CARDS?|WALLET) ",
    r" PS PLUS ",
    r" (?:NINTENDO )?ESHOP CARDS? ",
    r" NINTENDO SWITCH ONLINE ",
    r" GIFT CARDS? ",                   # any gift card on a console row is a card
))
# MMOGA card / subscription CATEGORY segments (title may look like a game: "Xbox Game
# Pass Ultimate 1 Month [EU]" is filed under the Xbox-One / Xbox-360 GAME categories, the
# title marker catches those; these catch "PSN Card 80 Euro [Austria] - …").
_MMOGA_NON_GAME_CATEGORY_RE = re.compile(
    r"/(psn-cards(?:-[a-z]+)?|nintendo-eshop-cards|playstation-plus|xbox-live-cards|xbox-live-gold)/"
)


def _non_game_marker(name: str, url: str) -> str | None:
    padded = _padded_upper(name)
    for rx in _NON_GAME_TITLE_RES:
        m = rx.search(padded)
        if m:
            return m.group(0).strip()
    path = urlparse(url).path.lower()
    m = _MMOGA_NON_GAME_CATEGORY_RE.search(path)
    if m:
        return m.group(1).upper().replace("-", " ")
    if "gift-card" in path:
        return "GIFT CARD"
    # Kinguin console ACCOUNT / ACCESS listings (URL "-account" / "-online-account-
    # activation"; title "<x> Account" / "<x> Access") — never a key.
    if re.search(r"-account/?$", path) or re.search(r" ACCOUNT $", padded):
        return "ACCOUNT"
    if "online-account-activation" in path or re.search(r" ACCESS $", padded):
        return "ACCESS"          # "<Game> <Platform> Access" — the platform precedes the word
    return None


# ── URL grammar (only when the title declares no family) ─────────────────────────────
@dataclass(frozen=True)
class _UrlParse:
    families: tuple[str, ...] = ()
    pc_declared: bool = False
    skip_reason: str | None = None


_MMOGA_CATEGORY_RULES = (
    # (regex on the lower path, families, skip)
    (r"/xbox-live/xbox-360-game-keys/", (), SKIP_XBOX_360),
    (r"/xbox-live/xbox-one-game-keys/", ("XBOX_ONE",), None),
    (r"/xbox-live/xbox-series-xs-game-keys/", ("XBOX_SERIES",), None),
    (r"/playstation-network/playstation-5-game-keys/", ("PS5",), None),
    (r"/playstation-network/playstation-4-game-keys/", ("PS4",), None),
    (r"/nintendo/switch/", ("SWITCH",), None),
)


def _parse_url_mmoga(path: str) -> _UrlParse:
    """MMOGA: the platform CATEGORY segment (lower generation only — a cross-gen title is
    filed under Xbox-One-Game-Keys; the title phrase wins when present)."""

    for rx, families, skip in _MMOGA_CATEGORY_RULES:
        if re.search(rx, path):
            return _UrlParse(families=families, skip_reason=skip)
    return _UrlParse()


_GAMIVO_RUN_RE = re.compile(
    r"-xbox-(?:"
    r"(?P<oneseries>(?:xbox-)?one-series|xboxoneseries)(?P<pcw1>windows|-pc|-windows|-xbox-pc)?"
    r"|(?P<series>(?:xbox-)?series|xboxseries)(?P<pcw2>windows|-pc|-windows|-xbox-pc)?"
    r"|(?P<one>xboxone|one)(?P<pcw3>-pc|-windows)?"
    r"|(?P<pconly>pc)"
    r"|(?P<nogen>xbox-windows|xboxwindows)"
    r")-"
)
_GAMIVO_PS_RE = re.compile(r"-(?:ps|psn)-(?P<gen>ps4-ps5|ps5|ps4)-|-(?P<gen2>ps4-ps5)-")
_GAMIVO_NINTENDO_RE = re.compile(r"-nintendo-nintendo-switch(?P<two>-2)?-")


def _parse_url_gamivo(path: str) -> _UrlParse:
    """Gamivo: ``/product/<slug>-<platform run>-<cc>[-<langs>]-<edition>`` — the title
    NEVER carries the platform (569/572 console rows detected from the URL only)."""

    seg = "-" + path.rstrip("/").rsplit("/", 1)[-1] + "-"
    m = _GAMIVO_RUN_RE.search(seg)
    if m:
        if m.group("pconly"):
            return _UrlParse(skip_reason=SKIP_PC_ONLY)
        if m.group("nogen"):
            return _UrlParse()                    # "xbox-xbox-windows": Xbox + Windows, no generation
        pc = bool(m.group("pcw1") or m.group("pcw2") or m.group("pcw3"))
        if m.group("oneseries"):
            return _UrlParse(("XBOX_ONE", "XBOX_SERIES"), pc)
        if m.group("series"):
            return _UrlParse(("XBOX_SERIES",), pc)
        return _UrlParse(("XBOX_ONE",), pc)
    m = _GAMIVO_PS_RE.search(seg)
    if m:
        gen = m.group("gen") or m.group("gen2")
        return _UrlParse({"ps4-ps5": ("PS4", "PS5"), "ps5": ("PS5",), "ps4": ("PS4",)}[gen])
    m = _GAMIVO_NINTENDO_RE.search(seg)
    if m:
        if m.group("two"):
            return _UrlParse(skip_reason=SKIP_SWITCH_2)
        return _UrlParse(("SWITCH",))
    return _UrlParse()


def _parse_url_generic(tokens: list[str]) -> _UrlParse:
    """Dash-delimited runs: xbox-one, xbox-series(-x-s|-xs)?, xbox-one-series(-x-s)?,
    ps4, ps5, ps4-ps5, playstation-4/5, nintendo-switch(-2)?, xbox-360; a pc / windows
    token IMMEDIATELY before or after the run (same phrase) → pc_declared."""

    families: list[str] = []
    switch_2 = xbox_360 = False
    pc_adjacent = False
    run_positions: list[tuple[int, int]] = []       # (start, end) of family runs
    i = 0
    n = len(tokens)
    while i < n:
        t = tokens[i]
        nxt = tokens[i + 1] if i + 1 < n else ""
        start = i
        found: list[str] = []
        if t == "xbox" and nxt == "one":
            found.append("XBOX_ONE")
            i += 2
            # "xbox-one-series-x-s" (K4G) / "xbox-one-xbox-series-x-s" (Kinguin, Driffle)
            if i < n and tokens[i] == "xbox" and i + 1 < n and tokens[i + 1] == "series":
                found.append("XBOX_SERIES")
                i += 2
            elif i < n and tokens[i] == "series":
                found.append("XBOX_SERIES")
                i += 1
        elif t == "xbox" and nxt == "series":
            found.append("XBOX_SERIES")
            i += 2
        elif t == "xbox" and nxt == "360":
            xbox_360 = True
            i += 2
        elif t == "ps4" or (t == "playstation" and nxt == "4"):
            found.append("PS4")
            i += 2 if t == "playstation" else 1
        elif t == "ps5" or (t == "playstation" and nxt == "5"):
            found.append("PS5")
            i += 2 if t == "playstation" else 1
        elif t == "nintendo" and nxt == "switch":
            i += 2
            if i < n and tokens[i] == "2":
                switch_2 = True
                i += 1
            else:
                found.append("SWITCH")
        else:
            i += 1
            continue
        # swallow the "x-s" / "xs" / "x" spelling of Series
        while i < n and tokens[i] in ("x", "s", "xs"):
            i += 1
        for fam in found:
            if fam not in families:
                families.append(fam)
        run_positions.append((start, i))
    if families:
        # merge contiguous family runs (…-pc-ps5-ps4-xbox-series-x-s-xbox-one-…) and look
        # ONE token before the first / after the last for pc / windows.
        first = min(s for s, _ in run_positions)
        last = max(e for _, e in run_positions)
        before = tokens[first - 1] if first > 0 else ""
        after = tokens[last] if last < n else ""
        pc_adjacent = before in ("pc", "windows") or after in ("pc", "windows")
    if xbox_360:
        return _UrlParse(tuple(families), pc_adjacent, SKIP_XBOX_360)
    if switch_2:
        return _UrlParse(tuple(families), pc_adjacent, SKIP_SWITCH_2)
    return _UrlParse(tuple(families), pc_adjacent)


def _parse_url_eneba(path: str) -> _UrlParse:
    """Eneba: ``eneba.com/<store>-<slug>-<platform>-<store>-key-<region>``. The LEADING
    segment (``xbox-`` / ``psn-`` / ``nintendo-``) is the STORE, never a generation —
    ``xbox-one-last-breath-xbox-live-key-europe`` is the game "One Last Breath", not an
    Xbox One key (13/16 "Xbox One" rows of the 2026-09-12 batch were this artefact)."""

    tokens = _path_tokens(path)
    if tokens and tokens[0] in ("xbox", "psn", "nintendo"):
        tokens = tokens[1:]
    parsed = _parse_url_generic(tokens)
    if parsed.families or parsed.skip_reason:
        return parsed
    joined = "-" + "-".join(tokens) + "-"
    if "-pc-xbox-live-key-" in joined:
        return _UrlParse(skip_reason=SKIP_PC_ONLY)   # a PC key sold through Xbox Live / MS Store
    return _UrlParse()


def _parse_url(url: str, merchant: str) -> _UrlParse:
    try:
        parsed = urlparse(url)
    except ValueError:
        return _UrlParse()
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    merchant_key = (merchant or "").strip().upper()
    if host.endswith("mmoga.com") or merchant_key == "MMOGA":
        return _parse_url_mmoga(path)
    if host.endswith("gamivo.com") or merchant_key == "GAMIVO":
        return _parse_url_gamivo(path)
    if host.endswith("eneba.com") or merchant_key == "ENEBA":
        return _parse_url_eneba(path)
    return _parse_url_generic(_path_tokens(path))


# ── resolve_name ─────────────────────────────────────────────────────────────────────
# Gamivo "<Game> [<Edition>] EN[/DE/FR…] <Region>" tail: the language code(s) are dropped
# ONLY when a region word closes the title ("Kingdom Come Deliverance II Royal Edition EN
# Canada" keeps its "II"; "FIFA 23 EN/PL/CS/RU/TR EU" → "FIFA 23").
_GAMIVO_LANG_TAIL_RE = re.compile(
    r"\s+(?<![A-Za-z0-9])[A-Z]{2}(?:/[A-Z]{2})*(?=\s+(?:" + _REGION_ALT + r")\s*$)",
    re.IGNORECASE,
)
_EMPTY_BRACKETS_RE = re.compile(r"[(\[]\s*[)\]]")
_DANGLING_SEP_RE = re.compile(r"^\s*(?:[-–—:|,/&+]\s*)+|(?:\s*[-–—:|,/&+])+\s*$")
_DOUBLE_SEP_RE = re.compile(r"\s*([-–—:|])\s*(?:[-–—:|]\s*)+")


def _run_is_furniture(run: "re.Match[str]", text: str) -> bool:
    """Remove this run? Anchored runs (a console/store/delivery item) always; weak-only
    runs (region / PC / KEY / language) only when bracketed or at the tail — "The Last
    of Us" (mixed-case "Us" is not a code anyway) and "PC Building Simulator" survive."""

    groups = {_item_group(m) for m in _ITEM_RE.finditer(run.group(0))}
    if groups & _ANCHOR_GROUPS:
        return True
    body = run.group(0).strip()
    bracketed = body[:1] in "([" and body[-1:] in ")]"
    at_tail = text[run.end():].strip(" -–—:|,/&+\t") == ""
    return bracketed or at_tail


def _strip_furniture_runs(text: str) -> str:
    def repl(m: "re.Match[str]") -> str:
        return " " if _run_is_furniture(m, text) else m.group(0)

    return _RUN_RE.sub(repl, text)


def resolve_name_of(name: str) -> str:
    """The merchant title without its platform phrase (+ brackets), store / delivery
    markers, region tails and Gamivo language tail; edition words KEPT; separators
    normalised ("Game - - EU" → "Game"). Never empty: falls back to the input."""

    text = name.replace(" ", " ")
    text = _GAMIVO_LANG_TAIL_RE.sub(" ", text)          # "Ravenswatch EN United Kingdom"
    for _ in range(4):                                  # tails uncover more tails
        stripped = _strip_furniture_runs(text)
        stripped = _EMPTY_BRACKETS_RE.sub(" ", stripped)
        stripped = re.sub(r"\s+", " ", stripped).strip()
        stripped = _DANGLING_SEP_RE.sub("", stripped).strip()
        stripped = _DOUBLE_SEP_RE.sub(r" \1 ", stripped)
        stripped = _DANGLING_SEP_RE.sub("", re.sub(r"\s+", " ", stripped)).strip()
        if stripped == text:
            break
        text = stripped
    return text or name


# ── classify ─────────────────────────────────────────────────────────────────────────
def classify_console(name: str, url: str, merchant: str) -> ConsoleSignal | None:
    """The merchant's console declaration for one feed row, or None when the row carries
    NO console marker at all (title tokens XBOX / PLAYSTATION / PS4 / PS5 / PSN / NINTENDO
    / SWITCH, or ``console_marker_in_url``) — a PC row.

    Order (all fail-closed): non-game marker → skip; title grammar (Switch 2 / Xbox 360
    → skip); URL grammar ONLY when the title declares no family (MMOGA category, Gamivo
    run, Eneba run + leading segment, generic runs — may skip: Switch 2, Xbox 360, PC-only);
    still no family → "console: no declared generation (R45)" (Eneba's 704 "XBOX LIVE Key"
    rows, bare "PSN" / "Nintendo"). A skip never guesses: families may be partial there.
    """

    padded = _padded_upper(name)
    title_marker = any(f" {t} " in padded for t in _TITLE_MARKER_TOKENS)
    if not title_marker and not console_marker_in_url(url):
        return None
    resolve_name = resolve_name_of(name)
    marker = _non_game_marker(name, url)
    if marker:
        return ConsoleSignal((), False, resolve_name, _skip_not_a_game(marker))
    title = _parse_title(name)
    families = list(title.families)
    pc_declared = title.pc_declared
    if title.switch_2:
        return ConsoleSignal(tuple(families), pc_declared, resolve_name, SKIP_SWITCH_2)
    if title.xbox_360:
        return ConsoleSignal(tuple(families), pc_declared, resolve_name, SKIP_XBOX_360)
    if not families:
        from_url = _parse_url(url, merchant)
        if from_url.skip_reason:
            return ConsoleSignal(from_url.families, pc_declared or from_url.pc_declared,
                                 resolve_name, from_url.skip_reason)
        families = list(from_url.families)
        pc_declared = pc_declared or from_url.pc_declared
    if not families:
        return ConsoleSignal((), pc_declared, resolve_name, SKIP_NO_GENERATION)
    return ConsoleSignal(tuple(families), pc_declared, resolve_name, None)


# ── AKS page side ────────────────────────────────────────────────────────────────────
_PAGE_SUFFIX_RE = re.compile(
    r"\s*[(\[]?\s*(?:PS5|PS4|XBOX\s+SERIES(?:\s*X(?:\s*[|/]\s*S)?)?|XBOX\s+ONE|"
    r"NINTENDO\s+SWITCH\s*2|NINTENDO\s+SWITCH|SWITCH\s*2|SWITCH)\s*[)\]]?\s*$",
    re.IGNORECASE,
)


def console_page_identity(aks_name: str) -> str:
    """"Hades Xbox Series" → "Hades"; "Hades PS5" → "Hades"; "Elden Ring Tarnished Edition
    Nintendo Switch 2" → "Elden Ring Tarnished Edition"; "Hades" → "Hades". ONE trailing
    platform suffix is removed (AKS names its console pages "<game> <platform>")."""

    stripped = _PAGE_SUFFIX_RE.sub("", aks_name, count=1).strip()
    return stripped or aks_name


_TAB_BAR_RE = re.compile(r'<ul\s+class="aks-offer-tabulations"[^>]*>(.*?)</ul>', re.S | re.I)
_TAB_HREF_RE = re.compile(r'<a\s+[^>]*href="([^"]+)"', re.I)
_PAGE_KIND_RE = re.compile(
    r"/buy-(?P<slug>.+?)-(?P<kind>" + "|".join(sorted(CONSOLE_PAGE_KINDS, key=len, reverse=True))
    + r")-compare-prices/?$"
)


def extract_console_pages(body: str) -> dict[str, str]:
    """The tab bar ``<ul class="aks-offer-tabulations">`` → ``{kind: url}`` for every
    LINKED platform tab (kind ∈ CONSOLE_PAGE_KINDS). The active tab is a ``<span>`` without
    href (the page itself) → not listed. A tab may point to ANOTHER product (Elden Ring →
    "Elden Ring Tarnished Edition Nintendo Switch 2"): the caller re-checks identity.
    {} when the page has no tab bar. First link wins for a duplicated kind."""

    m = _TAB_BAR_RE.search(body)
    if not m:
        return {}
    pages: dict[str, str] = {}
    for href in _TAB_HREF_RE.findall(m.group(1)):
        href = href.strip().replace("&amp;", "&")
        km = _PAGE_KIND_RE.search(urlparse(href).path)
        if not km:
            continue
        pages.setdefault(km.group("kind"), href)
    return pages


_PLATFORM_META_RE = re.compile(r'<meta\s+data-itemprop="platform"\s+content="([^"]*)"', re.I)


def extract_page_platform(body: str) -> str:
    """``<meta data-itemprop="platform" content="PC" />`` → "PC" ("Xbox Series X", "PS5",
    "Switch" on console pages); "" when absent."""

    m = _PLATFORM_META_RE.search(body)
    return m.group(1).strip() if m else ""
