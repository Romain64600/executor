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

Shared vocabulary ONLY (R32 / R45, 2026-09-14 — Romain: « pour la détection région /
édition / plateforme, tu as un fichier de config par marchand. Et si tu ne l'as pas, tu
dois l'avoir. »). This module holds what every merchant shares: the platform phrase
grammar ("Xbox One / Series X|S", "PS4 / PS5", "Nintendo Switch 2", …), the families,
buckets and page kinds, the non-game markers, the store / delivery markers, the region
text → base / forbidden-label mapping, ``resolve_name``, the plain slug runs (xbox-one /
xbox-series(-x-s|-xs) / ps4 / ps5 / ps4-ps5 / nintendo-switch(-2) — slug vocabulary, not
a merchant grammar), the AKS tab-bar / page-platform extraction and the page identity.
Everything a merchant writes in its OWN way (a URL category segment, a fused run, a
leading store segment, a region tail, a language tail, a delivery phrase) is declared by
that merchant's ``MerchantConfig`` console hooks (``src/merchant_config.py``:
``console_url_families`` / ``console_pc_declared`` / ``console_region_slot`` /
``console_noise``, implemented in ``src/merchants/<merchant>.py``). This module names NO
merchant in code (tests/test_console_keys.py pins that) and reaches the registry
(``src.merchants.registry``) through a function-level import only — the merchant modules
import the shared vocabulary from here, never ``src.matcher`` (which imports us).

This module is PURE (``re`` / ``dataclasses`` / ``typing`` / ``urllib.parse`` only; NO
``src.matcher`` import). It answers four questions, all deterministic, all fail-closed
(doubt → an explicit ``console: … (R45)`` skip reason, never a guessed platform, never a
guessed region, never a partial family list):

1. ``classify_console(name, url, merchant)`` — what platform(s) does the MERCHANT declare
   for this feed row (shared title grammar first; the merchant's URL hook — or the shared
   slug runs when it has none — only when the title declares no generation), does it also
   name PC/Windows (Play Anywhere candidate), what is the title once the console/store/
   region furniture is removed (``resolve_name`` — used for the AKS slug AND the R01/R16
   identity guards; edition words are KEPT), and WHAT REGION the merchant wrote next to
   the platform phrase (``region_base`` / ``region_label`` / ``region_words`` — the region
   slot, 2026-09-14: the adversarial review showed 456 region-locked rows falling to
   implicit GLOBAL because the region word was stripped from the name and never mapped).
2. ``console_marker_in_url(url)`` — the fix for the real leak of 2026-09-11 (a Gamivo
   row "Riders Republic Premium Edition United States", platform ONLY in the URL
   ``…/riders-republic-xbox-xbox-one-series-us-premium``, entered as a PC PUBLISHER GLOBAL
   offer): the ``precheck_skip`` console gate read the TITLE only.
3. ``extract_console_pages(body)`` / ``extract_page_platform(body)`` — the tab bar of an
   AKS page → ``{kind: url}`` and the page's own platform meta.
4. ``console_page_identity(aks_name)`` — "Hades Xbox Series" → "Hades" so the console
   page identity can be compared with the anchor page (Elden Ring's Switch 2 tab points
   to ANOTHER product, "Elden Ring Tarnished Edition Nintendo Switch 2").

The bucket ids/labels come from the feed modal's region catalog (867 entries, identical on
9 catalogs 2026-09-10/12). Absent bucket = fail-closed: no gift console bucket (PS5 EU / US /
UK take the PlayStation buckets 88eu / 88us / 88uk since P3, Romain 2026-09-25). Switch 2
(2026-09-14): the AKS Switch 2 pages carry the platform and their offers
use the NINTENDO family bucket (regions map {99: GLOBAL}, activationPlatform
nintendo-eshop) — SWITCH2 is a family with page kind ``nintendo-switch-2`` and the SAME
bucket ids as SWITCH. Label ``306`` is the only one carrying a BOM (U+FEFF) in the master
text — ``CONSOLE_REGION_LABELS`` stores it WITHOUT the BOM (the rendered text has none).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Pattern, Sequence
from urllib.parse import unquote, urlparse

