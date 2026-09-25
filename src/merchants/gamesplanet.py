"""Gamesplanet FR (feed store 55) — `[R59]`, 2026-09-25.

Romain, 2026-09-25 : « go pour Gamesplanet FR avec ta règle + un pays UE exclu mais États-Unis
autorisés → US ». Étude du même jour : `docs/PROCHAINS_MARCHANDS.md`.

Gamesplanet est un revendeur OFFICIEL (clés d'éditeurs) : ses titres sont nus (« Regulators »,
« The Surge 2 - Premium Edition »), sans plateforme ni région. Ce fichier lit ce que le marchand
écrit ailleurs, et rien d'autre :

* **la plateforme dans l'URL**, en clair, juste avant l'identifiant :
  ``…/game/regulators-steam-key--7963-1`` (474 lignes sur 526 le 21/09), ``-gog-key--`` (12),
  ``-epic-games-key--`` (8), ``-microsoft-store-download--`` (16), ``-rockstar-key--`` (3).
  Un segment inconnu (``-arenanet-key--``, ``-edition-download--``…) est REFUSÉ par son nom —
  jamais deviné ;
* **la région sur la page produit**, lisible en HTTP simple (200, ~70 Ko, pas de Cloudflare). La
  page porte, quand la clé est bridée, un bloc « REGION LOCK INFO » : « It will NOT activate in:
  Japan » (liste courte, en ligne) ou « It will NOT activate in specific countries/regions: See
  full list » (liste complète dans la fenêtre ``#modal_regionlocks_details``) — ou la variante
  « It will ONLY activate in … » (liste des pays AUTORISÉS). Sans bloc, la clé n'est pas bridée.

La règle de Romain, appliquée aux pays EXCLUS (pour une liste « ONLY », les exclus sont ceux qui
n'y figurent pas) :

=====================================================  ==========================
aucun pays de l'UE, ni le Royaume-Uni, ni les USA      GLOBAL
UE autorisée, États-Unis exclus                         Europe
un pays de l'UE exclu, États-Unis autorisés             US
un pays de l'UE exclu ET les États-Unis exclus          refus
UE et USA autorisés, Royaume-Uni seul exclu             refus (cas non tranché)
page illisible, ou page sans les repères d'une fiche     refus
=====================================================  ==========================
"""

from __future__ import annotations

import html
import re
import time
from typing import Any, Callable
from urllib.parse import urlsplit

from src.aks_env import REQUIRED_USER_AGENT, http_get
from src.merchant_config import MerchantOfferSignals
from src.merchants.common import make_config

DOMAIN = "gamesplanet.com"            # fr.gamesplanet.com — l'hôte est contrôlé par le suffixe
PROBE_DELAY_S = 0.6                   # politesse sur un sweep en masse, comme Gamerall

# ── plateforme : le segment de livraison de l'URL ─────────────────────────────────────
# « …/game/<slug>-<livraison>--<id>-<n> ». Seules les livraisons dont la plateforme AKS est
# certaine sont mappées ; tout le reste est refusé en le NOMMANT.
URL_DELIVERY_PLATFORM: dict[str, str] = {
    "steam-key": "STEAM",
    "gog-key": "GOG",
    "epic-games-key": "EPIC",
    "microsoft-store-download": "MICROSOFT",   # famille « Windows 10 » (R50) pour les jeux
    "rockstar-key": "ROCKSTAR",
    "ubisoft-connect-key": "UBISOFT",
    "uplay-key": "UBISOFT",
    "ea-app-key": "EA",
    "origin-key": "EA",
    "battle-net-key": "BATTLENET",
}
_DELIVERY_RE = re.compile(
    r"/game/(?P<slug>.+?)-(?P<delivery>" + "|".join(
        re.escape(k) for k in sorted(URL_DELIVERY_PLATFORM, key=len, reverse=True))
    + r")--\d+(?:-\d+)?/?$")
_ANY_DELIVERY_RE = re.compile(r"/game/.+-(?P<word>[a-z]+-(?:key|download))--\d+(?:-\d+)?/?$")


