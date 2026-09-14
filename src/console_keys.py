"""Console keys — platform/region classifier, AKS console pages, bucket table [R45].

R45 (Romain, 2026-09-12): the AKS feed tool will let us OVERWRITE the region — i.e. the
region/PLATFORM bucket — per target page, so console keys (Xbox One / Xbox Series X|S /
PS4 / PS5 / Nintendo Switch / Nintendo Switch 2) become enterable. AKS has SEPARATE
product pages per platform (``buy-<slug>-<kind>-compare-prices/``, kind ∈ ``ps4 ps5
xbox-one xbox-series nintendo-switch nintendo-switch-2``, PC = ``cd-key``), linked from a
tab bar ``<ul class="aks-offer-tabulations">`` on every page of the game (verified
read-only 2026-09-12: Hades PC 26712 · PS5 85105 · PS4 85104 · Xbox Series 85103 · Xbox
One 85102 · Switch 47979; 2026-09-14: Street Fighter 6 Nintendo Switch 2 188436 · ELDEN
RING Tarnished Edition Nintendo Switch 2 188441).

Romain's ruling of 2026-09-14 (policy P1, DECIDED): « clé PS5 seule = page PS5 seulement,
pareil pour Xbox Series, PS4, Xbox One, Switch et Switch 2 » — a lone declared platform is
entered on THAT page only; a cross-gen declaration ("PS4 / PS5", "Xbox One / Series X|S")
on both pages. This module only DECLARES what the merchant row says; the matcher applies P1.

This module is PURE (``re`` / ``dataclasses`` / ``typing`` / ``urllib.parse`` only; NO
``src.matcher`` import — the matcher imports us). It answers four questions, all
deterministic, all fail-closed (doubt → an explicit ``console: … (R45)`` skip reason,
never a guessed platform, never a guessed region, never a partial family list):

1. ``classify_console(name, url, merchant)`` — what platform(s) does the MERCHANT declare
   for this feed row (title grammar first, URL grammar only when the title declares no
   generation), does it also name PC/Windows (Play Anywhere candidate), what is the title
   once the console/store/region furniture is removed (``resolve_name`` — used for the
   AKS slug AND the R01/R16 identity guards; edition words are KEPT), and WHAT REGION the
   merchant wrote next to the platform phrase (``region_base`` / ``region_label`` /
   ``region_words`` — the region slot, 2026-09-14: the adversarial review showed 456
   region-locked rows falling to implicit GLOBAL because the region word was stripped
   from the name and never mapped).
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
9 catalogs 2026-09-10/12). Absent bucket = fail-closed: no PS5 EU/US/UK, no gift console
bucket. Switch 2 (2026-09-14): the AKS Switch 2 pages carry the platform and their offers
use the NINTENDO family bucket (regions map {99: GLOBAL}, activationPlatform
nintendo-eshop) — SWITCH2 is a family with page kind ``nintendo-switch-2`` and the SAME
bucket ids as SWITCH. Label ``306`` is the only one carrying a BOM (U+FEFF) in the master
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
# decides, matcher §3.5.f). SWITCH2 (2026-09-14): its own AKS page kind, the Nintendo
# family bucket — the page decides the platform, the bucket the region.
CONSOLE_FAMILIES = ("XBOX_ONE", "XBOX_SERIES", "XBOX_PC", "PS4", "PS5", "SWITCH", "SWITCH2")
CONSOLE_PAGE_KIND = {
    "XBOX_ONE": "xbox-one", "XBOX_SERIES": "xbox-series", "XBOX_PC": "cd-key",
    "PS4": "ps4", "PS5": "ps5", "SWITCH": "nintendo-switch", "SWITCH2": "nintendo-switch-2",
}
CONSOLE_PAGE_KINDS = ("ps4", "ps5", "xbox-one", "xbox-series", "nintendo-switch",
                      "nintendo-switch-2", "cd-key")
# family → {base region: catalog id} (§0 table; PS5 has ONE bucket — a "PS5 … [EU]" key
# has no bucket and fails closed in the matcher: "no region id for PS5/EU (R45)").
# SWITCH2 shares the Nintendo bucket ids with SWITCH (verified on the Street Fighter 6 /
# ELDEN RING Tarnished Edition Switch 2 pages, 2026-09-14: prices region 99, regions map
# {99: GLOBAL}).
CONSOLE_REGION_IDS: dict[str, dict[str, str]] = {
    "XBOX_ONE": {"global": "24", "eu": "24eu", "us": "24us", "uk": "226"},
    "XBOX_SERIES": {"global": "300", "eu": "302", "us": "303", "uk": "305"},
    "XBOX_PC": {"global": "306", "eu": "241", "us": "242", "uk": "240"},
    "PS4": {"global": "88", "eu": "88eu", "us": "88us", "uk": "88uk"},
    "PS5": {"global": "88ps5h"},
    "SWITCH": {"global": "99", "eu": "99eu", "us": "99us", "uk": "992"},
    "SWITCH2": {"global": "99", "eu": "99eu", "us": "99us", "uk": "992"},
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
    "SWITCH": "Nintendo Switch", "SWITCH2": "Nintendo Switch 2",
}

# The families a MERCHANT can declare (never XBOX_PC — the matcher's target bucket).
_DECLARABLE = ("XBOX_ONE", "XBOX_SERIES", "PS4", "PS5", "SWITCH", "SWITCH2")

# Reason strings (§2). Byte-exact — feed_status routes on the "console:" prefix.
# SKIP_SWITCH_2 is RETIRED (2026-09-14: Switch 2 pages exist and use the Nintendo
# bucket) — the constant stays for importers, it is never emitted any more.
SKIP_SWITCH_2 = "console: Switch 2 has no AKS bucket (R45)"
SKIP_XBOX_360 = "console: Xbox 360 (R45)"
SKIP_NO_GENERATION = "console: no declared generation (R45)"
SKIP_PC_ONLY = "console: PC-only Xbox Live key (R45)"
# 2026-09-14 (review, finder 2 [low]): a SERIES / ONE token still glued to a separator
# once the platform phrase is removed means the grammar did not parse the whole phrase —
# never a partial console entry.
SKIP_RESIDUE = "console: unparsed platform residue (R45)"


def _skip_not_a_game(marker: str) -> str:
    return f"console: {marker} — not a game (R45)"


def _skip_edition_platform(phrase: str, families: tuple[str, ...]) -> str:
    """"<Game> - Nintendo Switch 2 Edition" filed under another platform (2026-09-14)."""

    return (f"console: product name suffix '{phrase} Edition' contradicts the declared "
            f"platform {'/'.join(families)} — not entered (R45)")


@dataclass(frozen=True)
class ConsoleSignal:
    """What the merchant row declares about its console platform(s) and region.

    ``families``: families DECLARED by the merchant, order of appearance, deduplicated,
    among XBOX_ONE / XBOX_SERIES / PS4 / PS5 / SWITCH / SWITCH2 (never XBOX_PC).
    ``pc_declared``: the platform phrase names PC / Windows next to a console family
    ("Xbox Series X|S / Windows", "PC/XBOX One/Series X|S", "(Xbox Series X/S, PC)").
    ``resolve_name``: the title without its console/store/region markers (edition KEPT)
    — the slug source AND the text the R01/R16 identity guards read.
    ``skip_reason``: a fail-closed "console: … (R45)" skip, or None (families may be
    empty or not when a skip is set).

    Region slot (2026-09-14, R45 review): the region the merchant writes NEXT TO the
    platform phrase — Kinguin/K4G "<Game> [Edition] <REGION> <Platform phrase> CD Key",
    Driffle "(<Region>)", G2A " - <REGION>" tail, Eneba "<STORE> Key <REGION>", MMOGA
    " - EU" / "[EU]" / "(… Key EU)" / "EU Key", Gamivo "EN <Region>" tail — read from
    the SAME furniture runs ``resolve_name`` strips, so every stripped region word is
    accounted for:
    ``region_words``: every region word/phrase stripped from the title, verbatim, in
    order ("US", "Europe", "United Kingdom", "Hong Kong"); () when none.
    ``region_base``: "eu" / "us" / "uk" / "global" when the stripped words all map to
    ONE sellable base; None otherwise.
    ``region_label``: the FORBIDDEN region label (matcher vocabulary: CANADA, AUSTRALIA,
    TURKEY, NORTH AMERICA, HONG KONG, ROW, …; an unknown word → its upper-cased text)
    when a stripped word is not sellable; None otherwise.
    Fail-closed contract for the matcher: ``region_base`` set → that bucket;
    ``region_label`` set → forbidden skip; ``region_words`` non-empty with NEITHER set
    (two different sellable bases, e.g. "EU (European Union + UK)") → the slot is not a
    single sellable base → skip; all empty → the merchant wrote no region next to the
    platform phrase (the generic title/URL scan may still speak, never a guess).
    """

    families: tuple[str, ...]
    pc_declared: bool
    resolve_name: str
    skip_reason: str | None
    region_base: str | None = None
    region_label: str | None = None
    region_words: tuple[str, ...] = ()


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


# ── region vocabulary (2026-09-14) ───────────────────────────────────────────────────
# Sellable bases = the CONSOLE_REGION_IDS keys. Keys are the upper-cased, space-normalised
# region words of the title grammar (``_REGION_ALT`` below).
_REGION_BASE_OF = {
    "EU": "eu", "EUROPE": "eu", "EUROPEAN UNION": "eu",
    "US": "us", "USA": "us", "UNITED STATES": "us",
    "UK": "uk", "GB": "uk", "UNITED KINGDOM": "uk",
    "GLOBAL": "global", "WORLDWIDE": "global", "WW": "global",
}
# 2-letter codes → the matcher's FORBIDDEN_REGIONS / _URL_FORBIDDEN_CODES labels (mirror
# of src/merchants/mmoga.py FORBIDDEN_CODES, extended with the codes the console feeds
# write before the platform phrase: Kinguin CA 83 / AU 77 / NA / TR / AR / CO / ZA on the
# 2026-09-12 batch). A full name maps to its own upper-cased text, which IS the matcher
# vocabulary (CANADA, NORTH AMERICA, HONG KONG, SOUTH AFRICA, …); an unknown word too, so
# the one router (aks_lists.suggest_target_list) files every label the same way.
_REGION_CODE_LABEL = {
    "RU": "RUSSIA", "TR": "TURKEY", "BR": "BRAZIL", "AR": "ARGENTINA", "CN": "CHINA",
    "KR": "KOREA", "JP": "JAPAN", "PL": "POLAND", "UA": "UKRAINE", "MX": "MEXICO",
    "PH": "PHILIPPINES", "VN": "VIETNAM", "TH": "THAILAND",
    "CA": "CANADA", "AU": "AUSTRALIA", "ZA": "SOUTH AFRICA", "NA": "NORTH AMERICA",
    "CO": "COLOMBIA", "SG": "SINGAPORE", "HK": "HONG KONG", "IN": "INDIA",
    "DE": "GERMANY", "AT": "AUSTRIA", "NL": "NETHERLANDS", "RO": "ROMANIA",
    "EU/NA": "EU NA",          # the matcher spells it "EU NA" (punctuation → space)
}


def _region_slot(words: tuple[str, ...]) -> tuple[str | None, str | None]:
    """``(region_base, region_label)`` from the stripped region words — see
    :class:`ConsoleSignal`. A forbidden / unknown word wins (its label); one sellable
    base → that base; two different sellable bases or nothing → (None, None)."""

    bases: list[str] = []
    labels: list[str] = []
    for word in words:
        key = re.sub(r"\s+", " ", word.upper()).strip()
        base = _REGION_BASE_OF.get(key)
        if base is not None:
            bases.append(base)
        else:
            labels.append(_REGION_CODE_LABEL.get(key, key))
    if labels:
        return None, labels[0]
    if len(set(bases)) == 1:
        return bases[0], None
    return None, None


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
# UPPERCASE only — "The Last of Us" must never lose "Us", Kinguin writes "US" / "EU" / "CA";
# "RoW" is Kinguin's own spelling, "Row" stays a name word). Multi-word names first.
# Every word here is mapped by ``_region_slot`` (base, forbidden label or its own text).
_REGION_ALT = (
    r"EUROPEAN\s+UNION|UNITED\s+STATES|UNITED\s+KINGDOM|UNITED\s+ARAB\s+EMIRATES|"
    r"NORTH\s+AMERICA|SOUTH\s+AMERICA|LATIN\s+AMERICA|SOUTH\s+AFRICA|SOUTH\s+KOREA|"
    r"SOUTH\s+EAST\s+ASIA|EASTERN\s+EUROPE|MIDDLE\s+EAST|HONG\s+KONG|NEW\s+ZEALAND|EU\s+WEST|"
    r"EUROPE|GLOBAL|WORLDWIDE|LATAM|EMEA|MENA|ASIA|AMERICAS|OCEANIA|"
    r"CANADA|AUSTRALIA|ARGENTINA|TURKEY|POLAND|COLOMBIA|MEXICO|JAPAN|GERMANY|AUSTRIA|"
    r"ROMANIA|SINGAPORE|INDIA|BRAZIL|CHINA|KOREA|RUSSIA|NETHERLANDS|UKRAINE|PHILIPPINES|"
    r"THAILAND|MALAYSIA|INDONESIA|SWITZERLAND|TAIWAN|CHILE|PERU|PORTUGAL|USA|"
    r"(?-i:EU/UK|EU/NA|EU|US|UK|GB|WW|NA|ROW|RoW|CA|AU|AR|TR|PL|CO|ZA|MX|JP|DE|AT|HK|SG|IN|BR|"
    r"RU|UA|KR|CN|PH|VN|TH|NL|RO|GCC|CIS|UAE)"        # "EU/NA" before "EU": one word, one lock
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
                    "ps5": "PS5", "ps4": "PS4", "switch": "SWITCH", "sw2": "SWITCH2"}

# 2026-09-14 (review, finder 2 [low]): a BARE "Series" (optionally "X" / "S") right after
# an "Xbox One" item in the same phrase IS Xbox Series X|S — "Xbox One/Series",
# "Xbox One & Series", "(Xbox One / Series)", "Xbox One / Series X". The title is
# normalised to the canonical "Series X|S" spelling BEFORE parsing, so both the family
# list and resolve_name see one grammar. A bare "Series" anywhere else stays a name word
# ("World Series of Poker").
_BARE_SERIES_RE = re.compile(
    r"(?<![A-Z0-9])(XBOX\s+ONE\s*(?:[/,&+|]|\bAND\b|\bOR\b)\s*)SERIES(?!" + _XS + r")"
    r"(?:\s+X\b|\s+S\b)?(?![A-Z0-9])",
    re.IGNORECASE,
)


def _normalise_title(name: str) -> str:
    text = name.replace(" ", " ")
    return _BARE_SERIES_RE.sub(r"\1Series X|S", text)


def _item_group(match: "re.Match[str]") -> str:
    for name, value in match.groupdict().items():
        if value is not None:
            return name
    return ""            # unreachable: every alternative is a named group


def _leading_name_run(run: "re.Match[str]", text: str) -> bool:
    """2026-09-14 (review, finder 3 [low]): a console run that OPENS the title and is
    immediately followed by a plain word is part of the GAME NAME — "Nintendo World
    Championships: NES Edition …", "Xbox Fitness (Xbox One …)", "PlayStation All-Stars
    Battle Royale EU PS4 CD Key", "Nintendo Switch Sports EU Nintendo Switch CD Key". It
    is kept in resolve_name and never counted as the family declaration (a title whose
    ONLY console run is such a name → "no declared generation"). A bracketed opening run
    ("(Xbox One) Game") is a platform phrase, not a name."""

    if text[:run.start()].strip():
        return False
    if run.group(0).lstrip()[:1] in "([":
        return False
    return re.match(r"\s+[A-Za-z0-9]", text[run.end():]) is not None


def _edition_name_run(run: "re.Match[str]", text: str) -> str | None:
    """2026-09-14: "<Game> - Nintendo Switch 2 Edition" (Instant Gaming, K4G) — a single
    platform item immediately followed by "Edition" is a PRODUCT NAME suffix, not a
    platform declaration: kept in resolve_name, not a family. Returns the family the
    suffix names (the declaration elsewhere must agree — fail-closed otherwise)."""

    if not re.match(r"\s+EDITION\b", text[run.end():], re.IGNORECASE):
        return None
    items = list(_ITEM_RE.finditer(run.group(0)))
    if len(items) != 1 or run.group(0).lstrip()[:1] in "([":
        return None
    return _FAMILY_OF_GROUP.get(_item_group(items[0]))


@dataclass(frozen=True)
class _TitleParse:
    families: tuple[str, ...]
    pc_declared: bool
    xbox_360: bool
    edition_families: tuple[str, ...] = ()      # "<Platform> Edition" name suffixes
    leading_tokens: tuple[str, ...] = ()        # tokens of a leading NAME run ("nintendo", "switch")


def _parse_title(name: str) -> _TitleParse:
    """Families / PC flag / Xbox 360 from EVERY platform run of the (normalised) title;
    a leading name run and "<Platform> Edition" name suffixes are reported apart."""

    families: list[str] = []
    pc_declared = False
    xbox_360 = False
    edition_families: list[str] = []
    leading_tokens: tuple[str, ...] = ()
    for run in _RUN_RE.finditer(name):
        if _leading_name_run(run, name):
            leading_tokens = tuple(t for t in re.split(r"[^a-z0-9]+", run.group(0).lower()) if t)
            continue
        edition_family = _edition_name_run(run, name)
        if edition_family is not None:
            edition_families.append(edition_family)
            continue
        run_families: list[str] = []
        run_pc = False
        for item in _ITEM_RE.finditer(run.group(0)):
            group = _item_group(item)
            if group == "x360":
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
    return _TitleParse(tuple(families), pc_declared, xbox_360, tuple(edition_families),
                       leading_tokens)


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
# ACCOUNT listings (2026-09-14, review finder 3 [high]): Kinguin "<x> Account" (title tail,
# URL "-account"), Difmark "<Game> (Account) Standard Edition" with URL
# "/buy-console-account-<slug>-nintendo-switch-account-<id>" — the word ANYWHERE in the
# title (parenthesised too), a "/buy-console-account-" path, or an "-account" / "-account-
# <digits>" path suffix. Never a key.
_ACCOUNT_PATH_RE = re.compile(r"(?:^|-)account(?:-\d+)?/?$")


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
    if (" ACCOUNT " in padded or "/buy-console-account-" in path
            or _ACCOUNT_PATH_RE.search(path)):
        return "ACCOUNT"
    # Kinguin console ACCESS listings (URL "-online-account-activation"; title
    # "<Game> <Platform> Access") — never a key either.
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
    # (regex on the lower path, families, skip). No Switch 2 category observed on MMOGA
    # as of 2026-09-14 — a "Nintendo Switch 2" title phrase declares it; a category-only
    # row under /Nintendo/Switch/ is a SWITCH declaration (the name-suffix guard in
    # classify_console refuses a "… - Nintendo Switch 2 Edition" filed there).
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
    NEVER carries the platform (569/572 console rows detected from the URL only). The
    region code after the run is read by the R46 hook (src/merchants/gamivo.py) and the
    title tail by the region slot here."""

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
            return _UrlParse(("SWITCH2",))        # 2026-09-14: Switch 2 pages exist
        return _UrlParse(("SWITCH",))
    return _UrlParse()