if TYPE_CHECKING:  # the registry is imported at call time only (see _config_of)
    from src.merchant_config import MerchantConfig

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
# family → {base region: catalog id} (§0 table). [P3] PS5 — DÉCIDÉ Romain 2026-09-25 (« P3
# A ») : GLOBAL garde sa case propre `88ps5h` « PS5 » ; Europe / US / UK prennent les cases
# PlayStation `88eu` / `88us` / `88uk`, celles de PS4. C'est ce qu'AKS fait déjà : lu en direct
# le 25/09 sur 10 pages PS5, 43 offres en `88eu` « EUROPE » et 41 en `88us` « USA » à côté de 96
# en `88ps5h` ; `88uk` « Playstation Game Code UK » est dans le catalogue du modal
# (runs/20260925-152525-auto/catalog.json). Avant : « no region id for PS5/EU (R45) ».
# SWITCH2 shares the Nintendo bucket ids with SWITCH (verified on the Street Fighter 6 /
# ELDEN RING Tarnished Edition Switch 2 pages, 2026-09-14: prices region 99, regions map
# {99: GLOBAL}).
CONSOLE_REGION_IDS: dict[str, dict[str, str]] = {
    "XBOX_ONE": {"global": "24", "eu": "24eu", "us": "24us", "uk": "226"},
    "XBOX_SERIES": {"global": "300", "eu": "302", "us": "303", "uk": "305"},
    "XBOX_PC": {"global": "306", "eu": "241", "us": "242", "uk": "240"},
    "PS4": {"global": "88", "eu": "88eu", "us": "88us", "uk": "88uk"},
    "PS5": {"global": "88ps5h", "eu": "88eu", "us": "88us", "uk": "88uk"},
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

# The families a MERCHANT can declare (never XBOX_PC — the matcher's target bucket). A
# merchant's ``console_url_families`` hook may only return these (validated, fail-closed).
DECLARABLE_FAMILIES = ("XBOX_ONE", "XBOX_SERIES", "PS4", "PS5", "SWITCH", "SWITCH2")
_DECLARABLE = DECLARABLE_FAMILIES

# Reason strings (§2). Byte-exact — feed_status routes on the "console:" prefix. The
# merchant modules import these for their ``console_url_families`` hook (2026-09-14).
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


def skip_not_a_game(marker: str) -> str:
    """The non-game skip reason for ``marker`` ("PSN CARD", "GAME PASS", "ACCOUNT", …) —
    shared by the title / URL markers here and the merchant category hooks."""

    return f"console: {marker} — not a game (R45)"


_skip_not_a_game = skip_not_a_game


def _skip_edition_platform(phrase: str, families: tuple[str, ...]) -> str:
    """"<Game> - Nintendo Switch 2 Edition" filed under another platform (2026-09-14)."""

    return (f"console: product name suffix '{phrase} Edition' contradicts the declared "
            f"platform {'/'.join(families)} — not entered (R45)")


def _skip_hook_result(detail: str) -> str:
    """A merchant hook answered something outside its contract — never a guess."""

    return f"console: merchant URL hook {detail} — not entered (R45)"


@dataclass(frozen=True)
class ConsoleSignal:
    """What the merchant row declares about its console platform(s) and region.

    ``families``: families DECLARED by the merchant, order of appearance, deduplicated,
    among XBOX_ONE / XBOX_SERIES / PS4 / PS5 / SWITCH / SWITCH2 (never XBOX_PC).
    ``pc_declared``: the platform phrase names PC / Windows next to a console family
    ("Xbox Series X|S / Windows", "PC/XBOX One/Series X|S", "(Xbox Series X/S, PC)"), or
    the merchant's own ``console_pc_declared`` hook says so.
    ``resolve_name``: the title without its console/store/region markers (edition KEPT)
    — the slug source AND the text the R01/R16 identity guards read.
    ``skip_reason``: a fail-closed "console: … (R45)" skip, or None (families may be
    empty or not when a skip is set).

    Region slot (2026-09-14, R45 review): the region the merchant writes NEXT TO the
    platform phrase — "<Game> [Edition] <REGION> <Platform phrase> CD Key", "(<Region>)",
    " - <REGION>" tail, "<STORE> Key <REGION>", " - EU" / "[EU]" / "(… Key EU)" /
    "EU Key", "EN <Region>" tail. The merchant's ``console_region_slot`` hook speaks
    FIRST (its own grammar, verbatim text); otherwise the shared tail / bracket reads
    report every region word ``resolve_name`` strips, so every stripped word is
    accounted for:
    ``region_words``: the region word(s), verbatim, in order ("US", "Europe", "United
    Kingdom", "Hong Kong"); () when none.
    ``region_base``: "eu" / "us" / "uk" / "global" when the words all map to ONE
    sellable base; None otherwise.
    ``region_label``: the FORBIDDEN region label (matcher vocabulary: CANADA, AUSTRALIA,
    TURKEY, NORTH AMERICA, HONG KONG, ROW, …; an unknown word → its upper-cased text)
    when a word is not sellable; None otherwise.
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


# ── merchant hooks (2026-09-14) ──────────────────────────────────────────────────────
def _config_of(merchant: str) -> "MerchantConfig | None":
    """The merchant's ``MerchantConfig`` (console hooks live there), or None.

    Function-level import on purpose: ``src.merchants.registry`` imports the merchant
    modules, which import THIS module's shared vocabulary — a module-level import here
    would be circular. ``src.matcher`` is never imported."""

    if not (merchant or "").strip():
        return None
    from src.merchants.registry import merchant_config

    return merchant_config(merchant)


def _compile_noise(noise: Sequence["str | Pattern[str]"]) -> tuple["Pattern[str]", ...]:
    """``console_noise`` entries → patterns: a str is a LITERAL phrase (case-insensitive,
    whole words, any whitespace between the words); a compiled pattern is used as is."""

    out: list["Pattern[str]"] = []
    for item in noise:
        if isinstance(item, str):
            words = [re.escape(w) for w in item.split()]
            if not words:
                continue
            out.append(re.compile(r"(?<![A-Za-z0-9])" + r"\s+".join(words) + r"(?![A-Za-z0-9])",
                                  re.IGNORECASE))
        else:
            out.append(item)
    return tuple(out)


# ── title tokens ─────────────────────────────────────────────────────────────────────
# Same whole-word console tokens as matcher.CONSOLE_TOKENS (kept in sync by hand — this
# module must not import the matcher).
_TITLE_MARKER_TOKENS = ("XBOX", "PLAYSTATION", "PS4", "PS5", "PSN", "NINTENDO", "SWITCH")
# URL PATH tokens that prove a console row (dash/slash-delimited). SWITCH alone is NOT one
# ("switch-galaxy-ultra-steam-cd-key" is a Steam game); NINTENDO/PSN/XBOX/… are.
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


def path_tokens(url: str) -> list[str]:
    """Public alias of the slug tokenizer for the merchant modules (2026-09-14)."""

    return _path_tokens(url)


def console_marker_in_url(url: str) -> bool:
    """A console token in the URL PATH (XBOX / PLAYSTATION / PSN / NINTENDO / PS4 / PS5 as
    dash/slash segments; NOT a bare SWITCH) — the 2026-09-11 leak fix: some merchants
    carry the platform in the URL only ("…/riders-republic-xbox-xbox-one-series-us-premium").
    Hosts are irrelevant; the query string is ignored."""

    return any(t in _URL_MARKER_TOKENS for t in _path_tokens(url))


# ── region vocabulary (2026-09-14) ───────────────────────────────────────────────────
# Sellable bases = the CONSOLE_REGION_IDS keys. Keys are the upper-cased, space-normalised
# region words of the title grammar (``_REGION_ALT`` below) — and whatever verbatim text a
# merchant's ``console_region_slot`` hook hands over.
_REGION_BASE_OF = {
    "EU": "eu", "EUROPE": "eu", "EUROPEAN UNION": "eu",
    "US": "us", "USA": "us", "UNITED STATES": "us",
    "UK": "uk", "GB": "uk", "UNITED KINGDOM": "uk",
    "GLOBAL": "global", "WORLDWIDE": "global", "WW": "global",
}
# 2-letter codes → the matcher's FORBIDDEN_REGIONS / _URL_FORBIDDEN_CODES labels (the
# same 2-letter vocabulary the merchant "<CODE> Key" grammars use, extended with the codes
# the console feeds write before the platform phrase: CA 83 / AU 77 / NA / TR / AR / CO /
# ZA on the 2026-09-12 batch). A full name maps to its own upper-cased text, which IS the
# matcher vocabulary (CANADA, NORTH AMERICA, HONG KONG, SOUTH AFRICA, …); an unknown word
# too, so the one router (aks_lists.suggest_target_list) files every label the same way.
_REGION_CODE_LABEL = {
    "RU": "RUSSIA", "TR": "TURKEY", "BR": "BRAZIL", "AR": "ARGENTINA", "CN": "CHINA",
    "KR": "KOREA", "JP": "JAPAN", "PL": "POLAND", "UA": "UKRAINE", "MX": "MEXICO",
    "PH": "PHILIPPINES", "VN": "VIETNAM", "TH": "THAILAND",
    "CA": "CANADA", "AU": "AUSTRALIA", "ZA": "SOUTH AFRICA", "NA": "NORTH AMERICA",
    "CO": "COLOMBIA", "SG": "SINGAPORE", "HK": "HONG KONG", "IN": "INDIA",
    "DE": "GERMANY", "AT": "AUSTRIA", "NL": "NETHERLANDS", "RO": "ROMANIA",
    "EU/NA": "EU NA",          # the matcher spells it "EU NA" (punctuation → space)
}


def region_slot_of(words: Sequence[str]) -> tuple[str | None, str | None]:
    """``(region_base, region_label)`` from region words / phrases — see
    :class:`ConsoleSignal`. A forbidden / unknown word wins (its label); one sellable
    base → that base; two different sellable bases or nothing → (None, None). The shared
    text → base / label mapping: the merchant hooks return TEXT, this maps it."""

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


def distinct_region_bases(words: Sequence[str]) -> tuple[str, ...]:
    """Les bases VENDABLES distinctes déclarées par ces mots, dans l'ordre d'apparition.

    Séparée de :func:`region_slot_of`, qui replie « plusieurs bases » et « aucun mot » sur le
    même ``(None, None)`` : le matcher doit pouvoir distinguer les deux, et NOMMER la
    contradiction quand il refuse (Romain, 2026-09-19 — « le classifieur détecte deux régions
    incompatibles » et le refus ne disait pas lesquelles). Les mots non vendables sont ignorés
    ici : un « GLOBAL CANADA » n'est pas une contradiction entre deux zones vendables, c'est
    un verrou interdit, et il garde son propre aiguillage.
    """

    out: list[str] = []
    for word in words:
        base = _REGION_BASE_OF.get(re.sub(r"\s+", " ", word.upper()).strip())
        if base is not None and base not in out:
            out.append(base)
    return tuple(out)


_region_slot = region_slot_of


# ── title grammar ────────────────────────────────────────────────────────────────────
# One tokenizer for BOTH family extraction and resolve_name: a "furniture run" is a
# maximal sequence of platform / store / delivery / region items separated by
# " / , & + | - – — : ( ) [ ]" or spaces. Items are matched case-insensitively, EXCEPT the
# 2-letter region codes which must be UPPERCASE ("The Last of Us" must never lose "Us";
# the feeds write "US", "EU", "CA"). Longer alternatives come first (regex alternation).
#
# Every item alternative is a NAMED group so the parser knows what it hit:
#   xone / xseries / x360 / xbare / ps5 / ps4 / sw2 / switch / nbare / swbare / pc
#   store (XBOX LIVE, PSN, NINTENDO ESHOP, MICROSOFT STORE, PLAYSTATION NETWORK, NINTENDO…)
#   deliv (DOWNLOAD CODE, DIGITAL KEY, DIGITAL CODE, CD KEY)   weak (KEY, GIFT, ACCOUNT…)
#   region (EU, EUROPE, UNITED STATES, …)
# A merchant's own furniture (a language tail, a delivery phrase) is declared by its
# ``console_noise`` hook and stripped BEFORE this grammar runs (2026-09-14).
_XS = r"(?:\s*X\s*[|/]\s*S|\s*XS)"                       # "X|S" ≡ "X/S" ≡ "XS"
# Region words of the merchant grammars (long names case-insensitive; the 2-letter codes
# UPPERCASE only — "The Last of Us" must never lose "Us", the feeds write "US" / "EU" /
# "CA"; "RoW" is one feed's own spelling, "Row" stays a name word). Multi-word names first.
# Every word here is mapped by ``region_slot_of`` (base, forbidden label or its own text).
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
    text = name.replace(" ", " ")
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
    """2026-09-14: "<Game> - Nintendo Switch 2 Edition" — a single platform item
    immediately followed by "Edition" is a PRODUCT NAME suffix, not a platform
    declaration: kept in resolve_name, not a family. Returns the family the suffix names
    (the declaration elsewhere must agree — fail-closed otherwise)."""

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
# A merchant's card / subscription URL CATEGORY (a title that may look like a game) is
# its own grammar: declared by its ``console_url_families`` hook (2026-09-14).
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
# ── ACCOUNT listings — THE detector of the whole pipeline (2026-09-25) ────────────────────
# An ACCOUNT is a product (login credentials), never a key: entering it on a key / game-code
# page is a wrong offer. ONE detector, used by the console classifier below, by
# ``matcher.is_account_offer`` / ``precheck_skip`` / the Difmark account branch, by the sort,
# and by the submitter's last guard before any write — no second classification system.
#
# Signals, in order of PRECEDENCE:
#   1. the title carries ACCOUNT as a whole word (punctuation-insensitive: "(Account)",
#      "Steam-Account", "... Account") → ``"title"``;
#   2. a merchant that DECLARES its own account grammar (``MerchantConfig.account_row`` —
#      Difmark) → ``"merchant"``: its URL is ITS business, never read by the generic token
#      below. At Difmark every URL carries « account » as TEMPLATE (« /buy-console-account-
#      … -steam-account-<id> », keys included — the reviewed decision of 2026-09-21 pinned by
#      ``test_une_vraie_cle_difmark_passe_toujours``), so the row goes to the ACCOUNT BRANCH,
#      where the merchant's own offer page decides account vs key (``matcher._pc_plan``);
#   3. otherwise the URL PATH carries ``account`` as a standalone token — URL-decoded,
#      lower-cased, split on every non-alphanumeric, ANYWHERE in the path (query string
#      ignored), after the merchant's declared URL noise (``url_ignore_substrings``) → ``"url"``.
# « accounting » / « accountant » are not the token. For every merchant without its own
# grammar, no trusted source states « key » explicitly, so nothing overrides signals 1 and 3:
# the default "key" reading only applies when none fires.
#
# Why "anywhere" (bug of 2026-09-24, reported by Romain): the first version read the path
# token only at the END ("-account" / "-account-<digits>"). Gamivo writes
# ``<game>-<platform>-account-<region>-<edition>`` —
# ``/product/hitman-2-xbox-one-series-account-global-standard``, title « Hitman 2 Global » —
# so the marker never fired and the ACCOUNT was entered as an « Xbox One Game Code » key.


def url_path_account_token(url: str, noise: Sequence[str] = ()) -> bool:
    """True iff the URL PATH carries ``account`` as a standalone token (see above). ``noise``
    = the merchant's ``url_ignore_substrings``, removed case-insensitively first (Difmark's
    ``buy-console-account-`` prefix is template, not a signal)."""

    try:
        path = urlparse(url or "").path
    except ValueError:
        path = str(url or "")
    path = unquote(path).lower()
    for piece in noise:
        if piece:
            path = path.replace(str(piece).lower(), "")
    return "account" in re.split(r"[^a-z0-9]+", path)


def title_account_marker(name: str) -> bool:
    """The whole word ACCOUNT in the title (punctuation-insensitive)."""

    return " ACCOUNT " in _padded_upper(name or "")


def account_signal(name: str, url: str, merchant: str = "") -> str | None:
    """Which explicit signal says this listing is an ACCOUNT — ``"merchant"`` (the
    merchant's ``account_row`` grammar), ``"title"`` or ``"url"`` — or None (then, and only
    then, the row may be read as a key). See the precedence note above."""

    if title_account_marker(name):
        return "title"
    cfg = _config_of(merchant)
    if cfg is not None and cfg.account_row is not None:
        return "merchant" if cfg.account_row(name, url) else None
    noise = tuple(cfg.url_ignore_substrings) if cfg is not None else ()
    if url_path_account_token(url, noise):
        return "url"
    return None


def is_account_listing(name: str, url: str, merchant: str = "") -> bool:
    """True when the title or the URL token says account (:func:`account_signal` ``"title"``
    / ``"url"``). The ``"merchant"`` hint of a merchant with its own account grammar is NOT
    enough: that merchant's page decides (see above)."""

    return account_signal(name, url, merchant) in ("title", "url")


