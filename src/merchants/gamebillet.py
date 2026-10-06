"""Gamebillet (feed store 15) — `[R71]` : la FICHE produit fait foi (plateforme, pays restreints,
DLC). Romain, 2026-10-06 : « Puis Gamebillet », juste après le go d'Indiegala `[R69]` — même
modèle (Allyouplay `[R68]` → Indiegala `[R69]`), même règle de région `[R59]`.

**Le titre et l'URL ne disent rien** : « Dunebound Tactics », `gamebillet.com/dunebound-tactics`
(268 lignes au scan tous-magasins du 21/09 ; un suffixe d'URL `-2` / `-z` / `-pre-purchase` sans
sens produit ; quelques titres bilingues « Attack on Titan 3 / A.O.T. 3 », gardés entiers comme
chez Indiegala — R01 refuse au pire, jamais un nom deviné).

**La fiche se lit en HTTP** (200, UA navigateur, bibliothèque standard — jamais `aks_env.http_get`,
même raison que `[R68]` ; 51 fiches sur 51 le 06/10) et dit tout :

* **plateforme** : la ligne **« Delivery »** du tableau de spécifications (`Publisher / Developer
  / Platform / Delivery / Release Date / Genres / Languages / Features`) — « Steam » sur 51 / 51.
  La ligne « Platform » est le SYSTÈME (Windows / Linux / Mac), pas la boutique : elle est lue
  pour mémoire, jamais pour décider. Un libellé de livraison connu → notre jeton
  (``DELIVERY_TEXT``) ; absent ou inconnu → refus NOMMÉ, jamais STEAM par défaut ;
* **région** : la fenêtre « Restricted countries » (`#restrictedcountries-popup`), une liste de
  pays séparés par des virgules où la clé ne s'active PAS → règle `[R59]` de Romain sur les pays
  EXCLUS (`gamesplanet.region_from_lock`, mode « NOT ») : ni UE, ni UK, ni USA exclus → GLOBAL
  (même avec 130 pays d'Asie / d'Amérique latine exclus) ; USA exclus sans l'UE → EU ; un pays
  de l'UE exclu sans les USA → US ; UE et USA exclus → refus « LOCK (EU + US) ». Une fenêtre
  présente mais VIDE = aucune restriction = GLOBAL ; une fenêtre ABSENTE = gabarit changé = refus.
  L'info-bulle « This product can be activated and played in your current region » est la
  politique de vente du site, IGNORÉE comme chez Gamesplanet et Indiegala ;
* **DLC : la fiche NE SAIT PAS le dire.** Le seul mot approchant, « Downloadable Content » dans la
  ligne « Features », est une catégorie de fonctionnalités Steam que portent aussi des JEUX DE
  BASE (« FAIRY TAIL 2 Digital Deluxe » la porte : à l'aperçu du 06/10 un premier essai en
  faisait une garde DLC et refusait cette édition Deluxe à tort ; 42 vrais DLC sur 45 ne la
  portaient pas). Donc ``MerchantOfferSignals.dlc`` reste ``None`` : le seau DLC(16) est l'affaire
  des règles de titre R18 / `[R43]` / `[R57]` et de la page AKS, comme pour tout marchand sans
  signal de fiche. La ligne Features est gardée pour mémoire (`ProductPage.features`) ;
* **fiche périmée** : un produit retiré répond 404 (la page d'accueil « GameBillet | PC, Mac and
  Linux Games », sans tableau ni fenêtre) → refus. Aucun lien canonique sur ces pages : l'identité
  est le chemin demandé, et une page 200 sans les repères d'une fiche est refusée.

Hors liste blanche et hors groupe tant que Romain n'a pas vu l'aperçu
(`docs/apercu_gamebillet_2026-10-06.md`). Décisions PROPOSÉES ici (les miennes, à confirmer) :
(1) « Delivery » = plateforme, « Platform » (OS) ignoré ; (2) `[R59]` sur la fenêtre des pays
restreints, fenêtre VIDE = GLOBAL (24 entrées sur 165 à l'aperçu) ; (3) aucun signal DLC de la
fiche ; (4) titre bilingue gardé entier. Si une fiche disait « North America » (aucune vue), le vocabulaire partagé la refuserait
comme aujourd'hui — le travail NA (`[R70]`) est séparé.
"""

from __future__ import annotations

import html
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlsplit

