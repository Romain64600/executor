"""Loaded — ex-CDKeys (feed store 40) — `[R61]`, 2026-09-25.

Romain, 2026-09-25 : « Pars sur CDKeys (nouveau nom du marchand est LOADED) », puis, sur les deux
questions posées : « 1. Europe 2. comme Kinguin et MMOGA en global ».

Les titres sont RICHES, écrits en fin de ligne :
``<Jeu> [Édition] <Plateforme> [(<Région>)] [- DLC]`` —
« Towerborne Xbox/PC (Europe & UK) », « Attack on Titan 3 … PC (North America) »,
« Red Dead Redemption 2: Ultimate Edition Xbox (WW) », « Super Mario Galaxy 2 Switch & Switch 2
(Europe & UK) », « Zero Caliber 2 Remastered PC ».

L'URL du feed est un lien d'AFFILIATION (``go.loaded.com/c/…?u=https://www.loaded.com/<slug>``) :
la vraie fiche est dans le paramètre ``u``, et son slug répète plateforme, boutique et région
(``…-pc-steam-eu``, ``…-pc-steam-na``, ``…-xbox-pc-eu``, ``…-xbox-ww``, ``…-pc-steam``).

* **Région = la parenthèse finale du titre.** « Europe & UK » → Europe (décision 1 de Romain ;
  le vocabulaire partagé y voit deux régions à la fois, donc un verrou — c'est la grammaire de
  CE marchand qui tranche) ; « WW » → GLOBAL ; « UK » / « US »… → leur base ; « North America »
  et tout verrou connu → refus ``forbidden region`` ; un texte inconnu → refus nommé.
  **Sans parenthèse, pas de région → GLOBAL implicite**, comme Kinguin et MMOGA (décision 2).
* **Plateforme PC = la boutique du slug** (``-pc-steam`` → STEAM, ``-pc-epic`` → EPIC…) : le titre
  dit seulement « PC ». Les lignes console passent par le classifieur partagé ; ce fichier lui
  donne la région (``console_region_slot``).
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

from src.merchants.common import forbidden_reason, make_config

DOMAIN = "loaded.com"

# ── région : la parenthèse finale ─────────────────────────────────────────────────────
_SLOT_RE = re.compile(r"\(\s*(?P<slot>[^()]+?)\s*\)\s*(?:-\s*DLC\s*)?$", re.IGNORECASE)
REGION_TEXT: dict[str, str] = {
    "europe & uk": "eu",        # décision 1 de Romain (2026-09-25)
    "europe": "eu", "eu": "eu",
    "ww": "global", "worldwide": "global", "global": "global",
    "uk": "uk", "united kingdom": "uk",
    "us": "us", "usa": "us", "united states": "us",
}
# Ce que le classifieur console partagé comprend (``console_keys._REGION_BASE_OF``).
_CONSOLE_TEXT = {"eu": "Europe", "global": "WW", "uk": "UK", "us": "US"}


def region_slot(name: str) -> str | None:
    """Le texte de la parenthèse finale (avant un éventuel « - DLC »), ou None."""

    m = _SLOT_RE.search(name or "")
    return m.group("slot") if m else None


def _base(slot: str | None) -> str | None:
    return REGION_TEXT.get(re.sub(r"\s+", " ", slot or "").strip().lower())


def title_region(name: str) -> str | None:
    """eu / global / uk / us quand la parenthèse le dit ; None sinon — sans parenthèse, le
    matcher applique le GLOBAL implicite (décision 2 de Romain), et une parenthèse non
    vendable a déjà été refusée par ``precheck``."""

    return _base(region_slot(name))


def console_region_slot(name: str) -> str | None:
    """Le même créneau pour les lignes console, traduit dans le vocabulaire partagé
    (« Europe & UK » → « Europe ») ; un texte non vendable passe tel quel, et le classifieur
    en fait un refus ``forbidden region``."""

    slot = region_slot(name)
    if slot is None:
        return None
    base = _base(slot)
    return _CONSOLE_TEXT[base] if base else slot


# ── nom : ce qui n'est pas le produit, retiré depuis la FIN ───────────────────────────
_DLC_TAIL_RE = re.compile(r"\s*-\s*DLC\s*$", re.IGNORECASE)
_PAREN_TAIL_RE = re.compile(r"\s*\([^()]*\)\s*$")
_PLATFORM_TAIL_RE = re.compile(
    r"\s+(?:Xbox\s*/\s*PC|Xbox\s+Series\s+X\s*\|\s*S|Xbox\s+One|Xbox"
    r"|Switch\s*&\s*Switch\s*2|Nintendo\s+Switch(?:\s*2)?|Switch(?:\s*2)?"
    r"|PlayStation\s*[45]|PS[45]|PC)\s*$", re.IGNORECASE)


def _peel(name: str, keep_dlc: bool) -> str:
    text = (name or "").strip()
    dlc = bool(_DLC_TAIL_RE.search(text))
    text = _DLC_TAIL_RE.sub("", text)
    if region_slot(name) is not None:
        text = _PAREN_TAIL_RE.sub("", text)
    text = _PLATFORM_TAIL_RE.sub("", text).strip()
    return f"{text} (DLC)" if (dlc and keep_dlc) else text


def resolve_name(name: str) -> str:
    """Le produit seul, pour le slug AKS : « - DLC », la région puis la plateforme sont
    retirées depuis la fin (« Zero Caliber 2 Remastered PC » → « Zero Caliber 2 Remastered »).
    Rien n'est retiré du MILIEU du nom."""

    return _peel(name, keep_dlc=False)