def _parse_url_generic(tokens: list[str]) -> _UrlParse:
    """Dash-delimited runs: xbox-one, xbox-series(-x-s|-xs)?, xbox-one-series(-x-s)?,
    ps4, ps5, ps4-ps5, playstation-4/5, nintendo-switch(-2)?, xbox-360; a pc / windows
    token IMMEDIATELY before or after the run (same phrase) → pc_declared."""

    families: list[str] = []
    xbox_360 = False
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
                found.append("SWITCH2")           # 2026-09-14: nintendo-switch-2 run
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
    return _UrlParse(tuple(families), pc_adjacent)


def _drop_mirrored_name(tokens: list[str], leading: tuple[str, ...]) -> list[str]:
    """A merchant slug mirrors the title: when the title OPENS with a console run that is
    part of the game name ("Nintendo Switch Sports"), the slug opens with the same tokens
    ("nintendo-switch-sports-…") — drop them so the URL grammar reads only a real
    platform slot ("…-nintendo-switch-cd-key"), never the name (2026-09-14)."""

    n = len(leading)
    if n and tuple(tokens[:n]) == leading:
        return tokens[n:]
    return tokens


def _parse_url_eneba(path: str, leading: tuple[str, ...] = ()) -> _UrlParse:
    """Eneba: ``eneba.com/<store>-<slug>-<platform>-<store>-key-<region>``. The LEADING
    segment (``xbox-`` / ``psn-`` / ``nintendo-``) is the STORE, never a generation —
    ``xbox-one-last-breath-xbox-live-key-europe`` is the game "One Last Breath", not an
    Xbox One key (13/16 "Xbox One" rows of the 2026-09-12 batch were this artefact)."""

    tokens = _path_tokens(path)
    if tokens and tokens[0] in ("xbox", "psn", "nintendo"):
        tokens = tokens[1:]
    tokens = _drop_mirrored_name(tokens, leading)
    parsed = _parse_url_generic(tokens)
    if parsed.families or parsed.skip_reason:
        return parsed
    joined = "-" + "-".join(tokens) + "-"
    if "-pc-xbox-live-key-" in joined:
        return _UrlParse(skip_reason=SKIP_PC_ONLY)   # a PC key sold through Xbox Live / MS Store
    return _UrlParse()