from src.aks_env import REQUIRED_USER_AGENT, HttpProbeResult
from src.merchant_config import MerchantOfferSignals
from src.merchants.common import make_config
from src.merchants.gamesplanet import _country as country_name
from src.merchants.gamesplanet import region_from_lock

DOMAIN = "gamebillet.com"
PROBE_DELAY_S = 1.0                   # ~1 requête / s sur un balayage complet (~270 fiches)
RULE = "R71"

# La ligne « Delivery » du tableau → notre jeton de plateforme. Seul « Steam » a été VU
# (51 / 51 le 06/10) ; les autres libellés sont les orthographes usuelles de ces boutiques, pour
# qu'une fiche qui les écrirait un jour entre à la bonne place — tout autre texte est un refus.
DELIVERY_TEXT: dict[str, str] = {
    "steam": "STEAM",
    "gog": "GOG", "gog.com": "GOG",
    "epic games": "EPIC", "epic games store": "EPIC", "epic": "EPIC",
    "origin": "EA", "ea app": "EA",
    "ubisoft connect": "UBISOFT", "uplay": "UBISOFT",
    "rockstar": "ROCKSTAR", "rockstar games launcher": "ROCKSTAR",
    "battle.net": "BATTLENET",
    "microsoft store": "MICROSOFT",
}
_SPEC_TABLE_MARKER = 'class="table-responsive"'
_MODAL_RE = re.compile(r'<div\b[^>]*\bid="restrictedcountries-popup"[^>]*>', re.I)
# La liste vit dans `<div class="popup-small-content"><div class="text-center">…</div></div>`
# (pas de `modal-body` sur ce gabarit) ; à défaut, le texte de toute la fenêtre (le bouton de
# fermeture n'a pas de texte).
_MODAL_BODY_RE = re.compile(r'<div\b[^>]*\bclass="[^"]*\btext-center\b[^"]*"[^>]*>(?P<body>.*?)</div>',
                            re.S | re.I)
_TABLE_RE = re.compile(r"<table\b[^>]*>(?P<table>.*?)</table>", re.S | re.I)
_ROW_RE = re.compile(r"<tr\b[^>]*>(?P<row>.*?)</tr>", re.S | re.I)
_CELL_RE = re.compile(r"<t[dh]\b[^>]*>(?P<cell>.*?)</t[dh]>", re.S | re.I)
_H1_RE = re.compile(r"<h1\b[^>]*>(?P<h1>.*?)</h1>", re.S | re.I)


class GamebilletPageUnreadable(RuntimeError):
    """Fiche injoignable, absente, ou lisible mais sans ce qu'il faut pour décider : on refuse,
    on ne devine ni la plateforme ni la région."""


@dataclass(frozen=True)
class ProductPage:
    path: str                                   # chemin demandé, en minuscules (pas de canonique)
    title: str                                  # le <h1> de la fiche
    delivery_text: str                          # « Steam » — la ligne Delivery
    os_text: str                                # « Windows » / « Linux » — la ligne Platform (mémoire)
    features: str                               # la ligne Features, telle quelle (mémoire)
    restricted: frozenset[str]                  # pays normalisés où la clé ne s'active pas


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def _on_domain(url: str) -> bool:
    host = _host(url)
    return host == DOMAIN or host.endswith("." + DOMAIN)


def _norm_path(path: str) -> str:
    return (path or "").rstrip("/").lower()


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


def _balanced_div(body: str, start: int) -> str | None:
    """Le ``<div …>`` ouvert à ``start`` jusqu'à sa fermeture de même profondeur, ou None."""

    depth = 0
    for m in re.finditer(r"<div\b|</div\s*>", body[start:], re.I):
        depth += 1 if m.group(0).lower().startswith("<div") else -1
        if depth == 0:
            return body[start:start + m.end()]
    return None


def spec_table(body: str) -> dict[str, str]:
    """Les lignes du tableau de spécifications (« Publisher », « Platform », « Delivery »…)."""

    for table in _TABLE_RE.finditer(body):
        rows: dict[str, str] = {}
        for row in _ROW_RE.finditer(table.group("table")):
            cells = [_clean(c.group("cell")) for c in _CELL_RE.finditer(row.group("row"))]
            if len(cells) >= 2 and cells[0]:
                rows[cells[0]] = cells[1]
        if "Delivery" in rows or "Platform" in rows:
            return rows
    return {}