def guard_name(name: str) -> str:
    """Le titre que lisent les gardes de nom : le même, mais le « - DLC » du marchand reste
    un marqueur DLC (« … (DLC) »), pour que R43 s'applique comme ailleurs."""

    return _peel(name, keep_dlc=True)


# ── URL : le lien d'affiliation cache la fiche ────────────────────────────────────────
def product_url(url: str) -> str:
    """La fiche réelle (paramètre ``u`` du lien ``go.loaded.com``), ou l'URL elle-même."""

    parts = urlsplit(url or "")
    cible = parse_qs(parts.query).get("u")
    return cible[0] if cible else (url or "")


def product_slug(url: str) -> str:
    return urlsplit(product_url(url)).path.strip("/").lower()


_STORE_TOKENS: tuple[tuple[str, str], ...] = (
    ("steam", "STEAM"), ("epic", "EPIC"), ("gog", "GOG"), ("ubisoft", "UBISOFT"),
    ("uplay", "UBISOFT"), ("origin", "EA"), ("ea-app", "EA"), ("rockstar", "ROCKSTAR"),
    ("battle-net", "BATTLENET"), ("battlenet", "BATTLENET"),
)
_PC_STORE_RE = re.compile(
    r"-pc(?:-dlc)?-(?P<store>" + "|".join(re.escape(t) for t, _ in _STORE_TOKENS) + r")(?:-[a-z]{2,3})?$")


def url_platform(url: str) -> str | None:
    """La boutique d'une clé PC, lue dans le slug de la fiche (« …-pc-steam-eu » → STEAM).
    None pour tout autre slug (console, ou slug qui ne la dit pas) — jamais une boutique
    devinée."""

    m = _PC_STORE_RE.search(product_slug(url))
    return dict(_STORE_TOKENS)[m.group("store")] if m else None


_CONSOLE_SLUG_RUNS: tuple[tuple[str, str], ...] = (
    ("xbox-series-x-s", "XBOX_SERIES"), ("xbox-series", "XBOX_SERIES"), ("xbox-one", "XBOX_ONE"),
    ("ps5", "PS5"), ("ps4", "PS4"), ("switch-2", "SWITCH2"),
)


def console_url_families(url: str) -> tuple[str, ...] | None:
    """Les générations console que le slug de la FICHE déclare (« towerborne-xbox-series-x-s-pc-eu »
    → XBOX_SERIES), consultées seulement quand le titre n'en déclare aucune (« Xbox/PC »). None
    quand le slug ne dit rien (« …-xbox-pc-eu ») : la ligne reste alors refusée « no declared
    generation », comme ailleurs."""

    slug = "-" + product_slug(url) + "-"
    familles: list[str] = []
    for run, fam in _CONSOLE_SLUG_RUNS:
        if f"-{run}-" in slug and fam not in familles:
            familles.append(fam)
    return tuple(familles) or None


def console_pc_declared(name: str, url: str) -> bool:
    """« Xbox/PC » dans le titre, ou « -pc » à côté de la plateforme dans le slug."""

    return bool(re.search(r"Xbox\s*/\s*PC", name or "", re.IGNORECASE)) or "-pc-" in (
        "-" + product_slug(url) + "-")


def precheck(name: str, url: str) -> str | None:
    """Refus propres à Loaded : un lien d'affiliation sans fiche (pas de ``u``), et une
    parenthèse de région qu'on ne sait pas vendre — verrou connu (« North America ») ou texte
    inconnu, refusé par son nom."""

    if "go.loaded.com" in (url or "").lower() and product_url(url) == url:
        return "Loaded : lien d'affiliation sans fiche produit (paramètre u absent) (R61)"
    slot = region_slot(name)
    if slot is None or _base(slot) is not None:
        return None
    return forbidden_reason(slot) or f"Loaded : région « {slot} » inconnue — non entré (R61)"


CONFIG = make_config(
    "Loaded",
    domain=DOMAIN,
    precheck=precheck,
    title_region=title_region,
    resolve_name=resolve_name,
    guard_name=guard_name,
    url_platform=url_platform,
    console_region_slot=console_region_slot,
    console_url_families=console_url_families,
    console_pc_declared=console_pc_declared,
    notes=("feed store 40 (ex-CDKeys). [R61] région = parenthèse finale du titre (« Europe & UK » "
           "→ Europe, sans parenthèse → GLOBAL implicite, décisions de Romain du 2026-09-25) ; "
           "boutique PC = slug de la fiche, dans le paramètre u du lien d'affiliation."),
)
