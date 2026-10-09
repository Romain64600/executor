"""Allyouplay (feed store 17) — le lien d'affiliation (2026-09-30).

Dans la liste blanche (``src/admin/auto_merchants.py``, groupe B) depuis le 14/09, fichier
d'identité seule jusqu'ici (« aucun hook inventé sans lot observé »). Le lot existe maintenant :
**six balayages du groupe B depuis le 17/09, 296 lignes distinctes, 100 % refusées par le
contrôle de domaine** (« offer URL not on allyouplay.com ») — aucune offre Allyouplay n'a
jamais été saisie. Première lecture complète le 29/09, à l'aperçu par page de Nivalis Nights
et Transport Fever 3.

**Le lien du feed n'est pas sur allyouplay.com.** Toutes les lignes passent par le même
redirecteur Impact :
``https://anandadigitalbv.sjv.io/c/1297091/2866230/30655?prodsku=42863&u=<fiche>&intsrc=CATF_22827``
— hôte, chemin, ``prodsku`` et ``intsrc`` identiques pour les 296 lignes ; la fiche est dans
``u`` (encodée), sur ``www.allyouplay.com``.

Règle de Romain (2026-09-30, « Go ») : « accepter le lien d'affiliation seulement si u pointe
vers allyouplay.com, et u sert d'identité comme Loaded ». D'où, ici :

* ``affiliate_hosts`` — l'hôte du redirecteur. ``MerchantConfig.landing_url`` rend la fiche de
  ``u`` quand elle est sur allyouplay.com ; le contrôle de domaine et toutes les lectures de
  signaux d'URL (région, région interdite, plateforme d'URL) lisent cette fiche. Un lien du
  redirecteur sans ``u``, ou dont ``u`` n'est pas sur allyouplay.com, reste refusé par le
  contrôle de domaine, avec un motif qui le NOMME (« affiliate link without a allyouplay.com
  product page in u »). L'URL stockée n'est jamais réécrite.
* ``url_identity_params=("u",)`` — comme Loaded : le chemin est le même pour toutes les
  offres, l'annonce est dans ``u``. Sans lui, demander la ligne 2 sélectionnait la ligne 1 et
  une sœur restée au feed empêchait de prouver la disparition d'une offre créée.

**Grammaire observée (296 lignes, runs du 17/09 au 26/09) — NON codée, décisions de Romain :**

* Premier segment de la fiche : ``/pc/`` 228, ``/xbox/`` 31, ``/cash-points/`` 25
  (monnaies de jeu, points), ``/subscription/`` 11 (Tinder Gold / Plus), ``/bundle/`` 1.
* Les titres PC ne portent **ni plateforme ni région** (« Nivalis Nights », « Transport Fever
  3 », « Worms Armageddon ») ; quelques « [Mac] ». Les titres Xbox portent la génération en
  queue (« - Xbox One », « - Xbox Series X|S »), parfois un pays (« … - Xbox Series X|S - BE »).
* Codes glissés dans certains slugs : ``-ga-ste-`` (Steam), ``-ga-gog-`` (GOG), ``-row-<uuid>``
  / ``-row-september-2026-…`` (Rest of World), ``-ww-<uuid>`` (monde), ``cnprc``, ``res30``,
  ``t2wwd``, ``glok2``, ``pointnxs``, suffixes ``-2`` … ``-11``. Le ``-row-`` est lu par le scan
  générique des régions interdites (la fiche est maintenant visible) : refus ``forbidden
  region: ROW``, conforme à la règle ROW du 24/09.
* La fiche produit est **lisible en HTTP** (200, pas de Cloudflare, vérifié le 29/09) : le
  payload Nuxt porte l'attribut « Platform: Steam » et ``available_countries``. Un lecteur de
  page (comme Gamesplanet FR ``[R59]``) est une option, pas codée.

**`[R68]` — la fiche fait foi (Romain, 2026-09-30 : « go pour 1 »).** L'option retenue : « lire la
page Allyouplay de chaque offre, comme pour Gamesplanet FR : elle s'ouvre sans blocage et donne la
plateforme (Platform: Steam) et la liste complète des pays où la clé s'active ». Sans elle, un
titre PC nu (« Nivalis Nights ») s'arrêtait sur R27 / ``[R51]`` : aperçu du 30/09, 0 candidat PC
sur 219.

Ordre de lecture (Romain, 2026-09-18 : « un check du titre par défaut avant d'ouvrir la page ») :

1. **Titre** — la génération Xbox (grammaire console partagée, inchangée) ; « [Mac] » → refus
   nommé (``precheck``, 10 lignes) : AKS range les clés Mac sur des pages « for Mac » à part, et
   un titre « Civilization VI [Mac] » tomberait sinon sur la page PC (MAC est un mot de bruit).
2. **URL** (le slug de ``u``) — deux codes OBSERVÉS, et eux seuls : ``-ga-ste-`` → STEAM (16
   lignes), ``-ga-gog-`` → GOG (2 lignes : X-COM Apocalypse / Terror From the Deep). Le ``-row-``
   reste le refus générique ROW. Rien d'autre n'est deviné du slug.
3. **Page** — la fiche ``https://www.allyouplay.com/<rayon>/<slug>`` (301 vers allyouplay.com),
   payload Nuxt ``<script id="__NUXT_DATA__">`` (tableau « devalue ») :
   * plateforme = l'attribut « Platform » du produit (« Steam » ; « Xbox Console » pour les lignes
     Xbox — une console n'est pas une boutique PC, la région seule sert alors) ; une valeur
     inconnue (« Elder Scrolls Online », vu le 30/09) est un refus NOMMÉ ;
   * une clé PC dont l'attribut « Operating System » ne cite pas Windows (« Mac OS » seul :
     « Civilization VI - Persia and Macedon », titre sans « [Mac] ») est refusée ;
   * région = ``available_countries`` (codes ISO-2 du PRODUIT ; ``customer_country`` et
     ``is_available_for_country`` décrivent le VISITEUR, ignorés), lue par la règle de Romain du
     25/09 pour Gamesplanet FR ``[R59]`` (``gamesplanet.region_from_lock``, la même table) sur les
     pays ABSENTS : ni l'UE, ni le Royaume-Uni, ni les USA absents → GLOBAL ; UE complète, USA
     absents → Europe ; USA présents, un pays de l'UE absent → US ; le reste → refus.

La région ne se lit JAMAIS dans le titre ni dans l'URL chez ce marchand : pour une ligne qui
atteint la page (titre et URL ont déjà dit ce qu'ils savaient de la plateforme), la page est
ouverte. Le matcher confronte la plateforme du titre / de l'URL à celle de la page : un désaccord
(« -ga-gog- » et « Platform: Steam » sur X-COM Apocalypse, vu le 30/09) est un refus, jamais un
choix.

Fail-closed : page injoignable, statut ≠ 200, fiche non identifiée (lien canonique absent ou
autre que la fiche demandée), payload absent ou illisible, pas d'attribut « Platform », pas de
``available_countries`` → refus, JAMAIS un repli sur STEAM ou GLOBAL. Aucune page d'un autre
marchand n'est lue : seule une fiche allyouplay.com (celle de ``u``) est ouverte.

Politesse : une requête par fiche et par processus de match (cache), ~1 requête / s — ~250
fiches pour un passage complet du feed.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlsplit

from src.aks_env import REQUIRED_USER_AGENT, HttpProbeResult
from src.merchant_config import MerchantOfferSignals, affiliate_landing
from src.merchants.common import make_config
from src.merchants.gamesplanet import ISO2_TO_NAME, region_from_lock

DOMAIN = "allyouplay.com"
AFFILIATE_HOST = "anandadigitalbv.sjv.io"
PROBE_DELAY_S = 1.0                   # ~1 requête / s sur un balayage complet (~250 fiches)


def landing(url: str) -> str:
    """La fiche allyouplay.com du lien d'affiliation (``u``), ou l'URL telle quelle."""

    return affiliate_landing(url, (AFFILIATE_HOST,), DOMAIN)


def _host(url: str) -> str:
    try:
        return urlsplit(url or "").netloc.lower().split("@")[-1].split(":")[0]
    except ValueError:
        return ""


def _on_domain(url: str) -> bool:
    host = _host(url)
    return host == DOMAIN or host.endswith("." + DOMAIN)


def _landing_path(url: str) -> str | None:
    """Le chemin de la fiche allyouplay.com, ou None (lien sans fiche allyouplay)."""

    target = landing(url)
    return urlsplit(target).path.lower() if _on_domain(target) else None


# ── 1. titre ───────────────────────────────────────────────────────────────────────────
_MAC_RE = re.compile(r"\[\s*mac\s*\]", re.IGNORECASE)


def precheck(name: str, url: str) -> str | None:
    """« [Mac] » : une clé Mac, que la lecture générique rangerait sur la page PC (MAC est un
    mot de bruit des gardes). AKS a des pages « for Mac » à part ; on refuse (10 lignes sur 296
    le 30/09)."""

    if _MAC_RE.search(name or ""):
        return ("Allyouplay : clé Mac (« [Mac] » dans le titre) — AKS range les clés Mac sur des "
                "pages « for Mac » à part, non entré (R68)")
    return None


# ── 2. URL : les codes observés dans le slug de la fiche ─────────────────────────────
URL_STORE_CODES: tuple[tuple[str, str], ...] = (("-ga-ste-", "STEAM"), ("-ga-gog-", "GOG"))


def url_platform(url: str) -> str | None:
    """STEAM / GOG d'après un code du slug de la fiche (``…-azic-ga-ste-…``, ``…-take-ga-gog-…``),
    ou None. Deux codes différents dans un même slug : None — la page tranchera."""

    path = _landing_path(url)
    if not path:
        return None
    found = {token for code, token in URL_STORE_CODES if code in path + "-"}
    return found.pop() if len(found) == 1 else None


# ── 3. la fiche ───────────────────────────────────────────────────────────────────────
# Libellés « Platform » → nos jetons (`REGION_IDS`). Seul « Steam » est observé sur les fiches
# PC (30/09) ; les autres sont les noms usuels des boutiques, rendus au jeton du matcher. Un
# libellé absent de ces deux tables est REFUSÉ par son nom.
PLATFORM_TEXT: dict[str, str] = {
    "STEAM": "STEAM",
    "GOG": "GOG", "GOG.COM": "GOG", "GOG GALAXY": "GOG",
    "EPIC": "EPIC", "EPIC GAMES": "EPIC", "EPIC GAMES STORE": "EPIC",
    "UBISOFT CONNECT": "UBISOFT", "UPLAY": "UBISOFT",
    "EA APP": "EA", "ORIGIN": "EA",
    "MICROSOFT STORE": "MICROSOFT",
    "ROCKSTAR GAMES LAUNCHER": "ROCKSTAR", "ROCKSTAR": "ROCKSTAR",
    "BATTLE.NET": "BATTLENET",
}
# Les fiches Xbox disent « Xbox Console » : pas une boutique PC. La branche console ne lit que
# la région de la fiche ; la branche PC refuse (plateforme non reconnue).
CONSOLE_PLATFORM_TEXT: frozenset[str] = frozenset({"XBOX CONSOLE"})

# Les pays qui décident, en ISO-2 → les noms de la table de Romain : `gamesplanet.ISO2_TO_NAME`,
# partagée avec Greenmangaming `[R73]` depuis le 2026-10-09 (une table, pas une copie).

_NUXT_RE = re.compile(r'<script[^>]*\bid="__NUXT_DATA__"[^>]*>(?P<json>.*?)</script>', re.S)
_CANONICAL_RE = re.compile(r'<link[^>]*\brel="canonical"[^>]*\bhref="(?P<href>[^"]+)"', re.I)
_WRAPPERS = frozenset({"ShallowReactive", "Reactive", "Ref", "ShallowRef"})
_ISO2_RE = re.compile(r"^[A-Z]{2}$")


class AllyouplayPageUnreadable(RuntimeError):
    """Fiche injoignable, non identifiée, ou sans ce qu'il faut pour décider : on refuse, on ne
    devine ni plateforme ni région (`[R68]`)."""


@dataclass(frozen=True)
class ProductPage:
    """Ce qu'une fiche dit : le libellé « Platform », les systèmes, les pays autorisés."""

    platform_text: str
    operating_systems: tuple[str, ...]
    available_countries: frozenset[str]