def _parse_url(url: str, merchant: str, leading: tuple[str, ...] = ()) -> _UrlParse:
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
        return _parse_url_eneba(path, leading)
    # generic: the slug is the LAST path segment (Kinguin "/category/<id>/<slug>")
    tokens = _path_tokens(path)
    seg_tokens = _path_tokens(path.rstrip("/").rsplit("/", 1)[-1])
    head = tokens[:len(tokens) - len(seg_tokens)] if seg_tokens else tokens
    return _parse_url_generic(head + _drop_mirrored_name(seg_tokens, leading))


# ── resolve_name ─────────────────────────────────────────────────────────────────────
# Gamivo "<Game> [<Edition>] EN[/DE/FR…] <Region>" tail: the language code(s) are dropped
# ONLY when a region word closes the title ("Kingdom Come Deliverance II Royal Edition EN
# Canada" keeps its "II"; "FIFA 23 EN/PL/CS/RU/TR EU" → "FIFA 23"). The region word itself
# is a tail run — stripped AND reported in region_words like every other grammar.
_GAMIVO_LANG_TAIL_RE = re.compile(
    r"\s+(?<![A-Za-z0-9])[A-Z]{2}(?:/[A-Z]{2})*(?=\s+(?:" + _REGION_ALT + r")\s*$)",
    re.IGNORECASE,
)
_EMPTY_BRACKETS_RE = re.compile(r"[(\[]\s*[)\]]")
_DANGLING_SEP_RE = re.compile(r"^\s*(?:[-–—:|,/&+]\s*)+|(?:\s*[-–—:|,/&+])+\s*$")
_DOUBLE_SEP_RE = re.compile(r"\s*([-–—:|])\s*(?:[-–—:|]\s*)+")
# A SERIES / ONE token glued to a phrase separator ("/Series", "& Series", "(Series",
# "Series)", "One /") once the furniture is gone = an unparsed platform phrase. "-" and
# ":" are ordinary name punctuation ("Season One - Ultra Edition"), a token between
# plain words is a name ("One Piece", "World Series of Poker") and so is a BALANCED
# standalone bracket ("Get Them Out! (Series)", 2 real Eneba rows) — only an unbalanced
# or separator-glued token is a residue.
_BALANCED_TOKEN_RE = re.compile(r"[(\[]\s*(?:SERIES|ONE)(?:\s+[XS])?\s*[)\]]", re.IGNORECASE)
_RESIDUE_RE = re.compile(
    r"[/&+|,(\[]\s*(?:SERIES|ONE)(?:\s+[XS])?(?![A-Z0-9])"
    r"|(?<![A-Z0-9])(?:SERIES|ONE)(?:\s+[XS])?\s*[/&+|,)\]]",
    re.IGNORECASE,
)


