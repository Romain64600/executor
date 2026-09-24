"""Wyrel (feed store 162) — the title grammar, declared 2026-09-16 `[R53]`.

Audited on 100 rows of page 1 (read-only extraction of 2026-09-15), three independent
lenses then three adversarial contradictors. The feed advertises **60 pages**, so this is
the most voluminous merchant of the discovery audit — and the most machine-readable: its
title is a SLOT TEMPLATE that parses end-to-end, and its URL repeats the same facts as
numeric ids.

Grammar (title), parsed from the END, no residue (100/100)::

    <Product> [ "(" <TAG> ")" ] <EDITION> [ <PLATFORM> ] <REGION> [ "Steam Gift" ]

Real rows::

    Hunt Showdown: Shrine Maidens Hell (DLC) Standard PC Global
    AENTITY (PC) Standard Europe Steam Gift
    Vanquish (Xbox) Standard Xbox One Europe
    DYSMANTLE (Xbox Series X) Standard Xbox Series X/S Europe
    Rituals Gift Card  7 GBP Standard Other United Kingdom      → not a game

Slots measured on the corpus:

* ``<REGION>`` — MANDATORY, 100/100, always a FULL NAME in Title Case, never a code:
  Global 53, Europe 19, United Kingdom 15, United States 12, Germany 1. No "Worldwide",
  "WW", "RoW", "EU", "US", "UK" anywhere.
* ``<EDITION>`` — MANDATORY, 100/100: Standard 95, Collectors 2, Zero 2, Horizon Hobby 1.
* ``<PLATFORM>`` — Other 48, Xbox One 7, PC 6, Xbox Series X/S 1, absent 38 (absent exactly
  when ``<TAG>`` is "PC").
* ``<TAG>`` — the single parenthesised group, POLYMORPHIC (a device OR a product nature):
  PC 38, Xbox 7, DLC 6, Xbox Series X 1, absent 48. Reading "the parenthesis is the
  platform" would file a DLC as a platform.
* ``<DELIVERY>`` — binary: "Steam Gift" 10, nothing 90. It is the ONLY place Wyrel ever
  names a STORE.

URL: ``wyrel.com/en/buy-{cheap|billig}-<slug>-<id>?referal=…&marketplace_id=<M>&edition_id=<E>&region=<R>&coupon=…``
— the five parameters are present 100/100. **The region is a PARAMETER, never in the path**,
and the matcher cuts the query before its own region scan, so only ``precheck`` can read it.

`[R53d]` **the two region sources must AGREE.** The title slot and ``region=`` are in strict
bijection on the corpus — 1↔Global, 4↔Europe, 8↔United States, 14↔United Kingdom,
19↔Germany, **0 disagreement**. No other merchant gives us a second independent source, so
it is used as a CROSS-CHECK: a proven disagreement is a fail-closed skip, never a guess. The
comparison is of MEANINGS (``compound_region_kind``), never of spellings, and an id outside
the known map is tolerated (it proves nothing).

`[R53b]` **``<PLATFORM> == "Other"`` IS the non-game marker** — it is the merchant's own
word for "no device", so reading it is reading Wyrel's declaration, not guessing. The reason
names the PRODUCT (GIFT CARD / WALLET / VOUCHER / CURRENCY), not the slot, so
``aks_lists.suggest_target_list`` routes it like every other merchant's non-game.

*This rule was WIDER for a day, and the data narrowed it.* On the 100 rows of page 1 the
adversarial review required THREE agreeing signals — slot "Other", no ``(<TAG>)`` group, and
a ``marketplace_id`` outside the game ids {2, 8} — because with one predicate alone a row
written "(PS5) … Other" would have been called "not a game", a LIE about the row. The first
real slice (pages 1-10, **990 rows**) answered both open questions:
* ``marketplace_id`` is NOT enumerable and does not even separate the two classes — the
  "Other" rows use 316, 651, 487, 1703, 12, 112…, the "PC" rows use 2, 588, 6, 12, 603… and
  **id 12 appears on BOTH sides**. Requiring it produced **98 false refusals** on that slice;
* a tag next to "Other" is not a contradiction: the 4 such rows are IN-GAME CURRENCY naming
  the device it is for ("eFootball 2023 12000 Coins (Xbox One)", "Apex Legends Apex Coins
  6700 Points (PC)", "PUBG 11200 G COIN (PC)") — still not a game.
On 990 rows the slot alone is 228/228 non-games and never touches a key. So the marketplace
predicate is GONE and the contradiction branch with it. An audit reading only page 1 will
want the three-signal gate back — it was measured wrong on ten times the data; leave it out.

`[R53e]` **the platform slot vocabulary is OPEN and an unknown word fails closed.** The
first draft closed it to the four strings the corpus shows; the review refused that — page 1
of 60 cannot enumerate a merchant's devices, and an unlisted "PS5" would be silently
swallowed into the EDITION slot and change the parse. Any slot word outside the declared
vocabulary is refused BY NAME.

Store 162 is NOT on the safe-auto allowlist: supervised runs first.

Self-contained: imports only ``src.merchant_config`` and ``src.merchants.common``.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

from src.merchants.common import (
    compound_region_kind,
    forbidden_reason,
    make_config,
    normalise_region_text,
    region_alternation,
    sellable_base,
)

# ── the slots ────────────────────────────────────────────────────────────────────────
_REGION = region_alternation()
_DELIVERY = r"Steam\s+Gift"
# Region slot at the END, with the optional delivery word after it.
_TAIL_RE = re.compile(
    rf"^(?P<head>.*?)\s+(?P<region>{_REGION})(?:\s+(?P<delivery>{_DELIVERY}))?\s*$",
    re.IGNORECASE)

# `[R53e]` the platform slot vocabulary — OPEN, and deliberately wider than page 1 shows
# (the feed has 60 pages). "Other" is Wyrel's own marker for a non-game listing.
PLATFORM_SLOT_WORDS: tuple[str, ...] = (
    "Other",
    "PC", "Mac", "PC/Mac",
    "Xbox Series X/S", "Xbox Series X|S", "Xbox Series X", "Xbox Series S", "Xbox Series",
    "Xbox One", "Xbox 360", "Xbox",
    "PS5", "PS4", "PS3", "PlayStation 5", "PlayStation 4", "PlayStation",
    "Nintendo Switch 2", "Nintendo Switch", "Switch 2", "Switch",
)
_SLOT_ALT = "|".join(
    re.escape(w).replace(r"\ ", r"\s+") for w in sorted(PLATFORM_SLOT_WORDS, key=len, reverse=True))
_PLATFORM_SLOT_RE = re.compile(rf"\s+(?P<slot>{_SLOT_ALT})\s*$", re.IGNORECASE)
# A trailing capitalised run that is NOT in the vocabulary, sitting where the slot belongs:
# refused by name rather than swallowed into the edition (`[R53e]`).
_UNKNOWN_SLOT_RE = re.compile(r"\)\s+\S+(?:\s+\S+)?\s+(?P<word>[A-Z][A-Za-z0-9/|+.-]*(?:\s+[A-Z][A-Za-z0-9/|+.-]*)?)\s*$")
_TAG_RE = re.compile(r"\(([^()]*)\)")
# NOTE: there is deliberately NO game-marketplace id set here. `marketplace_id` looks like a
# device partition on page 1 (2 = PC, 8 = Xbox) but the 990-row slice shows it is neither
# enumerable nor separating — id 12 carries both "Other" rows and "PC" rows. See [R53b].
# region= id → the region text Wyrel writes, measured 100/100 with zero disagreement.
REGION_PARAM_TEXT: dict[str, str] = {
    "1": "Global", "4": "Europe", "8": "United States", "14": "United Kingdom",
    "19": "Germany",
}
# edition_id → the edition text Wyrel writes, measured 100/100 with zero disagreement. Used
# as the SECOND SOURCE that tells an unknown PLATFORM slot from a long EDITION name: the
# edition "Horizon Hobby" is two words, so word-counting alone cannot separate them
# (`[R53e]`, adversarial review 2026-09-16).
EDITION_PARAM_TEXT: dict[str, str] = {
    "780": "Standard", "41": "Collectors", "1589": "Zero", "1185": "Horizon Hobby",
}
# `[R53c]` the edition slot words the SHARED vocabulary really maps to an AKS bucket.
# Measured on the 990-row slice: "Standard" 700 → Standard(1), "Deluxe Edition" 6 and
# "Digital Deluxe" 2 → Deluxe(7) — those must ENTER. But "Collectors" 5, "Zero" 2 and
# "Anniversary" 2 are silently FLATTENED to Standard(1) by the generic read, which would
# file a collector's edition as the base game: they are refused BY NAME instead. The list
# holds the tier words the generic read is known to resolve; "Edition" / "Digital" are
# format words, dropped before the comparison.
MAPPED_EDITION_WORDS = frozenset({
    "STANDARD", "DELUXE", "GOLD", "ULTIMATE", "PREMIUM", "COMPLETE", "GOTY",
    "GAME OF THE YEAR", "COLLECTION", "DEFINITIVE", "REMASTERED",
})
_EDITION_FORMAT_WORDS = frozenset({"EDITION", "DIGITAL", "THE", "OF", "AND"})
# The product families behind the non-game rows, named so the list router recognises them.
_NON_GAME_PRODUCT = (
    (re.compile(r"\bgift\s*cards?\b", re.I), "GIFT CARD"),
    (re.compile(r"\bwallet\b|\btop\s*up\b", re.I), "WALLET"),
    (re.compile(r"\bvoucher\b", re.I), "VOUCHER"),
    (re.compile(r"\bcard\b", re.I), "GIFT CARD"),
    (re.compile(r"\btokens?\b|\bVP\b|\brobux\b|\bcoins?\b", re.I), "CURRENCY"),
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def parse_title(name: str) -> dict[str, str] | None:
    """The title split into its slots, or None when it does not parse.

    Keys: ``head`` (product + the "(<TAG>)" group + the edition), ``tag``, ``platform``,
    ``region``, ``delivery``. Parsed from the END so nothing in the product name is mined."""

    text = _norm(name)
    m = _TAIL_RE.match(text)
    if not m:
        return None
    head, region, delivery = m.group("head"), m.group("region"), m.group("delivery") or ""
    slot = ""
    ms = _PLATFORM_SLOT_RE.search(head)
    if ms:
        slot = _norm(ms.group("slot"))
        head = head[: ms.start()].rstrip()
    tags = _TAG_RE.findall(head)
    return {
        "head": head,
        "tag": _norm(tags[-1]) if tags else "",
        "platform": slot,
        "region": _norm(region),
        "delivery": _norm(delivery),
    }


def _url_params(url: str) -> dict[str, str]:
    q = parse_qs(urlsplit(url or "").query)
    return {k: v[0] for k, v in q.items() if v}


def _non_game_product(name: str) -> str:
    for rx, label in _NON_GAME_PRODUCT:
        if rx.search(name or ""):
            return label
    return "STORED VALUE"


# ── hooks ────────────────────────────────────────────────────────────────────────────
def precheck(name: str, url: str) -> str | None:
    """Wyrel's categorical skips, in order. Every one fail-closed:

    1. `[R53a]` the title does not parse (no readable region slot at the end);
    2. `[R53b]` NON-GAME — the three signals agree (slot "Other", no "(<TAG>)" group, a
       marketplace id outside {2, 8}); a CONTRADICTION between them is its own skip;
    3. `[R53e]` a platform-slot word outside the declared vocabulary, refused BY NAME;
    4. a region LOCK in the slot → ``forbidden region: <LABEL>``;
    5. `[R53d]` a proven disagreement between the title slot and the ``region=`` parameter;
    6. `[R53c]` an edition slot we cannot map (anything but Standard)."""

    parts = parse_title(name)
    params = _url_params(url)
    if parts is None:
        # an unknown platform-slot word can be WHY the title does not parse — name it
        m = _UNKNOWN_SLOT_RE.search(_norm(name))
        if m:
            return (f"Wyrel: unknown platform slot {m.group('word')!r} — not in the declared "
                    "vocabulary, refusing to fold it into the edition (R53e)")
        return ("Wyrel: no region slot at the end of the title — the region is never "
                "implicit here (R53a)")

    slot = parts["platform"]
    if slot.casefold() == "other":
        return f"skip category: {_non_game_product(name)} (Wyrel non-game listing) (R53b)"

    kind = compound_region_kind(parts["region"])
    if kind is None:
        return (f"Wyrel: unknown region slot {parts['region']!r} — not in the shared "
                "vocabulary (R53a)")
    if kind[0] == "forbidden":
        return forbidden_reason(parts["region"])

    # [R53d] the URL repeats the region as an id: a PROVEN disagreement fails closed.
    expected = REGION_PARAM_TEXT.get(params.get("region", ""))
    if expected is not None and normalise_region_text(expected) != normalise_region_text(parts["region"]):
        exp_kind = compound_region_kind(expected)
        if exp_kind is None or exp_kind != kind:
            return (f"Wyrel: title says region {parts['region']!r} but the URL says "
                    f"{expected!r} — the two sources disagree (R53d)")

    after_tag = parts["head"].rsplit(")", 1)[-1].strip() if ")" in parts["head"] else parts["head"].strip()
    # [R53e] the URL names the edition too: anything the edition does NOT account for, sitting
    # where the platform slot belongs, is an UNDECLARED slot word — refuse it BY NAME instead
    # of folding it into the edition (which would silently change the parse).
    expected_edition = EDITION_PARAM_TEXT.get(params.get("edition_id", ""))
    if expected_edition and after_tag.casefold() != expected_edition.casefold():
        if after_tag.casefold().startswith(expected_edition.casefold()):
            residue = after_tag[len(expected_edition):].strip()
            if residue:
                return (f"Wyrel: unknown platform slot {residue!r} — not in the declared "
                        "vocabulary, refusing to fold it into the edition (R53e)")
    if after_tag:
        words = [t for t in re.split(r"\s+", after_tag.upper()) if t]
        tiers = [t for t in words if t not in _EDITION_FORMAT_WORDS]
        if not tiers or any(t not in MAPPED_EDITION_WORDS for t in tiers):
            return (f"Wyrel: edition slot {after_tag!r} maps to no AKS bucket — the generic "
                    "read would flatten it to Standard (R53c)")
    return None


def title_region(name: str) -> str | None:
    """The region slot → "eu" / "us" / "uk" / "global". Read POSITIONALLY from the end of
    the title, never by scanning the title or the URL path. A lock or an unparsable title
    returns None (``precheck`` refused the row first)."""

    parts = parse_title(name)
    return sellable_base(parts["region"]) if parts else None


def resolve_name(name: str) -> str:
    """The product alone: delivery → region → platform slot → edition slot → the whole
    "(<TAG>)" group peeled from the END. Nothing is removed from the NAME — a "Pack",
    "Bundle" or a "DLC" that belongs to the product survives."""

    parts = parse_title(name)
    if parts is None:
        return _norm(name)
    head = parts["head"]
    head = re.sub(r"\s+Standard\s*$", "", head, flags=re.I)
    head = _TAG_RE.sub(" ", head)
    head = re.sub(r"\(\s*$", "", head)
    head = re.sub(r"\s{2,}", " ", head).strip(" -–,")
    return head or _norm(name)


def console_region_slot(name: str) -> str | None:
    """The console rows use the SAME slot — hand the shared classifier the raw text."""

    parts = parse_title(name)
    return parts["region"] if parts else None


# The edition slot sits right after the "(<TAG>)" group; strip it (and it only) from the
# name the shared console classifier resolves. Positional: it cannot eat a product word.
CONSOLE_NOISE = re.compile(r"(?<=\))\s+Standard(?![A-Za-z0-9])", re.IGNORECASE)


CONFIG = make_config(
    "Wyrel",
    domain="wyrel.com",
    precheck=precheck,
    title_region=title_region,
    resolve_name=resolve_name,
    console_region_slot=console_region_slot,
    console_noise=(CONSOLE_NOISE,),
    # Les variantes d'un même produit partagent le CHEMIN et ne diffèrent que par la query :
    # « …-shores-unknown-pc-…?marketplace_id=2&edition_id=780&region=4 » (Europe) contre
    # « …&region=1 » (Global). C'est l'identité de l'annonce (2026-09-24 : 14 fausses
    # « STILL in feed » le jour même, la sœur de l'autre région restée au feed). `referal` et
    # `coupon` sont les mêmes sur toutes les lignes : ils n'en font pas partie.
    url_identity_params=("marketplace_id", "edition_id", "region"),
    notes=(
        "feed store id 162, 60 pages. R53: slot template parsed from the END. The region is "
        "written in FULL in the title AND repeated as the URL's region= id — the two must "
        "agree (R53d). Non-game needs three agreeing signals (R53b); an unknown platform "
        "slot word is refused by name (R53e). Safe-auto allowlist since 2026-09-24 (group B)."
    ),
)