def restricted_countries(body: str) -> frozenset[str]:
    """La liste de la fenêtre « Restricted countries », normalisée (``gamesplanet._country``).
    Vide = aucune restriction. Lève si la fenêtre manque ou ne se lit pas (gabarit changé).

    La liste est séparée par des virgules et certains NOMS en portent une (« Korea, Democratic
    People's Republic of », « Iran (Islamic Republic of) » n'en a pas, « Congo (Democratic
    Republic of the) » non plus). La coupe produit des fragments (« democratic people's republic
    of ») SANS EFFET sur la décision : seuls les 27 noms de l'UE, « united kingdom » et « united
    states » comptent, et aucun fragment ne les vaut. Épinglé par un test sur les listes réelles."""

    opening = _MODAL_RE.search(body)
    if opening is None:
        raise GamebilletPageUnreadable(
            f"fiche sans fenêtre « Restricted countries » — gabarit changé, non entrée ({RULE})")
    block = _balanced_div(body, opening.start())
    if block is None:
        raise GamebilletPageUnreadable(f"fenêtre « Restricted countries » illisible ({RULE})")
    inner = _MODAL_BODY_RE.search(block)
    raw = _clean(inner.group("body")) if inner else _clean(block)
    return frozenset(c for c in (country_name(x) for x in raw.split(",")) if c)


def parse_product_page(body: str, expected_path: str) -> ProductPage:
    """Lit une fiche gamebillet.com. Lève ``GamebilletPageUnreadable`` pour tout ce qui n'est pas
    une fiche produit lisible avec sa livraison et sa fenêtre de pays."""

    if _SPEC_TABLE_MARKER not in body:
        raise GamebilletPageUnreadable(
            f"page sans le tableau d'une fiche produit (table-responsive) — fiche retirée ou "
            f"gabarit changé, non entrée ({RULE})")
    spec = spec_table(body)
    delivery = spec.get("Delivery", "")
    if not delivery:
        raise GamebilletPageUnreadable(
            f"fiche sans ligne « Delivery » — plateforme inconnue, non entrée ({RULE})")
    restricted = restricted_countries(body)
    h1 = _H1_RE.search(body)
    return ProductPage(path=_norm_path(expected_path), title=_clean(h1.group("h1")) if h1 else "",
                       delivery_text=delivery, os_text=spec.get("Platform", ""),
                       features=spec.get("Features", ""), restricted=restricted)


def page_platform(page: ProductPage) -> str:
    """Le jeton de la plateforme PC lu dans « Delivery » ; lève pour un libellé inconnu — jamais
    STEAM par défaut."""

    token = DELIVERY_TEXT.get(page.delivery_text.strip().lower())
    if token is None:
        raise GamebilletPageUnreadable(
            f"livraison de la fiche inconnue : « {page.delivery_text} » — non entrée ({RULE})")
    return token


def page_region(page: ProductPage) -> tuple[str | None, str]:
    """La règle `[R59]` sur les pays EXCLUS ; aucune restriction = GLOBAL."""

    if not page.restricted:
        return region_from_lock(None, label="GAMEBILLET")
    return region_from_lock(("NOT", page.restricted), label="GAMEBILLET")


# ── la requête ────────────────────────────────────────────────────────────────────────
_MAX_BODY = 2_000_000