def _has_platform_residue(resolve_name: str) -> bool:
    return _RESIDUE_RE.search(_BALANCED_TOKEN_RE.sub(" ", resolve_name)) is not None


def _run_is_furniture(run: "re.Match[str]", text: str) -> bool:
    """Remove this run? Name runs (leading name, "<Platform> Edition" suffix) never;
    anchored runs (a console/store/delivery item) always; weak-only runs (region / PC /
    KEY / language) only when bracketed or at the tail — "The Last of Us" (mixed-case
    "Us" is not a code anyway) and "PC Building Simulator" survive."""

    if _leading_name_run(run, text) or _edition_name_run(run, text) is not None:
        return False
    groups = {_item_group(m) for m in _ITEM_RE.finditer(run.group(0))}
    if groups & _ANCHOR_GROUPS:
        return True
    body = run.group(0).strip()
    bracketed = body[:1] in "([" and body[-1:] in ")]"
    at_tail = text[run.end():].strip(" -–—:|,/&+\t") == ""
    return bracketed or at_tail


def _strip_furniture_runs(text: str) -> tuple[str, list[str]]:
    """The text without its furniture runs + the region words those runs carried."""

    regions: list[str] = []

    def repl(m: "re.Match[str]") -> str:
        if not _run_is_furniture(m, text):
            return m.group(0)
        for item in _ITEM_RE.finditer(m.group(0)):
            if _item_group(item) == "region":
                regions.append(item.group(0))
        return " "

    return _RUN_RE.sub(repl, text), regions