def _value(data: list, ref: Any, depth: int = 0) -> Any:
    """Déréférence un indice du tableau « devalue » de Nuxt (les valeurs d'un objet et les
    éléments d'une liste sont des indices ; un négatif est undefined / null)."""

    if depth > 12:
        raise AllyouplayPageUnreadable("payload Nuxt trop imbriqué")
    if not isinstance(ref, int) or isinstance(ref, bool):
        return ref
    if ref < 0 or ref >= len(data):
        return None
    v = data[ref]
    if isinstance(v, dict):
        return {k: _value(data, x, depth + 1) for k, x in v.items()}
    if isinstance(v, list):
        if v and isinstance(v[0], str):
            return _value(data, v[1], depth + 1) if v[0] in _WRAPPERS and len(v) > 1 else None
        return [_value(data, x, depth + 1) for x in v]
    return v


def parse_product_page(body: str, expected_path: str) -> ProductPage:
    """Lit la fiche. Lève si elle n'est pas CELLE demandée (lien canonique) ou si l'un des
    trois repères manque — jamais un défaut."""

    canon = _CANONICAL_RE.search(body or "")
    if canon is None:
        raise AllyouplayPageUnreadable("fiche sans lien canonique — produit non identifié")
    if urlsplit(canon.group("href")).path.rstrip("/").lower() != expected_path.rstrip("/"):
        raise AllyouplayPageUnreadable(
            f"la page servie n'est pas la fiche demandée ({canon.group('href')!r})")
    m = _NUXT_RE.search(body)
    if m is None:
        raise AllyouplayPageUnreadable("pas de payload Nuxt (__NUXT_DATA__) — gabarit changé ?")
    try:
        data = json.loads(m.group("json"))
    except ValueError as exc:
        raise AllyouplayPageUnreadable(f"payload Nuxt illisible : {exc}") from exc
    if not isinstance(data, list):
        raise AllyouplayPageUnreadable("payload Nuxt inattendu (pas un tableau)")
    products = [i for i, v in enumerate(data)
                if isinstance(v, dict) and "available_countries" in v
                and "product_specification_model" in v]
    if len(products) != 1:
        raise AllyouplayPageUnreadable(f"{len(products)} produit(s) dans le payload — un attendu")
    raw = data[products[0]]
    countries = _value(data, raw["available_countries"])
    if not isinstance(countries, list) or not countries or not all(
            isinstance(c, str) and _ISO2_RE.match(c) for c in countries):
        raise AllyouplayPageUnreadable("available_countries absent, vide ou illisible")
    spec = _value(data, raw["product_specification_model"]) or {}
    attributes: dict[str, list[str]] = {}
    for group in (spec.get("groups") or []) if isinstance(spec, dict) else []:
        for attr in (group or {}).get("attributes") or []:
            name = str((attr or {}).get("name") or "").strip().upper()
            vals = [str((x or {}).get("value_raw") or "").strip()
                    for x in (attr or {}).get("values") or []]
            attributes.setdefault(name, []).extend(v for v in vals if v)
    platforms = sorted({v.upper() for v in attributes.get("PLATFORM", [])})
    if not platforms:
        raise AllyouplayPageUnreadable("pas d'attribut « Platform » sur la fiche")
    if len(platforms) > 1:
        raise AllyouplayPageUnreadable(f"plusieurs plateformes sur la fiche : {platforms}")
    return ProductPage(platform_text=platforms[0],
                       operating_systems=tuple(attributes.get("OPERATING SYSTEM", [])),
                       available_countries=frozenset(countries))