def url_delivery(url: str) -> str | None:
    """Le segment de livraison mappé (``steam-key``…), ou None."""

    m = _DELIVERY_RE.search(urlsplit(url or "").path.lower())
    return m.group("delivery") if m else None


def url_platform(url: str) -> str | None:
    """STEAM / GOG / EPIC / MICROSOFT / ROCKSTAR / UBISOFT / EA / BATTLENET, ou None."""

    d = url_delivery(url)
    return URL_DELIVERY_PLATFORM.get(d) if d else None


def precheck(name: str, url: str) -> str | None:
    """Refus catégoriques propres à Gamesplanet : une livraison que l'URL ne dit pas, ou qu'on
    ne sait pas ranger sur AKS (``arenanet-key``, ``edition-download``…), est refusée par son
    nom — jamais une plateforme devinée."""

    if url_delivery(url) is not None:
        return None
    m = _ANY_DELIVERY_RE.search(urlsplit(url or "").path.lower())
    if m:
        return (f"Gamesplanet : livraison « {m.group('word')} » sans plateforme AKS connue "
                "— non entré (R59)")
    return "Gamesplanet : aucune livraison lisible dans l'URL — plateforme inconnue (R59)"


# ── région : la page produit ──────────────────────────────────────────────────────────
EU_MEMBERS: frozenset[str] = frozenset({
    "austria", "belgium", "bulgaria", "croatia", "cyprus", "czechia", "denmark", "estonia",
    "finland", "france", "germany", "greece", "hungary", "ireland", "italy", "latvia",
    "lithuania", "luxembourg", "malta", "netherlands", "poland", "portugal", "romania",
    "slovakia", "slovenia", "spain", "sweden",
})
# Orthographes de Gamesplanet relevées le 2026-09-25 (209 noms sur 30 pages) + synonymes usuels.
_ALIASES: dict[str, str] = {
    "czech republic": "czechia", "the netherlands": "netherlands", "slovak republic": "slovakia",
    "united kingdom of great britain and northern ireland": "united kingdom",
    "great britain": "united kingdom", "uk": "united kingdom",
    "united states of america": "united states", "usa": "united states",
    "us": "united states",
}
UK, US = "united kingdom", "united states"

_PRODUCT_PAGE_MARKERS = ('class="prod-data"', "platform badge")
_NOTICE_RE = re.compile(r"REGION LOCK INFO</p>(?P<notice>.*?)</strong>", re.S)
_MODE_RE = re.compile(r"It will\s*<u>\s*(NOT|ONLY)\s*</u>\s*activate in", re.S)
_MODAL_RE = re.compile(
    r'id="modal_regionlocks_details".*?activate in:\s*(?:</[^>]+>\s*|<[^>/][^>]*>\s*)*'
    r"(?P<list>[^<]+)", re.S)
_INLINE_RE = re.compile(r"activate in:\s*(?P<list>[^<]+)$", re.S)


class GamesplanetPageUnreadable(RuntimeError):
    """Page marchand illisible, ou lisible mais sans les repères d'une fiche produit : on
    refuse, on ne devine pas de région."""


def _country(raw: str) -> str:
    key = re.sub(r"\s+", " ", html.unescape(raw)).strip().lower()
    return _ALIASES.get(key, key)


def parse_region_lock(body: str) -> tuple[str, frozenset[str]] | None:
    """``None`` quand la fiche ne porte AUCUN bloc « REGION LOCK INFO » (clé non bridée) ;
    sinon ``("NOT" | "ONLY", pays)``. Lève si la page n'est pas une fiche produit, ou si un
    bloc présent ne se lit pas (gabarit changé) — jamais un GLOBAL par défaut dans ce cas."""

    if not all(m in body for m in _PRODUCT_PAGE_MARKERS):
        raise GamesplanetPageUnreadable(
            "page sans les repères d'une fiche produit (prod-data / platform badge)")
    notice = _NOTICE_RE.search(body)
    if notice is None:
        if "REGION LOCK INFO" in body:
            raise GamesplanetPageUnreadable("bloc REGION LOCK INFO présent mais illisible")
        return None
    mode = _MODE_RE.search(notice.group("notice"))
    if mode is None:
        raise GamesplanetPageUnreadable("bloc REGION LOCK INFO sans « NOT » ni « ONLY »")
    liste = _MODAL_RE.search(body) or _INLINE_RE.search(notice.group("notice"))
    if liste is None:
        raise GamesplanetPageUnreadable("liste de pays introuvable dans le bloc REGION LOCK")
    pays = frozenset(c for c in (_country(x) for x in liste.group("list").split(",")) if c)
    if not pays:
        raise GamesplanetPageUnreadable("liste de pays vide dans le bloc REGION LOCK")
    return mode.group(1), pays