def page_get(url: str, timeout: int = 20,
             user_agent: str = REQUIRED_USER_AGENT) -> HttpProbeResult:
    """GET d'une fiche gamebillet.com (redirections suivies, hôte final vérifié). Même contrat
    que ``http_get`` : un ``HttpProbeResult``, jamais d'exception."""

    request = urllib.request.Request(url, headers={"User-Agent": user_agent,
                                                   "Accept": "text/html,*/*;q=0.8",
                                                   "Accept-Language": "en-US,en;q=0.8"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            final = response.geturl()
            body = response.read(_MAX_BODY).decode("utf-8", errors="replace")
            status = response.status
    except urllib.error.HTTPError as exc:
        return HttpProbeResult(url=url, ok=False, status=exc.code, body="", error=str(exc))
    except Exception as exc:                  # noqa: BLE001 — tout échec = réponse ratée
        return HttpProbeResult(url=url, ok=False, status=None, body="",
                               error=f"{type(exc).__name__}: {exc}")
    if not _on_domain(final):
        return HttpProbeResult(url=url, ok=False, status=status, body="",
                               error=f"redirigé hors de gamebillet.com : {final}")
    return HttpProbeResult(url=url, ok=status == 200, status=status, body=body)


_CACHE: dict[str, ProductPage | str] = {}


def clear_cache() -> None:
    _CACHE.clear()


def product_url(url: str) -> str | None:
    """L'URL de la fiche à ouvrir (sans query ni fragment), ou None si ce n'en est pas une :
    un seul segment de chemin sous gamebillet.com (« /dunebound-tactics »)."""

    if not _on_domain(url):
        return None
    parts = urlsplit(url)
    path = _norm_path(parts.path)
    if not path or path == "/" or path.count("/") != 1:
        return None
    return f"https://www.{DOMAIN}{path}"


def fetch_product_page(url: str, http_get_fn: Callable[..., Any] = page_get) -> ProductPage:
    """Ouvre la fiche gamebillet.com de l'offre (une fois par processus). Lève si illisible."""

    target = product_url(url)
    if target is None:
        raise GamebilletPageUnreadable(
            f"lien sans fiche produit gamebillet.com (/<slug>) — aucune autre page n'est lue ({RULE})")
    path = _norm_path(urlsplit(target).path)
    cached = _CACHE.get(target)
    if isinstance(cached, ProductPage):
        return cached
    if isinstance(cached, str):
        raise GamebilletPageUnreadable(cached)
    if http_get_fn is page_get:
        time.sleep(PROBE_DELAY_S)
    try:
        try:
            response = http_get_fn(target, timeout=20, user_agent=REQUIRED_USER_AGENT)
        except Exception as exc:             # noqa: BLE001 — tout échec = refus
            raise GamebilletPageUnreadable(f"fiche Gamebillet injoignable : {exc}") from exc
        if not (response.ok and response.status == 200 and response.body):
            raise GamebilletPageUnreadable(
                f"réponse inattendue : {response.status or response.error}"
                + (" — fiche retirée (404)" if response.status == 404 else "") + f" ({RULE})")
        page = parse_product_page(response.body, path)
    except GamebilletPageUnreadable as exc:
        if len(_CACHE) < 4096:
            _CACHE[target] = str(exc)
        raise
    if len(_CACHE) < 4096:
        _CACHE[target] = page
    return page


def offer_signals(url: str, name: str = "",
                  http_get_fn: Callable[..., Any] = page_get) -> MerchantOfferSignals:
    """Le résolveur `[R71]` : la fiche donne la plateforme (ligne « Delivery ») et TOUJOURS la
    région (`[R59]` sur la fenêtre des pays restreints) ; elle ne dit rien du DLC (``dlc=None``,
    voir le module). Une fiche illisible lève → refus R32 (« offer page unreadable »)."""

    page = fetch_product_page(url, http_get_fn)
    platform = page_platform(page)
    base, label = page_region(page)
    if base is None:
        return MerchantOfferSignals(platform=platform, region_resolved=True,
                                    region_base=None, region_label=label)
    return MerchantOfferSignals(platform=platform, region_resolved=True, region_base=base)


CONFIG = make_config(
    "Gamebillet",
    domain=DOMAIN,
    offer_page_resolver=offer_signals,
    # Aucune ligne console au feed du 21/09 ; si la grammaire console partagée en lisait une, la
    # fiche est lue pour elle aussi (`[R68]`) : une livraison « Steam » sur une ligne console est
    # un conflit, refusé — jamais une page console écrite sur une clé Steam.
    console_page_authoritative=True,
    notes=("feed store 15 — URL `gamebillet.com/<slug>` (titre et URL muets). [R71] (2026-10-06, "
           "hors liste blanche, aperçu à blanc le même jour) : plateforme = ligne « Delivery » du "
           "tableau de la fiche (jamais STEAM par défaut ; « Platform » = l'OS, ignoré) ; région = "
           "fenêtre « Restricted countries », règle [R59] de Romain sur les pays exclus — PROPOSÉE, "
           "à confirmer à l'aperçu ; fenêtre vide = GLOBAL, fenêtre absente = refus ; aucun signal DLC "
           "de la fiche (« Downloadable Content » des Features est aussi porté par des jeux de base) ; "
           "404 = fiche retirée = refus ; titre bilingue « A / B » gardé entier."),
)
