"""Electronicfirst (feed store 70) — the title grammar, declared 2026-09-15 `[R49]`.

Audited on 323 unique rows (the whole pending feed, coverage proven — read-only extraction
`runs/20260915-electronicfirst`). The grammar is Kinguin-shaped: an UPPERCASE region code
sits immediately before the final platform phrase, and the delivery word closes the title.

Grammar (title)::

    (A) <Game>[ - <Subtitle>][ <Edition>][ DLC] [<REGION>[ (<note>)]] <Platform phrase> <Delivery>
    (B) <Game> <Console platform phrase> <REGION>          (no delivery word)

Real rows::

    Sonic Superstars: Deluxe Edition featuring LEGO EU Steam CD Key   → eu, STEAM
    Worm In Rotating Land PC Steam CD Key                             → no code, STEAM
    Fable - Premium Edition Upgrade DLC US Xbox Series X|S / PC CD Key→ us, Play Anywhere
    Hero's Hour EU (without DE/NL/PL/AT) PS5 CD Key                   → partial EU → skip
    Mortal Kombat: Legacy Kollection PS4 / PS5 UK                     → grammar (B), uk
    Two Point Hospital: … Bundle RoW Steam CD Key                     → forbidden region: ROW
    £120 PlayStation PSN Card UK                                      → not a game

Vocabulary measured on the corpus: the slot is written on 113 / 323 rows — EU 71, US 16,
DE 8, FR 4, RoW 4, UK 2, EU/NA 2, NA 2, CA 1, EU/US/JP 1, UK/US 1, EMEA 1 — always an
UPPERCASE code (or the mixed-case "RoW"), never a full name, never lower-case.

`[R49a]` **a partial EU key is refused.** 16 rows carry a note glued to the code — "EU
(without DE)" 13, "EU (without DE/NL/PL/AT)", "EU (without DE/NL/PL)", "EU (without FR, RU)".
AKS has no bucket for "EU minus a country", so the row is neither the EU bucket nor global:
``precheck`` skips it by name.

`[R49b]` **a region word SPELLED OUT in the product name with an empty slot is refused.**
The slot is a CODE; a title that writes "Europe" or "United States" inside the name while
leaving the slot empty is ambiguous, and the generic scan would mine the name word. 1 row.

`[R49c]` **a CONSOLE row with an empty slot is refused — there is no worldwide PSN / Xbox
SKU.** This is the load-bearing rule, and it came out of the adversarial review of
2026-09-15. Electronicfirst writes the region on 55 / 75 = 73 % of its console rows against
14.5 % of its PC rows: on the console side the slot is a real lock carrier, so a silent
console row is far more likely an unwritten lock than a genuine worldwide key. Left to the
generic implicit GLOBAL, 7 rows would have been filed worldwide — including four full games
("Forza Motorsport Xbox Series X|S / PC CD Key", "Microsoft Flight Simulator 2024 Premium
Deluxe Edition  Xbox Series X|S / PC Key", "Horror Adventure : Zombie Edition VR PS4 / PS5
CD Key"). Cost: 7 candidates. Exactly the failure mode `[R27]` and `[R47]` exist for.

**A "template gap" rule was considered and REJECTED (2026-09-15).** The adversarial review
proposed skipping rows carrying a DOUBLE SPACE at the slot position, reading it as an empty
field rendered visible — the example being "Microsoft Flight Simulator 2024 Premium Deluxe
Edition  Xbox Series X|S / PC Key", same game and same ingestion block as a sibling that DOES
write "EU" six ids earlier. Measured on the corpus, the rule is INERT and noisy: of the 5
double-space rows, 2 already carry a slot ("Wreckreation  PS4/PS5 US"), 2 have the gap inside
the product NAME ("Dakar Desert Rally-  Audi RS Q E-Tron…") and the last one — the MSFS row —
is already refused by `[R49c]`. It would add a rule that never fires and whose signal also
appears in ordinary titles. Recorded here so a later audit does not re-propose it blind: the
concern it addressed is real and is covered by `[R49c]`.

**PC rows with an empty slot keep the generic implicit GLOBAL — PROVISIONALLY.** 210 rows
have no code and the merchant never writes an explicit worldwide word (GLOBAL / Worldwide /
WW: 0 / 323), which is the Kinguin / MMOGA shape. But unlike those two, Electronicfirst has
never been swept, so the validity condition is written down and re-checked at every batch:
**if a single Electronicfirst row ever writes a slot that resolves to "global", the empty
slot becomes ambiguous and `[R47]`'s fail-closed skip applies to every silent row.**
``tests/test_merchants_electronicfirst.py`` pins the 0-explicit-global measurement so the
day it changes, the rule is re-read rather than silently kept.

Store 70 stays OFF the safe-auto allowlist: first pass supervised, dry-run.

Self-contained: imports only ``src.merchant_config`` and ``src.merchants.common``.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from src.merchants.common import (
    FORBIDDEN_WORDS,
    SELLABLE_WORDS,
    compound_region_kind,
    forbidden_reason,
    make_config,
    sellable_base,
)

# ── title grammar ────────────────────────────────────────────────────────────────────
# The platform phrase Electronicfirst writes at the end of the title (before the delivery
# word), "/"-separated. Vocabulary only: the platform DETECTION stays the generic title read
# (title_is_platform_source, like Kinguin) — this module peels the phrase and anchors the
# region slot.
_PLATFORM_WORD = (
    r"PC\s*/\s*MAC|PC|Mac|Steam|GOG(?:\.com)?|Epic\s*Games(?:\s*Store)?|Epic|EA\s*App|"
    r"EA\s*Play|Origin|Ubisoft\s*Connect|Ubisoft|Uplay|Rockstar(?:\s*Games)?|Battle\.?net|"
    r"Microsoft\s*Store|Official\s*Website|Windows\s*1[01](?:\s*/\s*1[01])?|Win\s*1[01]|"
    r"Xbox\s*Series\s*X\s*\|\s*S|Xbox\s*Series\s*X\s*/\s*S|Xbox\s*Series\s*X|"
    r"Xbox\s*Series\s*S|Xbox\s*Series|Xbox\s*One|Xbox|"
    r"PlayStation\s*5|PlayStation\s*4|PS5|PS4|PSN|"
    r"Nintendo\s*Switch\s*2|Nintendo\s*Switch|Switch\s*2|Switch"
)
# Inside one run the generation words are abbreviated after the first platform word
# ("XBOX One / Series X|S / PC", "PS4/PS5").
_PLATFORM_CONT = (
    _PLATFORM_WORD + r"|Series\s*X\s*\|\s*S|Series\s*X\s*/\s*S|Series\s*X|Series\s*S|Series"
)
_PLATFORM_RUN_CORE = rf"(?:{_PLATFORM_WORD})(?:\s*/\s*(?:{_PLATFORM_CONT}))*"
# EF also writes the device word in FRONT of the store ("PC Steam", "PC GOG", "PC EA App",
# "PC Rockstar") — one optional leading device word, never a free space-joined run.
_PLATFORM_RUN = rf"(?:(?:PC|Mac|PC\s*/\s*Mac)\s+)?{_PLATFORM_RUN_CORE}"
# Delivery words, measured: "CD Key" 216, "" 75, "Key" 18, "Gift" 9 (always "Steam Gift"),
# "Digital Download CD Key" 4, "Digital Download Key" 1. No Account / Access / Altergift.
_DELIVERY = r"(?:Digital\s+Download\s+)?(?:CD\s+)?(?:Keys?|Gifts?)"
# The region slot: an UPPERCASE code, or "RoW", possibly compound with "/". Case-sensitive on
# purpose — 0 / 323 rows write it in lower case, and "Us" / "Row" are ordinary name words.
_CODES = sorted(
    {w for w in (*SELLABLE_WORDS, *FORBIDDEN_WORDS) if re.fullmatch(r"[A-Z]{2,4}", w)},
    key=len, reverse=True,
)
_CODE = r"(?:(?-i:" + "|".join(_CODES) + r")|RoW)"
_SLOT = rf"{_CODE}(?:\s*/\s*{_CODE})*"
# The note glued to the slot: "(without DE)", "(without DE/NL/PL/AT)", "(retail)", "(Tier 1)".
_NOTE = r"\(\s*[^()]{1,40}\s*\)"

# (A) … <SLOT> [<note>] <platform run> <delivery>
_GRAMMAR_A_RE = re.compile(
    rf"^(?P<head>.*?)\s+(?P<slot>{_SLOT})(?:\s*(?P<note>{_NOTE}))?"
    rf"\s+(?P<run>{_PLATFORM_RUN})\s+(?P<delivery>{_DELIVERY})\s*$", re.IGNORECASE)
# (A') no slot: … <platform run> <delivery>
_GRAMMAR_A_NOSLOT_RE = re.compile(
    rf"^(?P<head>.*?)\s+(?P<run>{_PLATFORM_RUN})\s+(?P<delivery>{_DELIVERY})\s*$",
    re.IGNORECASE)
# (B) … <console platform run> <SLOT>   (no delivery word)
_GRAMMAR_B_RE = re.compile(
    rf"^(?P<head>.*?)\s+(?P<run>{_PLATFORM_RUN})\s+(?P<slot>{_SLOT})\s*$", re.IGNORECASE)
# (B') no slot, no delivery: … <platform run>
_GRAMMAR_B_NOSLOT_RE = re.compile(rf"^(?P<head>.*?)\s+(?P<run>{_PLATFORM_RUN})\s*$", re.IGNORECASE)

# A "PC" device word EF sometimes writes BEFORE the slot ("RIOT- Civil Unrest PC EU XBOX One
# / Xbox Series X|S CD Key") — peeled from the head after the slot is removed.
_TRAILING_DEVICE_RE = re.compile(r"\s+(?:PC|Mac|PC\s*/\s*Mac)\s*$", re.IGNORECASE)

# ── non-game listings ────────────────────────────────────────────────────────────────
# (1) a monetary amount next to a number — vouchers, cards, top-ups (16 rows).
_MONEY_RE = re.compile(
    r"(?:USD|EUR|GBP|CAD|AUD|CHF|SEK|PLN|CLP|SGD|C\$|A\$|[$€£¥₺])\s*\d"
    r"|\d+(?:[.,]\d+)?\s*(?:USD|EUR|GBP|CAD|AUD|CHF|SEK|PLN|CLP|SGD)\b")
# (2) the CARD collocations — never a bare "CARD" nor a bare "GAME" ("Cards and Towers" and
# "Parkour Game 2 PC Steam CD Key" are real games).
_CARD_RE = re.compile(
    r"\bGame\s+e?-?Card\b|\bPSN\s+Card\b|\bPlayStation\s+Network\s+Card\b|\be-?Card\b",
    re.IGNORECASE)
# (3) subscriptions.
_SUBSCRIPTION_RE = re.compile(r"\bPS\s*Plus\b|\b\d+\s*(?:Months?|Years?)\b", re.IGNORECASE)
# (4) in-game currency written as a quantity of tokens (TOKEN is absent from the generic
# CURRENCY_TOKENS, which already covers COINS / GEMS / CREDITS / CURRENCY).
_TOKEN_RE = re.compile(r"\d[\d,.]*\s*(?:TP\s+)?Tokens?\b|\bTokens?\s+\d", re.IGNORECASE)

# Software licences: EF sells them without any edition grammar we can read.
_LICENCE_SCOPE_RE = re.compile(
    r"\(\s*(?:\d+\s*(?:PCs?|MACs?|Devices?)|Unlimited\s+Devices?|Lifetime[^)]*)\s*\)\s*$",
    re.IGNORECASE)
_LICENCE_DELIVERY_RE = re.compile(r"\b(?:ISO|Bind)\s+Key\s*$", re.IGNORECASE)
_MS_PRODUCT_RE = re.compile(r"^MS\s+\S", re.IGNORECASE)

# Region words SPELLED OUT (>= 4 letters) — a name word when the slot is empty (R49b).
_SPELLED_REGION_RE = re.compile(
    r"\b(?:" + "|".join(sorted(
        (re.escape(w).replace(r"\ ", r"\s+")
         for w in (*SELLABLE_WORDS, *FORBIDDEN_WORDS)
         if len(re.sub(r"[^A-Za-z]", "", w)) >= 4),
        key=len, reverse=True)) + r")\b", re.IGNORECASE)

_CONSOLE_MARKER_RE = re.compile(
    r"\bXbox\b|\bPlayStation\b|\bPSN\b|\bPS[345]\b|\bNintendo\b|\bSwitch\b|\bWii\b", re.IGNORECASE)


def _parse(name: str):
    """(head, slot, note, run, delivery) — every field verbatim, any of them "" when the
    grammar does not write it. Parsed from the END so a region or platform word inside the
    product name is never mined."""

    text = re.sub(r"[ \t]+", " ", name or "").strip()
    for rx in (_GRAMMAR_A_RE, _GRAMMAR_B_RE, _GRAMMAR_A_NOSLOT_RE, _GRAMMAR_B_NOSLOT_RE):
        m = rx.match(text)
        if m:
            g = m.groupdict()
            return (g.get("head") or "", g.get("slot") or "", g.get("note") or "",
                    g.get("run") or "", g.get("delivery") or "")
    return text, "", "", "", ""


def region_slot(name: str) -> str | None:
    """The region code Electronicfirst writes in its slot, verbatim ("EU", "US", "RoW",
    "EU/NA"), or None when the slot is empty."""

    slot = _parse(name)[1]
    return slot or None


def _is_partial_eu(name: str) -> str | None:
    """The "(without …)" note glued to the slot, or None."""

    note = _parse(name)[2]
    return note if note and re.search(r"\bwithout\b", note, re.IGNORECASE) else None


def _non_game_reason(name: str, url: str) -> str | None:
    text = name or ""
    if _MONEY_RE.search(text):
        return "skip category: STORED VALUE (card / voucher / top-up)"
    if _CARD_RE.search(text):
        return "skip category: GAME CARD"
    if _SUBSCRIPTION_RE.search(text):
        return "skip category: SUBSCRIPTION"
    if _TOKEN_RE.search(text):
        return "skip category: TOKEN (in-game currency)"
    return None


def _software_reason(name: str, url: str) -> str | None:
    text = name or ""
    path = urlsplit(url or "").path.lower()
    if (_LICENCE_SCOPE_RE.search(text) or _LICENCE_DELIVERY_RE.search(text)
            or _MS_PRODUCT_RE.match(text) or "-lifetime-" in path):
        return ("Electronicfirst: software licence — no merchant edition grammar for this "
                "brand (R49)")
    return None


# ── hooks ────────────────────────────────────────────────────────────────────────────
def precheck(name: str, url: str) -> str | None:
    """Electronicfirst's categorical skips, in order:

    1. non-game listings (stored value, game cards, subscriptions, token packs);
    2. software licences (licence scope, ISO / Bind Key, "MS <product>", "-lifetime-" slug);
    3. `[R49a]` a partial EU key ("EU (without DE)") — no AKS bucket for EU minus a country;
    4. a region LOCK in the slot → ``forbidden region: <LABEL>``;
    5. `[R49b]` a region word spelled out in the NAME while the slot is empty — ambiguous;
    6. `[R49c]` a CONSOLE row with an empty slot — there is no worldwide PSN / Xbox SKU."""

    reason = _non_game_reason(name, url)
    if reason:
        return reason
    reason = _software_reason(name, url)
    if reason:
        return reason
    note = _is_partial_eu(name)
    if note:
        return (f"Electronicfirst: partial EU key {note} — no AKS bucket for EU minus a "
                "country (R49a)")
    slot = region_slot(name)
    if slot:
        kind = compound_region_kind(slot)
        if kind is None:
            return (f"Electronicfirst: unknown region slot {slot!r} — not in the shared "
                    "vocabulary (R49)")
        if kind[0] == "forbidden":
            return forbidden_reason(slot)
        return None
    # ── the slot is EMPTY from here on ──────────────────────────────────────────────
    head = _parse(name)[0]
    spelled = _SPELLED_REGION_RE.search(head)
    if spelled:
        return (f"Electronicfirst: region word {spelled.group(0)!r} in the product name "
                "while the slot is empty — the region is a CODE in the slot (R49b)")
    if _CONSOLE_MARKER_RE.search(name or ""):
        return ("Electronicfirst: console key with no region slot — no worldwide PSN / Xbox "
                "SKU, and 73% of this merchant's console rows do carry a code (R49c)")
    return None


def title_region(name: str) -> str | None:
    """The slot's code → "eu" / "us" / "uk". Read POSITIONALLY, never by scanning the title
    or the slug. An empty slot returns None: the PC rows then keep the generic implicit
    GLOBAL (see the module docstring for the validity condition of that choice); a console
    row with an empty slot never reaches here — ``precheck`` skipped it `[R49c]`."""

    slot = region_slot(name)
    return sellable_base(slot) if slot else None


def resolve_name(name: str) -> str:
    """The title handed to AKS resolution, peeled from the END: delivery → platform phrase →
    note → region slot → residual device word.

    "Grand Theft Auto V Enhanced EU PC Rockstar Digital Download CD Key" → "Grand Theft Auto
    V Enhanced"; "Hero's Hour EU (without DE/NL/PL/AT) PS5 CD Key" → "Hero's Hour"; "RIOT-
    Civil Unrest PC EU XBOX One / Xbox Series X|S CD Key" → "RIOT- Civil Unrest"; a bare
    title is returned untouched."""

    head = _parse(name)[0]
    head = _TRAILING_DEVICE_RE.sub("", head).strip(" -–,")
    return head or re.sub(r"\s+", " ", name or "").strip()


CONFIG = make_config(
    "Electronicfirst",
    domain="electronicfirst.com",
    precheck=precheck,
    title_region=title_region,
    resolve_name=resolve_name,
    notes=(
        "feed store id 70. R49: UPPERCASE region code before the final platform phrase "
        "(Kinguin-shaped). Partial EU (R49a), spelled-out region word with an empty slot "
        "(R49b) and console row with an empty slot (R49c) all fail "
        "closed. PC rows with an empty slot keep the generic implicit GLOBAL, PROVISIONALLY "
        "— the merchant writes no explicit worldwide word today (0/323); the day it does, "
        "R47 applies. Platform stays title-sourced; no console hook (the shared classifier "
        "reads the 75 console rows). Off the safe-auto allowlist: supervised dry-run first."
    ),
)
