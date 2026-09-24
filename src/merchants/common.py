"""Pieces shared by the merchant modules (2026-09-14, Romain's rule — R32 / R45).

Romain (2026-08-11, repeated until the 2026-09-14 ultimatum): « pour la détection région /
édition / plateforme, tu as un fichier de config par marchand. Et si tu ne l'as pas, tu
dois l'avoir. » Each ``src/merchants/<merchant>.py`` DECLARES that merchant's grammar and
implements its deterministic hooks. This module holds only what several of those files
need and that must NOT be imported from the generic layers — a merchant file never imports
``src.matcher`` nor ``src.console_keys`` (both reach the merchant registry, so the import
would be circular):

* the region-word vocabulary the merchant grammars share — the sellable words → the
  ``REGION_IDS`` base (eu / us / uk / global) and the region locks → the matcher's
  ``forbidden region: <LABEL>`` label vocabulary (``FORBIDDEN_REGIONS`` /
  ``_URL_FORBIDDEN_CODES``), i.e. the labels ``aks_lists.suggest_target_list`` routes
  (CANADA / AUSTRALIA / MIDDLE EAST / AFRICA → their list, LATAM / Brazil / Asia / Russia /
  Poland / Ukraine → Blacklist, the rest → garder). Mirror of the console classifier's
  ``_REGION_BASE_OF`` / ``_REGION_CODE_LABEL`` tables and of ``src/merchants/gamivo.py``
  ``SELLABLE_TAILS`` / ``FORBIDDEN_TAILS`` — kept in sync by hand (no import possible);
* the console skip-reason strings of the R45 hook contract (byte-exact mirrors of
  ``src.console_keys`` — ``feed_status`` routes on the ``console:`` prefix);
* :func:`make_config` — the ``MerchantConfig`` constructor tolerant to the console hooks
  (``console_url_families`` / ``console_pc_declared`` / ``console_region_slot`` /
  ``console_noise``) not yet being fields of the dataclass (agent M1 adds them,
  2026-09-14): a hook is passed only when its field exists (``dataclasses.fields``),
  otherwise it is recorded under ``extra["console_hooks_pending"]`` so the integrator sees
  what the module declares. Every merchant module imports either way.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Any

from src.merchant_config import MerchantConfig

# ── console skip reasons (R45 contract, mirrors of src.console_keys) ─────────────────
SKIP_XBOX_360 = "console: Xbox 360 (R45)"
SKIP_PC_ONLY = "console: PC-only Xbox Live key (R45)"


def skip_not_a_game(marker: str) -> str:
    """``"console: <MARKER> — not a game (R45)"`` — the shared non-game console reason
    (ACCOUNT / ACCESS / GIFT CARD / GAME PASS …)."""

    return f"console: {marker} — not a game (R45)"


# ── region vocabulary ────────────────────────────────────────────────────────────────
# Sellable region words → detect_region base (REGION_IDS keys). Keys are upper-cased,
# space-normalised; the 2/3-letter codes are only read when the merchant WROTE them in
# capitals (see region_kind — "The Last of Us" never loses "Us").
SELLABLE_WORDS: dict[str, str] = {
    "EU": "eu", "EUROPE": "eu", "EUROPEAN UNION": "eu",
    "US": "us", "USA": "us", "UNITED STATES": "us",
    "UK": "uk", "GB": "uk", "UNITED KINGDOM": "uk",
    "GLOBAL": "global", "WORLDWIDE": "global", "WW": "global",
}
# Region locks → the matcher's label vocabulary (FORBIDDEN_REGIONS / _URL_FORBIDDEN_CODES /
# the console classifier's _REGION_CODE_LABEL). A full name maps to its own upper-cased
# text — that IS the matcher vocabulary (CANADA, NORTH AMERICA, HONG KONG, …). Observed
# on the 2026-09-12 batches: Kinguin CA 83 / AU 77 / RoW 15 / TR 11 / NA 9 / SEA 7 / AR /
# CO / ZA / DE / UAE / ANZ; K4G North America 42 / Mexico / United Arab Emirates /
# Luxembourg / Denmark; Driffle Asia / MENA / Turkey / Germany / France / Austria /
# Netherlands / Belgium / Egypt / Hong Kong / Romania / Latvia / Lithuania / SIEE (not a
# region); G2A NORTH AMERICA 132 / MENA / CANADA / CIS / CHINA / SINGAPORE / SOUTH AFRICA /
# GERMANY / JAPAN / TURKEY / ROW / POLAND; GameSeal CANADA / ROW / EMEA / BELGIUM / AU /
# EU/NA (July 2026 sweep).
FORBIDDEN_WORDS: dict[str, str] = {
    # 2-letter codes (upper-case only)
    "RU": "RUSSIA", "TR": "TURKEY", "BR": "BRAZIL", "AR": "ARGENTINA", "CN": "CHINA",
    "KR": "KOREA", "JP": "JAPAN", "PL": "POLAND", "UA": "UKRAINE", "MX": "MEXICO",
    "PH": "PHILIPPINES", "VN": "VIETNAM", "TH": "THAILAND", "CA": "CANADA",
    "AU": "AUSTRALIA", "ZA": "SOUTH AFRICA", "NA": "NORTH AMERICA", "CO": "COLOMBIA",
    "SG": "SINGAPORE", "HK": "HONG KONG", "IN": "INDIA", "DE": "GERMANY", "AT": "AUSTRIA",
    "NL": "NETHERLANDS", "RO": "ROMANIA", "CL": "CHILE", "PE": "PERU", "MY": "MALAYSIA",
    "ID": "INDONESIA", "NZ": "NEW ZEALAND", "CH": "SWITZERLAND", "FR": "FRANCE",
    "IT": "ITALY", "ES": "SPAIN", "PT": "PORTUGAL", "AE": "UNITED ARAB EMIRATES",
    "BE": "BELGIUM", "LU": "LUXEMBOURG", "DK": "DENMARK", "SE": "SWEDEN", "NO": "NORWAY",
    "FI": "FINLAND", "IE": "IRELAND", "EG": "EGYPT", "SA": "SAUDI ARABIA", "KW": "KUWAIT",
    "QA": "QATAR", "TW": "TAIWAN", "LV": "LATVIA", "LT": "LITHUANIA", "EE": "ESTONIA",
    "HU": "HUNGARY", "CZ": "CZECHIA", "SK": "SLOVAKIA", "GR": "GREECE", "HR": "CROATIA",
    "BG": "BULGARIA", "RS": "SERBIA", "KZ": "KAZAKHSTAN", "BY": "BELARUS", "IL": "ISRAEL",
    # groups / abbreviations
    "ROW": "ROW", "ROW ONLY": "ROW ONLY", "CIS": "CIS", "SEA": "SOUTH EAST ASIA",
    "ANZ": "ANZ", "UAE": "UNITED ARAB EMIRATES", "GCC": "GCC", "MENA": "MENA",
    "EMEA": "EMEA", "LATAM": "LATAM", "ASIA": "ASIA", "AMERICAS": "AMERICAS",
    "OCEANIA": "OCEANIA", "AFRICA": "AFRICA", "EU NA": "EU NA", "EU/NA": "EU NA",
    "EU/UK": "EU/UK", "EU WEST": "EU WEST", "EU EAST": "EU EAST",
    # « Rest of the world » écrit en toutes lettres = ROW (2026-09-24). Wyrel l'écrit ainsi
    # dans son créneau de région (161 lignes, `region=5`) : absent du vocabulaire, le titre
    # ne se lisait plus et la ligne tombait sur « no region slot » — refusée, mais pour une
    # fausse raison. Romain : une ROW n'entre que si on prouve qu'elle s'active en Europe.
    "REST OF WORLD": "ROW", "REST OF THE WORLD": "ROW",
    # full names (label = the name itself, matcher spelling)
    "NORTH AMERICA": "NORTH AMERICA", "SOUTH AMERICA": "SOUTH AMERICA",
    "LATIN AMERICA": "LATIN AMERICA", "SOUTH EAST ASIA": "SOUTH EAST ASIA",
    "EASTERN EUROPE": "EASTERN EUROPE", "MIDDLE EAST": "MIDDLE EAST",
    "HONG KONG": "HONG KONG", "NEW ZEALAND": "NEW ZEALAND", "SOUTH AFRICA": "SOUTH AFRICA",
    "SOUTH KOREA": "KOREA", "UNITED ARAB EMIRATES": "UNITED ARAB EMIRATES",
    "SAUDI ARABIA": "SAUDI ARABIA", "CZECH REPUBLIC": "CZECHIA",
    "RUSSIA": "RUSSIA", "TURKEY": "TURKEY", "BRAZIL": "BRAZIL", "ARGENTINA": "ARGENTINA",
    "CHINA": "CHINA", "KOREA": "KOREA", "JAPAN": "JAPAN", "POLAND": "POLAND",
    "UKRAINE": "UKRAINE", "MEXICO": "MEXICO", "PHILIPPINES": "PHILIPPINES",
    "VIETNAM": "VIETNAM", "THAILAND": "THAILAND", "CANADA": "CANADA",
    "AUSTRALIA": "AUSTRALIA", "COLOMBIA": "COLOMBIA", "SINGAPORE": "SINGAPORE",
    "INDIA": "INDIA", "GERMANY": "GERMANY", "AUSTRIA": "AUSTRIA",
    "NETHERLANDS": "NETHERLANDS", "ROMANIA": "ROMANIA", "CHILE": "CHILE", "PERU": "PERU",
    "MALAYSIA": "MALAYSIA", "INDONESIA": "INDONESIA", "SWITZERLAND": "SWITZERLAND",
    "FRANCE": "FRANCE", "ITALY": "ITALY", "SPAIN": "SPAIN", "PORTUGAL": "PORTUGAL",
    "BELGIUM": "BELGIUM", "LUXEMBOURG": "LUXEMBOURG", "DENMARK": "DENMARK",
    "SWEDEN": "SWEDEN", "NORWAY": "NORWAY", "FINLAND": "FINLAND", "IRELAND": "IRELAND",
    "EGYPT": "EGYPT", "KUWAIT": "KUWAIT", "QATAR": "QATAR", "BAHRAIN": "BAHRAIN",
    "OMAN": "OMAN", "TAIWAN": "TAIWAN", "LATVIA": "LATVIA", "LITHUANIA": "LITHUANIA",
    "ESTONIA": "ESTONIA", "HUNGARY": "HUNGARY", "CZECHIA": "CZECHIA", "SLOVAKIA": "SLOVAKIA",
    "GREECE": "GREECE", "CROATIA": "CROATIA", "BULGARIA": "BULGARIA", "SERBIA": "SERBIA",
    "KAZAKHSTAN": "KAZAKHSTAN", "BELARUS": "BELARUS", "ISRAEL": "ISRAEL", "ICELAND": "ICELAND",
}
# Kinguin's own spelling of "rest of world" — the ONE mixed-case token that is a region
# word ("Row" / "Death Row" stays a name word).
_MIXED_CASE_CODES = {"RoW": "ROW"}


def normalise_region_text(text: str) -> str:
    """Upper-cased, space-normalised key of a region word ("United  States" → "UNITED
    STATES"). Case is NOT checked here — see :func:`region_kind`."""

    return re.sub(r"\s+", " ", (text or "").strip()).upper()


def region_kind(text: str) -> tuple[str, str] | None:
    """What one region word says: ``("base", "eu")`` for a sellable region, ``("forbidden",
    "CANADA")`` for a known lock, ``None`` for a word that is not in the vocabulary.

    A short token (≤ 3 letters) counts only when written in CAPITALS by the merchant
    ("US", "CA", "ROW"; Kinguin's "RoW" is the one mixed-case exception): "Us", "Row" and
    "Sea" are ordinary name words. Longer names are case-insensitive ("Europe", "Hong
    Kong", "NORTH AMERICA")."""

    raw = re.sub(r"\s+", " ", (text or "").strip())
    if not raw:
        return None
    if raw in _MIXED_CASE_CODES:
        return "forbidden", _MIXED_CASE_CODES[raw]
    letters = re.sub(r"[^A-Za-z]", "", raw)
    if len(letters) <= 3 and raw != raw.upper():
        return None
    key = raw.upper()
    base = SELLABLE_WORDS.get(key)
    if base is not None:
        return "base", base
    label = FORBIDDEN_WORDS.get(key)
    if label is not None:
        return "forbidden", label
    return None


def compound_region_kind(text: str) -> tuple[str, str] | None:
    """:func:`region_kind` over a compound slot ("United States / Canada", "EU/NA",
    "Europe, North America"): a known compound wins as one word; otherwise any forbidden
    part → that lock (a lock is a lock); parts all sellable with ONE base → that base; two
    different sellable bases → ``("forbidden", <TEXT>)`` (no single bucket — fail-closed,
    the label is the merchant's own text); an unknown part → None."""

    whole = region_kind(text)
    if whole is not None:
        return whole
    parts = [p for p in re.split(r"\s*[/,&+]\s*", (text or "").strip()) if p]
    if len(parts) < 2:
        return None
    kinds = [region_kind(p) for p in parts]
    if any(k is None for k in kinds):
        return None
    for kind in kinds:
        if kind[0] == "forbidden":
            return kind
    bases = {k[1] for k in kinds}
    if len(bases) == 1:
        return "base", bases.pop()
    return "forbidden", normalise_region_text(text)


def sellable_base(text: str) -> str | None:
    """``"eu"`` / ``"us"`` / ``"uk"`` / ``"global"`` for a sellable region word, else None."""

    kind = region_kind(text)
    return kind[1] if kind is not None and kind[0] == "base" else None


def forbidden_reason(text: str) -> str | None:
    """``"forbidden region: <LABEL>"`` for a known lock (compound slots included), else None."""

    kind = compound_region_kind(text)
    return f"forbidden region: {kind[1]}" if kind is not None and kind[0] == "forbidden" else None


def region_slug(text: str) -> str:
    """The hyphenated URL spelling of a region word ("United States" → "united-states")."""

    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


# URL spellings of every vocabulary word ("united-states", "north-america", "eu-na", …),
# for the merchant URL grammars that put the region in a slug slot.
REGION_SLUGS: frozenset[str] = frozenset(
    region_slug(w) for w in (*SELLABLE_WORDS, *FORBIDDEN_WORDS, *_MIXED_CASE_CODES)
)


def region_alternation() -> str:
    """A regex alternation of every vocabulary word for a pattern compiled with
    ``re.IGNORECASE``: the short codes (≤ 3 letters, plus ``RoW``) sit in a scoped
    case-SENSITIVE group ``(?-i:…)`` so "Us" / "Row" / "Sea" never match, the full names
    stay case-insensitive ("Europe", "HONG KONG"); longest first, spaces as ``\\s+``."""

    words = {*SELLABLE_WORDS, *FORBIDDEN_WORDS, *_MIXED_CASE_CODES}
    short = sorted((w for w in words if len(re.sub(r"[^A-Za-z]", "", w)) <= 3), key=len, reverse=True)
    long_ = sorted((w for w in words if len(re.sub(r"[^A-Za-z]", "", w)) > 3), key=len, reverse=True)

    def alt(items: list[str]) -> str:
        return "|".join(re.escape(w).replace(r"\ ", r"\s+") for w in items)

    return rf"(?-i:{alt(short)})|(?:{alt(long_)})"


# ── MerchantConfig constructor tolerant to the console hooks ─────────────────────────
CONSOLE_HOOK_FIELDS = ("console_url_families", "console_pc_declared", "console_region_slot",
                       "console_noise")
_CONFIG_FIELDS = frozenset(f.name for f in dataclasses.fields(MerchantConfig))


def config_has_field(name: str) -> bool:
    """True when ``MerchantConfig`` (as imported) declares ``name`` — the console hooks
    become fields when agent M1's ``src/merchant_config.py`` lands (2026-09-14)."""

    return name in _CONFIG_FIELDS


def make_config(name: str, **kwargs: Any) -> MerchantConfig:
    """``MerchantConfig(name, **kwargs)`` where the kwargs that are not (yet) fields of the
    dataclass are moved under ``extra["console_hooks_pending"]`` instead of raising — so a
    merchant module declaring the R45 console hooks imports both before and after the
    contract lands. Only the four console hook names may be pending; any other unknown
    kwarg is a programming error and raises like the dataclass would."""

    pending: dict[str, Any] = {}
    kept: dict[str, Any] = {}
    for key, value in kwargs.items():
        if key in _CONFIG_FIELDS:
            kept[key] = value
        elif key in CONSOLE_HOOK_FIELDS:
            pending[key] = value
        else:
            raise TypeError(f"MerchantConfig has no field {key!r}")
    if pending:
        extra = dict(kept.get("extra") or {})
        extra["console_hooks_pending"] = pending
        kept["extra"] = extra
    return MerchantConfig(name, **kept)