def page_platform(page: ProductPage) -> str | None:
    """Le jeton de la plateforme PC, None pour une fiche console ; lève pour un libellé inconnu
    ou une clé PC sans Windows."""

    if page.platform_text in CONSOLE_PLATFORM_TEXT:
        return None
    token = PLATFORM_TEXT.get(page.platform_text)
    if token is None:
        raise AllyouplayPageUnreadable(
            f"plateforme « {page.platform_text} » inconnue — non entré (R68)")
    if page.operating_systems and not any("WINDOWS" in os_.upper()
                                          for os_ in page.operating_systems):
        raise AllyouplayPageUnreadable(
            f"clé {page.platform_text} pour {' / '.join(page.operating_systems)} seulement, "
            "pas Windows — pas une clé PC, non entré (R68)")
    return token


def page_region(page: ProductPage) -> tuple[str | None, str]:
    """La règle de Romain ``[R59]`` sur la liste des pays AUTORISÉS (les exclus sont les absents)."""

    names = frozenset(ISO2_TO_NAME[c] for c in page.available_countries if c in ISO2_TO_NAME)
    return region_from_lock(("ONLY", names), label="ALLYOUPLAY")


# ── la requête ────────────────────────────────────────────────────────────────────────
# PAS `aks_env.http_get` (répétition du 30/09 sur le VPS de secours : 241 fiches sur 241 en
# 403 « Attention Required! | Cloudflare »). Son moteur keep-alive (`requests`) reçoit l'en-tête
# tel qu'urllib le range — `User-agent` — et le Cloudflare d'Allyouplay refuse cette forme-là
# venant de `requests` : mesuré le même jour depuis le VPS de secours ET cette machine, même
# seconde, même fiche — `requests` + « User-agent » → 403, `requests` + « User-Agent » → 200,
# urllib → 200. On ne touche pas au moteur partagé (chaque requête vers AKS passe par lui, et le
# pare-feu d'AKS a déjà banni une IP pour un en-tête le 11/09) : cette fiche est lue par la
# bibliothèque standard, sans nouvelle dépendance, et le contrat reste celui de `http_get`
# (un `HttpProbeResult`, jamais d'exception).
_MAX_BODY = 2_000_000