def _non_game_marker(name: str, url: str) -> str | None:
    padded = _padded_upper(name)
    for rx in _NON_GAME_TITLE_RES:
        m = rx.search(padded)
        if m:
            return m.group(0).strip()
    path = urlparse(url).path.lower()
    if "gift-card" in path:
        return "GIFT CARD"
    if title_account_marker(name):
        return "ACCOUNT"
    # Console ACCESS listings (URL "-online-account-activation"; title "<Game> <Platform>
    # Access") — never a key either. Checked BEFORE the URL account token: that path
    # carries the token too, and its label has always been ACCESS.
    if "online-account-activation" in path:
        return "ACCESS"
    # The account token ANYWHERE in the path (no merchant here: no noise removed — the
    # historical "/buy-console-account-" prefix keeps counting, as it always did).
    if url_path_account_token(url):
        return "ACCOUNT"
    if re.search(r" ACCESS $", padded):
        return "ACCESS"          # "<Game> <Platform> Access" — the platform precedes the word
    return None


# ── shared slug runs (only when the title declares no family) ────────────────────────
@dataclass(frozen=True)
class SlugRead:
    """What the plain slug runs of a hyphenated URL declare — the SHARED slug vocabulary
    (xbox-one, xbox-series(-x-s|-xs), xbox-one-series(-x-s), xbox-one-xbox-series-x-s,
    ps4, ps5, ps4-ps5, playstation-4/5, nintendo-switch(-2), xbox-360). ``span`` is the
    ``(start, end)`` token index range covering every family run (None when none) —
    a merchant hook uses it to check the run sits in ITS platform slot."""

    families: tuple[str, ...] = ()
    pc_declared: bool = False
    skip_reason: str | None = None
    span: tuple[int, int] | None = None