def resolve_name_and_regions(name: str) -> tuple[str, tuple[str, ...]]:
    """``(resolve_name, region_words)``: the merchant title without its platform phrase
    (+ brackets), store / delivery markers, region tails and Gamivo language tail; edition
    words KEPT; separators normalised ("Game - - EU" → "Game"); never empty (falls back to
    the input) — and every region word the strip removed, verbatim, in order."""

    text = _normalise_title(name)
    text = _GAMIVO_LANG_TAIL_RE.sub(" ", text)          # "Ravenswatch EN United Kingdom"
    regions: list[str] = []
    for _ in range(4):                                  # tails uncover more tails
        stripped, found = _strip_furniture_runs(text)
        regions.extend(found)
        stripped = _EMPTY_BRACKETS_RE.sub(" ", stripped)
        stripped = re.sub(r"\s+", " ", stripped).strip()
        stripped = _DANGLING_SEP_RE.sub("", stripped).strip()
        stripped = _DOUBLE_SEP_RE.sub(r" \1 ", stripped)
        stripped = _DANGLING_SEP_RE.sub("", re.sub(r"\s+", " ", stripped)).strip()
        if stripped == text:
            break
        text = stripped
    return (text or name), tuple(regions)


def resolve_name_of(name: str) -> str:
    """The merchant title without its furniture — see :func:`resolve_name_and_regions`."""

    return resolve_name_and_regions(name)[0]