def page_get(url: str, timeout: int = 20,
             user_agent: str = REQUIRED_USER_AGENT) -> HttpProbeResult:
    """GET d'une fiche allyouplay.com (redirections suivies, hôte final vérifié)."""

    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
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
                               error=f"redirigé hors d'allyouplay.com : {final}")
    return HttpProbeResult(url=url, ok=status == 200, status=status, body=body)


_CACHE: dict[str, ProductPage | str] = {}


def clear_cache() -> None:
    _CACHE.clear()


def fetch_product_page(url: str, http_get_fn: Callable[..., Any] = page_get) -> ProductPage:
    """Ouvre la fiche allyouplay.com de ``u`` (une fois par processus). Lève si illisible."""

    target = landing(url)
    if not _on_domain(target):
        raise AllyouplayPageUnreadable(
            "lien sans fiche allyouplay.com — aucune autre page n'est lue (R68)")
    path = urlsplit(target).path.lower()
    cached = _CACHE.get(target)
    if isinstance(cached, ProductPage):
        return cached
    if isinstance(cached, str):
        raise AllyouplayPageUnreadable(cached)
    if http_get_fn is page_get:
        time.sleep(PROBE_DELAY_S)
    try:
        try:
            response = http_get_fn(target, timeout=20, user_agent=REQUIRED_USER_AGENT)
        except Exception as exc:             # noqa: BLE001 — tout échec = refus
            raise AllyouplayPageUnreadable(f"fiche Allyouplay injoignable : {exc}") from exc
        if not (response.ok and response.status == 200 and response.body):
            raise AllyouplayPageUnreadable(
                f"réponse inattendue : {response.status or response.error}")
        page = parse_product_page(response.body, path)
    except AllyouplayPageUnreadable as exc:
        if len(_CACHE) < 4096:
            _CACHE[target] = str(exc)
        raise
    if len(_CACHE) < 4096:
        _CACHE[target] = page
    return page