_UrlParse = SlugRead


def slug_families(tokens: Sequence[str]) -> SlugRead:
    """Dash-delimited runs over lower-case tokens: xbox-one, xbox-series(-x-s|-xs)?,
    xbox-one-series(-x-s)?, ps4, ps5, ps4-ps5, playstation-4/5, nintendo-switch(-2)?,
    xbox-360 (→ skip); a pc / windows token IMMEDIATELY before or after the run (same
    phrase) → pc_declared. Shared slug vocabulary — the merchant modules call it on the
    slot their own grammar locates (2026-09-14)."""

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
            # "xbox-one-series-x-s" / "xbox-one-xbox-series-x-s"
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
    span: tuple[int, int] | None = None
    if families:
        # merge contiguous family runs (…-pc-ps5-ps4-xbox-series-x-s-xbox-one-…) and look
        # ONE token before the first / after the last for pc / windows.
        first = min(s for s, _ in run_positions)
        last = max(e for _, e in run_positions)
        before = tokens[first - 1] if first > 0 else ""
        after = tokens[last] if last < n else ""
        pc_adjacent = before in ("pc", "windows") or after in ("pc", "windows")
        span = (first, last)
    if xbox_360:
        return SlugRead(tuple(families), pc_adjacent, SKIP_XBOX_360, span)
    return SlugRead(tuple(families), pc_adjacent, None, span)