# ── classify ─────────────────────────────────────────────────────────────────────────
def classify_console(name: str, url: str, merchant: str) -> ConsoleSignal | None:
    """The merchant's console declaration for one feed row, or None when the row carries
    NO console marker at all (title tokens XBOX / PLAYSTATION / PS4 / PS5 / PSN / NINTENDO
    / SWITCH, or ``console_marker_in_url``) — a PC row.

    Order (all fail-closed): non-game marker → skip; unparsed platform residue → skip;
    title grammar (Xbox 360 → skip; a leading name run / "<Platform> Edition" suffix is
    not a declaration); URL grammar ONLY when the title declares no family (MMOGA
    category, Gamivo run, Eneba run + leading segment, generic runs — may skip: Xbox 360,
    PC-only); still no family → "console: no declared generation (R45)" (Eneba's 704
    "XBOX LIVE Key" rows, bare "PSN" / "Nintendo", a name-only "Nintendo Switch 2
    Edition"); a name suffix naming another platform than the declaration → skip. The
    region slot (``region_base`` / ``region_label`` / ``region_words``) is filled on every
    signal, skip or not. A skip never guesses: families may be partial there.
    """

    padded = _padded_upper(name)
    title_marker = any(f" {t} " in padded for t in _TITLE_MARKER_TOKENS)
    if not title_marker and not console_marker_in_url(url):
        return None
    text = _normalise_title(name)
    resolve_name, region_words = resolve_name_and_regions(name)
    region_base, region_label = _region_slot(region_words)

    def signal(families: tuple[str, ...], pc: bool, skip: str | None) -> ConsoleSignal:
        return ConsoleSignal(families, pc, resolve_name, skip, region_base, region_label,
                             region_words)

    marker = _non_game_marker(name, url)
    if marker:
        return signal((), False, _skip_not_a_game(marker))
    if _has_platform_residue(resolve_name):
        return signal((), False, SKIP_RESIDUE)
    title = _parse_title(text)
    families = list(title.families)
    pc_declared = title.pc_declared
    if title.xbox_360:
        return signal(tuple(families), pc_declared, SKIP_XBOX_360)
    if not families:
        from_url = _parse_url(url, merchant, title.leading_tokens)
        if from_url.skip_reason:
            return signal(from_url.families, pc_declared or from_url.pc_declared,
                          from_url.skip_reason)
        families = list(from_url.families)
        pc_declared = pc_declared or from_url.pc_declared
    if not families:
        return signal((), pc_declared, SKIP_NO_GENERATION)
    for fam in title.edition_families:
        if fam not in families:
            return signal(tuple(families), pc_declared,
                          _skip_edition_platform(CONSOLE_PLATFORM_LABEL[fam], tuple(families)))
    return signal(tuple(families), pc_declared, None)


# ── AKS page side ────────────────────────────────────────────────────────────────────
_PAGE_SUFFIX_RE = re.compile(
    r"\s*[(\[]?\s*(?:PS5|PS4|XBOX\s+SERIES(?:\s*X(?:\s*[|/]\s*S)?)?|XBOX\s+ONE|"
    r"NINTENDO\s+SWITCH\s*2|NINTENDO\s+SWITCH|SWITCH\s*2|SWITCH)\s*[)\]]?\s*$",
    re.IGNORECASE,
)


def console_page_identity(aks_name: str) -> str:
    """"Hades Xbox Series" → "Hades"; "Hades PS5" → "Hades"; "Street Fighter 6 Nintendo
    Switch 2" → "Street Fighter 6"; "Elden Ring Tarnished Edition Nintendo Switch 2" →
    "Elden Ring Tarnished Edition"; "Hades" → "Hades". ONE trailing platform suffix is
    removed (AKS names its console pages "<game> <platform>")."""

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
    "Switch", "Switch 2" on console pages); "" when absent."""

    m = _PLATFORM_META_RE.search(body)
    return m.group(1).strip() if m else ""