def offer_signals(url: str, name: str = "",
                  http_get_fn: Callable[..., Any] = page_get) -> MerchantOfferSignals:
    """Le résolveur ``[R68]`` : la fiche donne la plateforme (confrontée par le matcher à celle
    du titre / de l'URL) et TOUJOURS la région — le titre et l'URL n'en disent rien chez ce
    marchand. Une fiche illisible lève → le matcher refuse (R32)."""

    page = fetch_product_page(url, http_get_fn)
    platform = page_platform(page)
    base, label = page_region(page)
    if base is None:
        return MerchantOfferSignals(platform=platform, region_resolved=True,
                                    region_base=None, region_label=label)
    return MerchantOfferSignals(platform=platform, region_resolved=True, region_base=base)


CONFIG = make_config(
    "Allyouplay",
    domain=DOMAIN,
    affiliate_hosts=(AFFILIATE_HOST,),
    # Le chemin du redirecteur (`/c/1297091/2866230/30655`) est le même pour les 296 lignes :
    # l'annonce est dans `u`, comme chez Loaded (2026-09-26).
    url_identity_params=("u",),
    precheck=precheck,
    url_platform=url_platform,
    offer_page_resolver=offer_signals,
    # Revue adverse du 30/09 : sans ce drapeau, un titre Xbox « … - UK » prenait sa région du
    # titre sans ouvrir la fiche, et une fiche « Platform: Steam » sur une ligne Xbox passait.
    console_page_authoritative=True,
    notes=("feed store 17 — liens d'affiliation `anandadigitalbv.sjv.io/…?u=<fiche "
           "allyouplay.com>` : la fiche de `u` fait foi pour le domaine et les signaux d'URL, "
           "`u` est l'identité. [R68] plateforme = titre, puis codes du slug (-ga-ste- / "
           "-ga-gog-), puis l'attribut « Platform » de la fiche ; région = available_countries "
           "de la fiche, règle [R59] de Romain ; « [Mac] » refusé (2026-09-30, en ligne le "
           "30/09)."),
)