def region_from_lock(lock: tuple[str, frozenset[str]] | None) -> tuple[str | None, str]:
    """La règle de Romain (2026-09-25). Rend ``(base, libellé)`` : base ``global`` / ``eu`` /
    ``us`` pour entrer, ou ``None`` + un libellé pour le refus « forbidden region: … »."""

    if lock is None:
        return "global", ""
    mode, pays = lock
    if mode == "NOT":
        eu_exclu = bool(EU_MEMBERS & pays)
        uk_exclu, us_exclu = UK in pays, US in pays
    else:                                   # ONLY : exclus = absents de la liste
        eu_exclu = not EU_MEMBERS <= pays
        uk_exclu, us_exclu = UK not in pays, US not in pays
    if not eu_exclu and not uk_exclu and not us_exclu:
        return "global", ""
    if not eu_exclu and us_exclu:
        return "eu", ""
    if eu_exclu and not us_exclu:
        return "us", ""
    if eu_exclu and us_exclu:
        return None, "GAMESPLANET LOCK (EU + US)"
    return None, "GAMESPLANET LOCK (UK)"


def fetch_region(url: str, http_get_fn: Callable[..., Any] = http_get) -> tuple[str | None, str]:
    """Ouvre la fiche et applique la règle. Lève si la page est illisible."""

    if http_get_fn is http_get:
        time.sleep(PROBE_DELAY_S)
    try:
        page = http_get_fn(url, timeout=20, user_agent=REQUIRED_USER_AGENT)
    except Exception as exc:                 # noqa: BLE001 — tout échec = refus
        raise GamesplanetPageUnreadable(f"page Gamesplanet injoignable : {exc}") from exc
    if not (page.ok and page.status == 200 and page.body):
        raise GamesplanetPageUnreadable(f"réponse inattendue : {page.status or page.error}")
    return region_from_lock(parse_region_lock(page.body))


def offer_signals(url: str, name: str = "",
                  http_get_fn: Callable[..., Any] = http_get) -> MerchantOfferSignals:
    """Plateforme lue dans l'URL, région lue sur la page (le titre et l'URL n'en disent rien
    chez Gamesplanet : 0 ligne sur 526 le 21/09). Une livraison inconnue a déjà été refusée par
    ``precheck`` ; une page illisible lève → le matcher refuse (R32)."""

    platform = url_platform(url)
    base, label = fetch_region(url, http_get_fn)
    if base is None:
        return MerchantOfferSignals(platform=platform, region_resolved=True,
                                    region_base=None, region_label=label)
    return MerchantOfferSignals(platform=platform, region_resolved=True, region_base=base)


CONFIG = make_config(
    "Gamesplanet FR",
    domain=DOMAIN,
    precheck=precheck,
    offer_page_resolver=offer_signals,
    # Les titres sont nus : la plateforme vient de l'URL (via le résolveur), jamais d'un mot
    # du titre (« Minecraft Dungeons (Microsoft Store) » : l'URL le dit aussi, sans ambiguïté).
    title_is_platform_source=False,
    notes=("feed store 55 (fr.gamesplanet.com). [R59] plateforme = segment de livraison de l'URL "
           "(steam-key / gog-key / epic-games-key / microsoft-store-download / rockstar-key…), "
           "région = bloc REGION LOCK de la fiche, règle de Romain du 2026-09-25."),
)
