"""eww.gg (feed store 170) — la seconde boutique de Driffle UAB, déclarée le 2026-10-07 sur
instruction de Romain (« Store ID 170 stop B et lance le data entry pour ce nouveau shop »).

Étude du 07/10 (`docs/PROCHAINS_MARCHANDS.md`) : le pied de page dit « Possédé et exploité par
Driffle UAB » ; le titre a LA grammaire de Driffle, à l'identique ::

    <Game> [<Edition>] [(<Region>)] [(<Platform>)] - <Store> - <Delivery>
    George VS Bonny PP Wars (Global) (PC) - Steam - Digital Key                  → global, STEAM

et l'URL aussi, au suffixe près : ``eww.gg/<slug>-<region>-<platform>-<store>-digital-key-<id>``
(Driffle écrit ``-p<id>``). La fiche se lit en HTTP (200, UA navigateur ; « Plateforme Steam »,
« Région Monde », « Version Standard ») — non lue ici : le titre dit déjà la région et la
plateforme, comme chez Driffle ([R45] / R32e). Ce module est donc une DÉCLINAISON de
:mod:`src.merchants.driffle` : mêmes hooks (``precheck`` sur la parenthèse de région,
``title_region``, ``console_region_slot``, ``console_noise``), seule la lecture des familles
console dans l'URL diffère par le suffixe d'identifiant. Toute règle nouvelle qu'on découvrirait
chez eww.gg se déclare ICI, jamais dans le générique.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from src.merchants import driffle
from src.merchants.common import make_config

DOMAIN = "eww.gg"

precheck = driffle.precheck
title_region = driffle.title_region
console_region_slot = driffle.console_region_slot
region_bracket = driffle.region_bracket

# Comme Driffle, avec l'identifiant nu en fin de slug (``-151108``) à la place de ``-p<id>``.
_URL_RUN_RE = re.compile(
    r"-(?P<run>(?:(?:pc|mac|linux|ps4|ps5|xbox-one|xbox-series-xs|xbox-series-x-s|"
    r"nintendo-switch-2|nintendo-switch)-)+)(?:xbox-live|psn|nintendo|xbox)-digital-(?:key|code)-p?\d+/?$"
)


def console_url_families(url: str) -> tuple[str, ...] | str | None:
    """Les familles console que le slug eww.gg déclare avant la boutique console et la
    livraison : ``…-europe-xbox-one-xbox-series-xs-xbox-live-digital-key-151234`` → XBOX_ONE,
    XBOX_SERIES ; rien de reconnu → None (la grammaire de Driffle, suffixe d'id adapté)."""

    path = urlsplit(url or "").path.lower()
    m = _URL_RUN_RE.search(path)
    if not m:
        return None
    families: list[str] = []
    for token in re.findall(r"xbox-series-x-s|xbox-series-xs|xbox-one|nintendo-switch-2|nintendo-switch|ps4|ps5",
                            m.group("run")):
        fam = driffle._URL_TOKEN_FAMILY[token]
        if fam not in families:
            families.append(fam)
    return tuple(families) or None


CONFIG = make_config(
    "eww.gg",
    domain=DOMAIN,
    precheck=precheck,
    title_region=title_region,
    console_region_slot=console_region_slot,
    console_url_families=console_url_families,
    console_noise=("Digital Key", "Digital Code"),
    notes=("feed store 170 (Romain, 2026-10-07) ; boutique de Driffle UAB, grammaire de titre "
           "identique à Driffle : '<Game> (<Region>) (<Platform>) - <Store> - Digital Key', région = "
           "première parenthèse du vocabulaire ; URL '<slug>-<region>-<platform>-<store>-digital-key-"
           "<id>' ; fiche lisible en HTTP, non lue (le titre suffit)"),
)