_parse_url_generic = slug_families


def _drop_mirrored_name(tokens: list[str], leading: tuple[str, ...]) -> list[str]:
    """A merchant slug mirrors the title: when the title OPENS with a console run that is
    part of the game name ("Nintendo Switch Sports"), the slug opens with the same tokens
    ("nintendo-switch-sports-…") — drop them so the slug runs read only a real platform
    slot ("…-nintendo-switch-cd-key"), never the name (2026-09-14)."""

    n = len(leading)
    if n and tuple(tokens[:n]) == leading:
        return tokens[n:]
    return tokens


def _generic_url_read(url: str, leading: tuple[str, ...] = ()) -> SlugRead:
    """The shared slug reading for a merchant WITHOUT a ``console_url_families`` hook:
    the slug is the LAST path segment ("/category/<id>/<slug>"), the mirrored leading
    name dropped, then the plain slug runs. Hosts are irrelevant."""

    try:
        path = urlparse(url).path.lower()
    except ValueError:
        return SlugRead()
    tokens = _path_tokens(path)
    seg_tokens = _path_tokens(path.rstrip("/").rsplit("/", 1)[-1])
    head = tokens[:len(tokens) - len(seg_tokens)] if seg_tokens else tokens
    return slug_families(head + _drop_mirrored_name(seg_tokens, leading))


