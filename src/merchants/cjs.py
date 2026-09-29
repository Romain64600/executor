"""CJS-CDKeys (feed store 30) — declaration only (2026-09-14, Romain's rule R32 / R45).

On the safe-auto allowlist (``src/admin/auto_merchants.py``, spelled "CJS-CDKeys") but
NEVER swept: no run directory, no saved feed, no console row in the 2026-09-12 extraction
(docs/MERCHANTS.md: « non, dry-run d'abord » — Romain 2026-09-11). Nothing is invented
without an observed batch: the generic rules and the shared console vocabulary apply,
fail-closed. The registry must map both spellings "CJS-CDKeys" (auto_merchants) and "CJS"
to this CONFIG.

**Créneau de région `[R67]` (2026-09-29).** CJS écrit la région APRÈS « Key: » / « Code: » /
« (Steam): » — « DYSMANTLE Steam Key: United Kingdom », « … Steam Key: Europe & UK »,
« … Steam Key: USA », « … Steam Key: China ». La lecture générique ne connaît que la queue
« - X » : « : United Kingdom » tombait au GLOBAL implicite. Mesuré le 29/09 : 120 clés Steam
« United Kingdom » (et une EA, une Epic) écrites en GLOBAL au lieu du seau UK, plus des clés
« Italy » / « France » / « Egypt » verrouillées pays publiées mondiales. Ce fichier lit
maintenant le créneau : Global / Europe / EU / Europe & UK / USA / United Kingdom → leur base ;
tout autre pays ou région → refus nommé, jamais le GLOBAL implicite. Un créneau qui n'est pas
une région (« Standard Edition », « Include Nuketown 2025 pack », « English Only ») laisse la
main à la lecture générique, comme avant.
"""

from __future__ import annotations

import re

from src.merchants.common import forbidden_reason, make_config, sellable_base

# Le créneau : ce qui suit le DERNIER « Key: » / « Code: » / « Account: » / « ): ».
_SLOT_RE = re.compile(r"(?:\bKey|\bCode|\bAccount|\))\s*:\s*(?P<slot>[^:]+?)\s*$", re.IGNORECASE)

# Les créneaux vendables et leur base (Romain : « Europe & UK » = Europe, comme Loaded [R61]).
REGION_SLOTS: dict[str, str] = {
    "global": "global",
    "europe": "eu", "eu": "eu", "europe & uk": "eu",
    "eu multi-language version (region free)": "eu",
    "eu multi-language key (all languages) (region free)": "eu",
    "usa": "us",
    "united kingdom": "uk",
}

# Mots qui font d'un créneau une ÉDITION ou un contenu, pas un lieu : la lecture générique garde
# la main (« Standard Edition », « Include Nuketown 2025 pack », « English Only »…).
_NOT_A_PLACE = re.compile(
    r"\b(?:edition|pack|dlc|game|base|include|includes|only|language|languages|steam|website|"
    r"devices?|membership|activation|bundle|collector'?s?|expansion|bonus|season|pass|"
    r"premium|deluxe|standard|limited|gold|day|pre-order|version|multi-language|mytrainz|"
    r"cheaper|bp|cs|de|es|fr|it|ko|tc|en)\b",
    re.IGNORECASE)
_PLACE_RE = re.compile(r"^[A-Za-z][A-Za-z .'&()]{1,60}$")   # sans « - » : « Nether - Watcher » est une édition


def region_slot(name: str) -> str | None:
    m = _SLOT_RE.search(name or "")
    return re.sub(r"\s+", " ", m.group("slot")).strip() if m else None


def _looks_like_place(slot: str) -> bool:
    """Un créneau qui NOMME un lieu : lettres seulement, sans mot d'édition ou de contenu
    (« Italy », « Saudi Arabia », « AR (Argentina) », « US Region (North America) »)."""

    return bool(_PLACE_RE.match(slot)) and not _NOT_A_PLACE.search(slot) or bool(
        re.search(r"\bregion\b", slot, re.IGNORECASE) and not re.search(r"region free", slot, re.IGNORECASE))


def _base(slot: str) -> str | None:
    """La base d'un créneau vendable : la table CJS d'abord (« Europe & UK »…), puis le
    vocabulaire partagé (« UK », « GB », « Worldwide », « WW », « United States »…) — audit de
    Romain du 29/09 (P2) : « UK » et « Worldwide » étaient refusés comme des pays."""

    return REGION_SLOTS.get(slot.lower()) or sellable_base(slot)


def title_region(name: str) -> str | None:
    slot = region_slot(name)
    return _base(slot) if slot else None


def precheck(name: str, url: str) -> str | None:
    """Un créneau de lieu que CJS ne vend pas partout (pays, région hors UE / UK / USA /
    monde) : refus nommé. Jamais le GLOBAL implicite d'une clé verrouillée."""

    slot = region_slot(name)
    if not slot or _base(slot) or not _looks_like_place(slot):
        return None
    return forbidden_reason(slot) or f"CJS : région « {slot} » (pays ou zone) non vendable — non entré (R67)"


CONFIG = make_config(
    "CJS-CDKeys",
    domain="cjs-cdkeys.com",          # to confirm at the first dry-run (a mismatch fails closed)
    # « …/Dragon%27s-Dogma-2%3A-Dark-Arisen-Steam-Key.html?variation=609 » et « …?variation=608 »
    # sont deux annonces (deux régions) sur le MÊME chemin : `variation` en est l'identité
    # (2026-09-24 — 13 fausses « STILL in feed » depuis le 20/09, dont 8 avec la sœur visible
    # sur la même page du feed).
    url_identity_params=("variation",),
    precheck=precheck,
    title_region=title_region,
    notes=("feed store 30 — [R67] région = créneau après « Key: » / « Code: » / « ): » (Global, "
           "Europe, EU, Europe & UK, USA, United Kingdom) ; tout autre pays ou zone → refus nommé "
           "(2026-09-29 : 120 clés « United Kingdom » écrites en GLOBAL auparavant)"),
)
