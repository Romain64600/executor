"""Discover.games (feed store 168) — `[R60]`, 2026-09-25.

Romain, 2026-09-25 : « go pour Discover.games ». Étude du même jour :
`docs/PROCHAINS_MARCHANDS.md`.

Boutique officielle (clés d'éditeurs, prix par pays) : les titres du feed sont NUS
(« Potion Permit », « Layers of Fear ») et l'URL aussi (``discover.games/games/<slug>``). Tout
vient de la **fiche produit**, lisible en HTTP simple (redirigée vers ``www.``), qui embarque
l'objet ``sellableProductDetail`` de l'application :

* ``platform`` : ``STEAM`` (23 fiches sur 25 le 25/09)… → notre plateforme ;
* ``skus[].availableCountries`` : les pays où chaque déclinaison est VENDUE — ``["WW"]`` pour le
  monde entier (13 fiches sur 25), sinon des listes de codes ISO (jusqu'à 249 pays, découpés en
  groupes de prix).

**Région : la règle de Romain pour Gamesplanet FR `[R59]`**, appliquée aux pays où le produit n'est
PAS vendu (le complément de l'union des ``availableCountries``) :

=============================================  ==========
``WW``, ou ni UE, ni Royaume-Uni, ni USA exclus  GLOBAL
UE couverte, USA exclus                          Europe
un pays de l'UE exclu, USA couverts              US
UE et USA exclus                                  refus
UE et USA couverts, Royaume-Uni seul exclu        refus
=============================================  ==========

C'est aussi ce que fait AKS pour les boutiques officielles à prix par pays présentes sur les mêmes
pages (lu le 25/09 sur 15 pages : Fanatical 14/14, GamersGate 14/14, Greenmangaming 10/10, Humble
5/5, Steam 16/16 en Steam GLOBAL).

**Produit introuvable** (Romain : « il faudra essayer d'ouvrir la page pour être sûr que ce soit
pas un product not found ») : une fiche 404, sans ``sellableProductDetail``, sans plateforme ou
sans aucune déclinaison en vente est REFUSÉE — jamais une région par défaut.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable

from src.aks_env import REQUIRED_USER_AGENT, http_get
from src.merchant_config import MerchantOfferSignals
from src.merchants.common import make_config

DOMAIN = "discover.games"
PROBE_DELAY_S = 0.6                   # politesse sur un sweep en masse, comme Gamerall

PLATFORM_MAP: dict[str, str] = {
    "STEAM": "STEAM", "GOG": "GOG", "EPIC": "EPIC", "EPIC_GAMES": "EPIC",
    "UBISOFT": "UBISOFT", "UPLAY": "UBISOFT", "UBISOFT_CONNECT": "UBISOFT",
    "EA": "EA", "ORIGIN": "EA", "EA_APP": "EA", "BATTLENET": "BATTLENET",
    "BATTLE_NET": "BATTLENET", "ROCKSTAR": "ROCKSTAR", "MICROSOFT": "MICROSOFT",
}
EU_MEMBERS: frozenset[str] = frozenset({
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT",
    "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE",
})
UK, US, WORLDWIDE = "GB", "US", "WW"


class DiscoverProductUnavailable(RuntimeError):
    """Fiche introuvable, illisible, ou produit sans déclinaison en vente : on refuse."""


def _json_object_after(text: str, key: str) -> dict[str, Any] | None:
    """L'objet JSON qui suit ``key`` dans la charge utile de la page (guillemets déjà
    déséchappés), ou None."""

    i = text.find(key)
    if i < 0:
        return None
    k = text.find("{", i + len(key))
    if k < 0:
        return None
    depth, in_str, esc = 0, False, False
    for n in range(k, len(text)):
        ch = text[n]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[k:n + 1])
                except ValueError:
                    return None
    return None


def parse_product(body: str) -> tuple[str | None, frozenset[str]]:
    """``(plateforme brute, pays où le produit est vendu)`` lus dans la fiche. Lève
    :class:`DiscoverProductUnavailable` si l'objet manque, ou si aucune déclinaison n'est en
    vente — le signe d'un produit retiré."""

    detail = _json_object_after(body.replace('\\"', '"'), '"sellableProductDetail":')
    if not detail:
        raise DiscoverProductUnavailable("fiche sans sellableProductDetail (produit retiré ?)")
    skus = detail.get("skus") or []
    pays = frozenset(str(c).upper() for s in skus for c in (s.get("availableCountries") or []))
    if not pays:
        raise DiscoverProductUnavailable("aucune déclinaison en vente sur la fiche")
    return (str(detail["platform"]).upper() if detail.get("platform") else None), pays


def region_from_countries(pays: frozenset[str]) -> tuple[str | None, str]:
    """La règle de Romain (`[R59]`), sur les pays NON couverts. ``(base, libellé de refus)``."""

    if WORLDWIDE in pays:
        return "global", ""
    eu_exclu = not EU_MEMBERS <= pays
    uk_exclu, us_exclu = UK not in pays, US not in pays
    if not eu_exclu and not uk_exclu and not us_exclu:
        return "global", ""
    if not eu_exclu and us_exclu:
        return "eu", ""
    if eu_exclu and not us_exclu:
        return "us", ""
    if eu_exclu and us_exclu:
        return None, "DISCOVER LOCK (EU + US)"
    return None, "DISCOVER LOCK (UK)"


def fetch_product(url: str, http_get_fn: Callable[..., Any] = http_get) -> tuple[str | None, frozenset[str]]:
    """Ouvre la fiche (la redirection vers ``www.`` est suivie). Lève si introuvable."""

    if http_get_fn is http_get:
        time.sleep(PROBE_DELAY_S)
    try:
        page = http_get_fn(url, timeout=20, user_agent=REQUIRED_USER_AGENT)
    except Exception as exc:                 # noqa: BLE001 — tout échec = refus
        raise DiscoverProductUnavailable(f"fiche Discover.games injoignable : {exc}") from exc
    if page.status == 404:
        raise DiscoverProductUnavailable("product not found (404)")
    if not (page.ok and page.status == 200 and page.body):
        raise DiscoverProductUnavailable(f"réponse inattendue : {page.status or page.error}")
    return parse_product(page.body)


def offer_signals(url: str, name: str = "",
                  http_get_fn: Callable[..., Any] = http_get) -> MerchantOfferSignals:
    """Plateforme et région lues sur la fiche. Une plateforme inconnue rend ``platform=None``
    (le matcher refuse, R32) ; une région hors règle rend un libellé de refus."""

    brute, pays = fetch_product(url, http_get_fn)
    platform = PLATFORM_MAP.get(brute or "")
    base, label = region_from_countries(pays)
    if base is None:
        return MerchantOfferSignals(platform=platform, region_resolved=True,
                                    region_base=None, region_label=label)
    return MerchantOfferSignals(platform=platform, region_resolved=True, region_base=base)


CONFIG = make_config(
    "Discover.games",
    domain=DOMAIN,
    offer_page_resolver=offer_signals,
    notes=("feed store 168. [R60] titre et URL nus : plateforme = sellableProductDetail.platform "
           "de la fiche, région = pays où le produit est vendu (WW = monde), règle de Romain "
           "[R59] ; fiche 404 / sans déclinaison en vente = refus."),
)