def _hook_url_read(cfg: "MerchantConfig", url: str) -> tuple[tuple[str, ...], str | None]:
    """``(families, skip_reason)`` from the merchant's ``console_url_families`` hook,
    validated: a None → nothing declared; a "console: …" string → that skip; families
    must be declarable (never XBOX_PC, never an unknown token) — anything else is a
    fail-closed skip, never a guess (2026-09-14)."""

    declared = cfg.console_url_families(url)  # type: ignore[misc]
    if declared is None:
        return (), None
    if isinstance(declared, str):
        if declared.startswith("console:"):
            return (), declared
        return (), _skip_hook_result(f"returned {declared!r}")
    families: list[str] = []
    for fam in declared:
        if fam not in _DECLARABLE:
            return (), _skip_hook_result(f"declared unknown platform {fam!r}")
        if fam not in families:
            families.append(fam)
    return tuple(families), None


def _hook_pc_declared(cfg: "MerchantConfig | None", name: str, url: str) -> bool:
    if cfg is None or cfg.console_pc_declared is None:
        return False
    return bool(cfg.console_pc_declared(name, url))


def _hook_region_slot(cfg: "MerchantConfig | None", name: str) -> str | None:
    if cfg is None or cfg.console_region_slot is None:
        return None
    text = cfg.console_region_slot(name)
    return text.strip() if isinstance(text, str) and text.strip() else None


# ── resolve_name ─────────────────────────────────────────────────────────────────────
_EMPTY_BRACKETS_RE = re.compile(r"[(\[]\s*[)\]]")
_DANGLING_SEP_RE = re.compile(r"^\s*(?:[-–—:|,/&+]\s*)+|(?:\s*[-–—:|,/&+])+\s*$")
_DOUBLE_SEP_RE = re.compile(r"\s*([-–—:|])\s*(?:[-–—:|]\s*)+")
# A SERIES / ONE token glued to a phrase separator ("/Series", "& Series", "(Series",
# "Series)", "One /") once the furniture is gone = an unparsed platform phrase. "-" and
# ":" are ordinary name punctuation ("Season One - Ultra Edition"), a token between
# plain words is a name ("One Piece", "World Series of Poker") and so is a BALANCED
# standalone bracket ("Get Them Out! (Series)", 2 real rows) — only an unbalanced or
# separator-glued token is a residue.
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
    KEY) only when bracketed or at the tail — "The Last of Us" (mixed-case "Us" is not a
    code anyway) and "PC Building Simulator" survive."""

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


def _merchant_noise(merchant: str) -> tuple["Pattern[str]", ...]:
    cfg = _config_of(merchant)
    if cfg is None or not cfg.console_noise:
        return ()
    return _compile_noise(cfg.console_noise)


def resolve_name_and_regions(name: str, merchant: str = "") -> tuple[str, tuple[str, ...]]:
    """``(resolve_name, region_words)``: the merchant title without its platform phrase
    (+ brackets), store / delivery markers and region tails; the merchant's own
    ``console_noise`` (a language tail, a delivery phrase) stripped FIRST when
    ``merchant`` names a configured merchant; edition words KEPT; separators normalised
    ("Game - - EU" → "Game"); never empty (falls back to the input) — and every region
    word the shared strip removed, verbatim, in order."""

    text = _normalise_title(name)
    for rx in _merchant_noise(merchant):
        text = rx.sub(" ", text)
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


def resolve_name_of(name: str, merchant: str = "") -> str:
    """The merchant title without its furniture — see :func:`resolve_name_and_regions`."""

    return resolve_name_and_regions(name, merchant)[0]


# ── classify ─────────────────────────────────────────────────────────────────────────
def classify_console(name: str, url: str, merchant: str) -> ConsoleSignal | None:
    """The merchant's console declaration for one feed row, or None when the row carries
    NO console marker at all (title tokens XBOX / PLAYSTATION / PS4 / PS5 / PSN / NINTENDO
    / SWITCH, or ``console_marker_in_url``) — a PC row.

    Order (all fail-closed): shared non-game marker → skip; unparsed platform residue →
    skip; shared title grammar (Xbox 360 → skip; a leading name run / "<Platform>
    Edition" suffix is not a declaration); the URL ONLY when the title declares no
    family — the merchant's ``console_url_families`` hook when it has one (may skip:
    Xbox 360, PC-only, a card / subscription category), else the shared slug runs;
    still no family → "console: no declared generation (R45)" (bare "PSN" /
    "Nintendo", a name-only "Nintendo Switch 2 Edition"); a name suffix naming another
    platform than the declaration → skip. ``pc_declared`` = the shared title phrase
    check OR the merchant's ``console_pc_declared`` hook (OR, for a merchant without
    hooks, a pc / windows token next to the shared slug run). The region slot
    (``region_base`` / ``region_label`` / ``region_words``) is filled on every signal,
    skip or not: the merchant's ``console_region_slot`` hook first, else the shared
    tail / bracket reads. ``resolve_name`` strips the merchant's ``console_noise``
    first. A skip never guesses: families may be partial there. The merchant is looked
    up by NAME in the registry — the URL host is irrelevant (2026-09-14).
    """

    padded = _padded_upper(name)
    title_marker = any(f" {t} " in padded for t in _TITLE_MARKER_TOKENS)
    if not title_marker and not console_marker_in_url(url):
        return None
    cfg = _config_of(merchant)
    text = _normalise_title(name)
    resolve_name, stripped_words = resolve_name_and_regions(name, merchant)
    slot_text = _hook_region_slot(cfg, name)
    region_words = (slot_text,) if slot_text is not None else stripped_words
    region_base, region_label = region_slot_of(region_words)

    def signal(families: tuple[str, ...], pc: bool, skip: str | None) -> ConsoleSignal:
        return ConsoleSignal(families, pc, resolve_name, skip, region_base, region_label,
                             region_words)

    marker = _non_game_marker(name, url)
    if marker:
        return signal((), False, skip_not_a_game(marker))
    if _has_platform_residue(resolve_name):
        return signal((), False, SKIP_RESIDUE)
    title = _parse_title(text)
    families = list(title.families)
    pc_declared = title.pc_declared
    if title.xbox_360:
        return signal(tuple(families), pc_declared, SKIP_XBOX_360)
    if not families:
        if cfg is not None and cfg.console_url_families is not None:
            declared, skip = _hook_url_read(cfg, url)
            if skip:
                return signal(declared, pc_declared or _hook_pc_declared(cfg, name, url), skip)
            families = list(declared)
            # AUDIT DU 2026-09-18 : la branche SANS hook complète `pc_declared` avec la lecture
            # générique du slug, la branche AVEC hook non — or les quatre marchands qui ont un
            # `console_url_families` (G2A, GameSeal, Driffle, K4G) CONSOMMENT le jeton `pc`
            # dans leur propre expression et jettent l'information, et aucun ne déclare
            # `console_pc_declared`. La garde P2 de §4.12 (« Xbox + PC sans Play Anywhere
            # vérifié ») ne pouvait donc jamais se déclencher chez eux. On complète le signal
            # de la même façon, sauf si le marchand a explicitement pris la main en déclarant
            # son propre `console_pc_declared` — ce qu'aucun ne fait aujourd'hui.
            if cfg.console_pc_declared is None:
                pc_declared = pc_declared or _generic_url_read(url, title.leading_tokens).pc_declared
        else:
            read = _generic_url_read(url, title.leading_tokens)
            if read.skip_reason:
                return signal(read.families, pc_declared or read.pc_declared, read.skip_reason)
            families = list(read.families)
            pc_declared = pc_declared or read.pc_declared
    pc_declared = pc_declared or _hook_pc_declared(cfg, name, url)
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


# AUDIT DU 2026-09-18 : `page_platform` était EXTRAIT puis JETÉ. Le seul contrôle d'une page
# cible console était une comparaison de NOMS — or `console_page_identity` retire précisément
# le suffixe de plateforme, donc « Hades PS4 », « Hades PS5 » et « Hades » sont tous égaux à
# « Hades » : une barre d'onglets qui pointe sur la page d'une AUTRE génération passait. La
# méta de la page, elle, le dit. Table bâtie sur le vocabulaire de la MÉTA (pas sur les titres
# d'onglets, qui en diffèrent : l'onglet dit « Xbox Series », la méta « Xbox Series X »).
# FAIL-CLOSED PRUDENT : une méta absente ou inconnue ne prouve RIEN et ne refuse rien ; seule
# une méta qui nomme explicitement une AUTRE famille fait échouer la cible.
PAGE_PLATFORM_FAMILY: dict[str, str] = {
    "PC": "XBOX_PC",
    "PS4": "PS4",
    "PS5": "PS5",
    "XBOX ONE": "XBOX_ONE",
    "XBOX SERIES": "XBOX_SERIES",
    "XBOX SERIES X": "XBOX_SERIES",
    "XBOX SERIES X|S": "XBOX_SERIES",
    "SWITCH": "SWITCH",
    "NINTENDO SWITCH": "SWITCH",
    "SWITCH 2": "SWITCH2",
    "NINTENDO SWITCH 2": "SWITCH2",
}


def page_platform_family(text: str) -> str | None:
    """La famille que la MÉTA de la page revendique, ou None si elle ne dit rien d'exploitable."""

    return PAGE_PLATFORM_FAMILY.get(re.sub(r"\s+", " ", (text or "").strip()).upper())


def extract_page_platform(body: str) -> str:
    """``<meta data-itemprop="platform" content="PC" />`` → "PC" ("Xbox Series X", "PS5",
    "Switch", "Switch 2" on console pages); "" when absent."""

    m = _PLATFORM_META_RE.search(body)
    return m.group(1).strip() if m else ""
