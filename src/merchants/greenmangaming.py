"""Greenmangaming (feed store 22) — `[R73]` la fiche fait foi (2026-10-09).

Romain, 2026-10-09 : « Formons-nous sur un nouveau marchand. Choisis un marchand selon nos critères,
soit assez facile à rentrer et qui ait des pending offers disponibles », puis, sur l'étude
(`docs/PROCHAINS_MARCHANDS.md`, section 2026-10-09) : « go pour Greenmangaming avec ta règle R59,
1. L'executor continue de rentrer l'offre en ROW mais il vérifie que ce soit bien dispo en EU + US
avant de l'ajouter, sinon il skip 2. consoles oui mais ça peut être xbox + PC sur certaines offres,
3. Standard oui 4. OK, go ».

**Le feed.** 482 lignes au scan du 21/09, le plus gros stock hors liste blanche (318 avec une page
AKS d'après le nom). Le titre est NU (« Reus 2 - Jurassic », « Cozy Builder » ; 42 portent ™ / ®).
Toutes les URL passent par le redirecteur Impact, comme Allyouplay `[R68]` :
``https://greenmangaming.sjv.io/c/1297091/1272000/15105?prodsku=<sku>&u=<fiche>`` — ``u`` est la
fiche ``www.greenmangaming.com/games/<slug>/``, ``prodsku`` est le code produit de GMG, qui finit
par la PLATEFORME : « - PC » 444, « - Xbox Series XS » 24, « - Xbox One » 8, « - PlayStation 4 » 5
(des crédits PSN), « - Windows 10 » 1. Ni la boutique ni la région ne sont dans le titre ou l'URL.

**La fiche** se lit en HTTP (200, 16 / 16 le 09/10, bibliothèque standard, UA navigateur) et embarque
un JSON produit : ``<script> var games = {…, "platforms": [{"ClassName": "steam", "Editions": [{…}]}]}``.
Chaque édition porte ``Code`` (= le ``prodsku`` du feed : l'identité ligne ↔ fiche se VÉRIFIE, une
fiche sert plusieurs éditions — NHL 27 Standard et Deluxe sur ``/games/nhl-27-xbox/``), ``GameName``,
``Name`` (l'édition : « Standard Edition », « Deluxe Edition », « Bundle », « 2 Pack Edition », ou
vide), ``Drm`` (``["steam"]``, ``["xbox-one"]`` pour TOUTE génération Xbox, ``["microsoft"]`` pour une
clé Microsoft Store « Windows 10 »), ``ExcludedCountries`` (codes ISO-2 des pays où la clé ne
s'active PAS — vide : « This product has no regional restrictions »), ``SystemRequirements[]
.PlatformName`` (« PC », « Xbox One », « Xbox Series X/S »).

**Ordre de lecture** (Romain, 2026-09-18 : le titre, puis l'URL, puis la page) :

1. **Titre / sku** — « (MAC) » → refus nommé (AKS a des pages « for Mac » à part) ; un sku
   PlayStation → refus nommé (GMG n'y vend que du crédit PSN) ; une monnaie / un abonnement
   (Bucks, Points, Coins, CREDIT, Game Pass…) → refus nommé.
2. **URL** — la génération console du sku (« Xbox Series XS » → XBOX_SERIES, « Xbox One » →
   XBOX_ONE), déclarée au classifieur console par ``console_url_families`` ; « - PC » et
   « - Windows 10 » ne disent pas la boutique : rien n'est deviné.
3. **Fiche** — l'édition dont ``Code`` == ``prodsku`` (exactement une, sinon refus) :
   * plateforme = ``Drm`` (vocabulaire FERMÉ : ``steam`` → STEAM, ``microsoft`` → MICROSOFT —
     observés ; ``epic`` / ``uplay`` / ``origin`` / ``gog`` / ``rockstar`` / ``battlenet`` → leurs
     jetons, NON observés au 09/10 ; ``xbox-one`` → console, pas une boutique PC ; tout autre
     libellé, ou deux DRM → refus nommé) ;
   * région = **`[R59]` sur les pays EXCLUS, bornée par la décision du 09/10** : liste vide →
     GLOBAL ; liste non vide mais NI l'UE, NI le Royaume-Uni, NI les USA exclus → la clé est
     « ROW » : base ``row`` (seau « Steam ROW (steamrow) » du menu, lu le 26/09 — « L'executor
     continue de rentrer l'offre en ROW mais il vérifie que ce soit bien dispo en EU + US ») ;
     un pays de l'UE, le Royaume-Uni ou les USA exclus → refus (« sinon il skip » — JAMAIS le
     repli US / EU de `[R59]` chez ce marchand) ;
   * édition = ``Name`` confronté au titre : un palier nommé par la fiche (Deluxe, Ultimate…) que
     le titre ne porte pas → refus ; « 2 Pack » / « Bundle » → refus (plusieurs clés, pas une) ;
     « Standard Edition » ou vide → le chemin générique (Romain : « Standard oui ») ;
   * consoles (Romain : « consoles oui mais ça peut être Xbox + PC sur certaines offres ») :
     ``Drm`` ``xbox-one`` → plateforme None (la génération vient du sku, P1) ; la fiche qui liste
     PC ET une Xbox dans ``SystemRequirements`` déclare « Xbox + PC » (``console_pc_declared`` →
     P2) ; la région de la fiche fait foi (``console_page_authoritative``).

Fail-closed : lien sans ``u`` sur greenmangaming.com ou sans ``prodsku``, fiche injoignable, statut
≠ 200, lien canonique autre que la fiche demandée, JSON absent / illisible, sku absent de la fiche
ou présent plusieurs fois sous des formes différentes, DRM inconnu → refus nommé, JAMAIS un repli
sur STEAM ou GLOBAL. Seule une fiche greenmangaming.com (celle de ``u``) est ouverte, une fois par
processus (cache), ~1 requête / s.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from src.aks_env import REQUIRED_USER_AGENT, HttpProbeResult
from src.merchant_config import MerchantOfferSignals, affiliate_landing
from src.merchants.common import make_config
from src.merchants.gamesplanet import EU_MEMBERS, ISO2_TO_NAME, UK, US

DOMAIN = "greenmangaming.com"
AFFILIATE_HOST = "greenmangaming.sjv.io"
PROBE_DELAY_S = 1.0                   # ~1 requête / s — ~480 fiches pour un passage complet
RULE = "R73"


def landing(url: str) -> str:
    """La fiche greenmangaming.com du lien d'affiliation (``u``), ou l'URL telle quelle."""

    return affiliate_landing(url, (AFFILIATE_HOST,), DOMAIN)


def _host(url: str) -> str:
    try:
        return urlsplit(url or "").netloc.lower().split("@")[-1].split(":")[0]
    except ValueError:
        return ""


def _on_domain(url: str) -> bool:
    host = _host(url)
    return host == DOMAIN or host.endswith("." + DOMAIN)


def prodsku(url: str) -> str | None:
    """Le code produit GMG du lien d'affiliation (``prodsku``), ou None."""

    try:
        values = parse_qs(urlsplit(url or "").query).get("prodsku") or []
    except ValueError:
        return None
    sku = values[0].strip() if values else ""
    return sku or None


# ── 1. titre / sku ────────────────────────────────────────────────────────────────────
_MAC_RE = re.compile(r"\(\s*MAC\s*\)|\bfor Mac\b", re.IGNORECASE)
_PREPAID_RE = re.compile(
    r"\b(?:CREDIT|Gift Card|Wallet|Points?|Coins?|Bucks|Membership|Game Pass|Subscription|"
    r"Month(?:s)? Card|Prepaid|Top[- ]?Up)\b", re.IGNORECASE)
# Le suffixe du sku (« <nom> - <plateforme> ») → la famille console déclarée, None pour une
# plateforme PC. Un suffixe inconnu n'est PAS deviné.
_SKU_PLATFORM_RE = re.compile(r"\s-\s(?P<platform>[A-Za-z0-9 /|]+)\s*$")
SKU_CONSOLE_FAMILIES: dict[str, tuple[str, ...]] = {
    "XBOX SERIES XS": ("XBOX_SERIES",), "XBOX SERIES X|S": ("XBOX_SERIES",),
    "XBOX SERIES X/S": ("XBOX_SERIES",), "XBOX ONE": ("XBOX_ONE",),
    "PLAYSTATION 4": ("PS4",), "PLAYSTATION 5": ("PS5",), "NINTENDO SWITCH": ("SWITCH",),
}
SKU_PC_PLATFORMS: frozenset[str] = frozenset({"PC", "WINDOWS 10", "WINDOWS 11", "WINDOWS"})


def sku_platform(url: str) -> str | None:
    """Le suffixe de plateforme du sku, en capitales (« PC », « XBOX SERIES XS »), ou None."""

    sku = prodsku(url)
    m = _SKU_PLATFORM_RE.search(sku or "")
    return m.group("platform").strip().upper() if m else None


def precheck(name: str, url: str) -> str | None:
    if _MAC_RE.search(name or ""):
        return (f"Greenmangaming : clé Mac (« (MAC) » dans le titre) — AKS range les clés Mac sur "
                f"des pages « for Mac » à part, non entré ({RULE})")
    if _PREPAID_RE.search(name or ""):
        return (f"Greenmangaming : monnaie / crédit / abonnement (« {name.strip()} »), pas une clé "
                f"de jeu — non entré ({RULE})")
    platform = sku_platform(url)
    if platform and platform.startswith("PLAYSTATION"):
        return (f"Greenmangaming : sku PlayStation (« {platform.title()} ») — GMG n'y vend que du "
                f"crédit PSN, non entré ({RULE})")
    if not _on_domain(landing(url)):
        return (f"Greenmangaming : lien d'affiliation sans fiche greenmangaming.com dans u — "
                f"non entré ({RULE})")
    if prodsku(url) is None:
        return (f"Greenmangaming : lien d'affiliation sans prodsku — l'édition de la fiche ne "
                f"peut pas être identifiée, non entré ({RULE})")
    return None


# ── 2. URL : la génération console du sku ─────────────────────────────────────────────
def console_url_families(url: str) -> tuple[str, ...] | str | None:
    """La famille console déclarée par le suffixe du sku, None pour une plateforme PC ou un
    suffixe absent. Un suffixe inconnu est un refus nommé (jamais une famille devinée)."""

    platform = sku_platform(url)
    if platform is None or platform in SKU_PC_PLATFORMS:
        return None
    families = SKU_CONSOLE_FAMILIES.get(platform)
    if families is None:
        return f"console: Greenmangaming sku platform {platform!r} not recognised — not entered ({RULE})"
    return families


# ── 3. la fiche ───────────────────────────────────────────────────────────────────────
# ``Drm`` → notre jeton de boutique PC. OBSERVÉS le 09/10 : steam, microsoft ; xbox-one (console).
# Les autres sont les noms de classe usuels des boutiques, NON observés — un libellé absent de ces
# deux tables est REFUSÉ par son nom.
DRM_PLATFORM: dict[str, str] = {
    "steam": "STEAM",
    "microsoft": "MICROSOFT",
    "epic": "EPIC", "epic-games": "EPIC", "epicgames": "EPIC",
    "uplay": "UBISOFT", "ubisoft": "UBISOFT", "ubisoft-connect": "UBISOFT",
    "origin": "EA", "ea": "EA", "ea-app": "EA",
    "gog": "GOG",
    "rockstar": "ROCKSTAR",
    "battlenet": "BATTLENET", "battle-net": "BATTLENET",
}
# Un DRM console : pas une boutique PC — la génération vient du sku (P1), la fiche ne donne que la
# région (et la déclaration « Xbox + PC », P2).
CONSOLE_DRM: frozenset[str] = frozenset({"xbox-one", "xbox", "xbox-series"})
# ``Name`` : un palier que la fiche nomme et que le titre ne porte pas est un refus ; un lot de
# plusieurs clés aussi.
_TIER_WORDS = ("DELUXE", "ULTIMATE", "GOLD", "PREMIUM", "COMPLETE", "DEFINITIVE", "COLLECTOR",
               "LEGENDARY", "SUPPORTER", "ENHANCED", "SPECIAL", "ANNIVERSARY", "FOUNDER",
               "CHAMPION", "ELITE", "PLATINUM", "SILVER", "SEASON PASS", "EXPANSION")
_MULTI_KEY_RE = re.compile(r"\b(?:\d+|TWO|THREE|FOUR)[- ]PACK\b|\bBUNDLE\b", re.IGNORECASE)
_SCRIPT_GAMES_RE = re.compile(r"var\s+games\s*=\s*")
_CANONICAL_RE = re.compile(r'<link[^>]*\brel="canonical"[^>]*>', re.I)
_HREF_RE = re.compile(r'\bhref="(?P<href>[^"]+)"', re.I)
_ISO2_RE = re.compile(r"^[A-Z]{2}$")


class GreenmangamingPageUnreadable(RuntimeError):
    """Fiche injoignable, non identifiée, ou sans l'édition demandée : on refuse, on ne devine
    ni plateforme ni région (`[R73]`)."""


@dataclass(frozen=True)
class Variant:
    """L'édition de la fiche dont ``Code`` est le ``prodsku`` du feed."""

    code: str
    game_name: str
    edition_name: str
    drm: tuple[str, ...]
    drm_formats: tuple[str, ...]
    excluded_countries: frozenset[str]
    platform_names: tuple[str, ...]
    is_sellable: bool | None
    is_early_access: bool | None


def _json_end(body: str, start: int) -> int:
    """Fin (exclue) de l'objet JSON ouvert en ``body[start]``, chaînes et échappements respectés."""

    depth = 0
    in_str = esc = False
    i = start
    while i < len(body):
        c = body[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c in "{[":
            depth += 1
        elif c in "}]":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise GreenmangamingPageUnreadable("JSON produit non fermé")


def _canonical_path(body: str) -> str | None:
    for tag in _CANONICAL_RE.finditer(body or ""):
        m = _HREF_RE.search(tag.group(0))
        if m:
            return urlsplit(m.group("href")).path.rstrip("/").lower()
    return None


def parse_product_page(body: str, expected_path: str, sku: str) -> Variant:
    """Lit la fiche et rend l'édition ``sku``. Lève si la page n'est pas CELLE demandée (lien
    canonique), si le JSON manque, ou si ``sku`` n'y est pas exactement une fois."""

    canon = _canonical_path(body)
    if canon is None:
        raise GreenmangamingPageUnreadable("fiche sans lien canonique — produit non identifié")
    if canon != expected_path.rstrip("/").lower():
        raise GreenmangamingPageUnreadable(
            f"la page servie n'est pas la fiche demandée ({canon!r})")
    m = _SCRIPT_GAMES_RE.search(body)
    if m is None:
        raise GreenmangamingPageUnreadable("pas de JSON produit (« var games = ») — gabarit changé ?")
    start = body.find("{", m.end())
    if start < 0 or body[m.end():start].strip():
        raise GreenmangamingPageUnreadable("JSON produit inattendu après « var games = »")
    try:
        games = json.loads(body[start:_json_end(body, start)])
    except ValueError as exc:
        raise GreenmangamingPageUnreadable(f"JSON produit illisible : {exc}") from exc
    platforms = games.get("platforms") if isinstance(games, dict) else None
    if not isinstance(platforms, list):
        raise GreenmangamingPageUnreadable("JSON produit sans « platforms »")
    seen: dict[str, dict[str, Any]] = {}
    for platform in platforms:
        for edition in (platform or {}).get("Editions") or []:
            if not isinstance(edition, dict) or str(edition.get("Code") or "").strip() != sku:
                continue
            key = json.dumps(edition, sort_keys=True)
            seen.setdefault(key, edition)
    if not seen:
        raise GreenmangamingPageUnreadable(
            f"le sku {sku!r} n'est pas une édition de la fiche — ligne et fiche ne se correspondent pas")
    if len(seen) > 1:
        raise GreenmangamingPageUnreadable(
            f"le sku {sku!r} apparaît {len(seen)} fois sous des formes différentes sur la fiche")
    raw = next(iter(seen.values()))
    drm = tuple(str(x).strip().lower() for x in (raw.get("Drm") or []) if str(x).strip())
    if not drm:
        raise GreenmangamingPageUnreadable("édition sans « Drm » sur la fiche")
    excluded = raw.get("ExcludedCountries")
    if not isinstance(excluded, list) or not all(
            isinstance(c, str) and _ISO2_RE.match(c.strip().upper()) for c in excluded):
        raise GreenmangamingPageUnreadable("« ExcludedCountries » absent ou illisible sur la fiche")
    platform_names = tuple(str((x or {}).get("PlatformName") or "").strip()
                           for x in (raw.get("SystemRequirements") or []) if isinstance(x, dict))
    return Variant(
        code=sku,
        game_name=str(raw.get("GameName") or "").strip(),
        edition_name=str(raw.get("Name") or "").strip(),
        drm=drm,
        drm_formats=tuple(str(x).strip() for x in (raw.get("DrmFormats") or [])),
        excluded_countries=frozenset(c.strip().upper() for c in excluded),
        platform_names=tuple(p for p in platform_names if p),
        is_sellable=raw.get("IsSellable") if isinstance(raw.get("IsSellable"), bool) else None,
        is_early_access=(raw.get("IsEarlyAccess") if isinstance(raw.get("IsEarlyAccess"), bool)
                         else None),
    )


def variant_platform(variant: Variant) -> str | None:
    """Le jeton de la boutique PC, None pour un DRM console ; lève pour un DRM inconnu ou double."""

    if len(variant.drm) != 1:
        raise GreenmangamingPageUnreadable(
            f"plusieurs DRM sur la fiche ({', '.join(variant.drm)}) — non entré ({RULE})")
    drm = variant.drm[0]
    if drm in CONSOLE_DRM:
        return None
    token = DRM_PLATFORM.get(drm)
    if token is None:
        raise GreenmangamingPageUnreadable(f"DRM « {drm} » inconnu — non entré ({RULE})")
    return token


def variant_region(variant: Variant) -> tuple[str | None, str]:
    """`[R59]` sur les pays EXCLUS, bornée par la décision de Romain du 2026-10-09.

    Rend ``(base, libellé)`` : ``("global", "")`` sans exclusion ; ``("row", "")`` quand des pays
    sont exclus mais ni l'UE, ni le Royaume-Uni, ni les USA (« rentrer l'offre en ROW … vérifier
    que ce soit bien dispo en EU + US ») ; ``(None, libellé)`` dès qu'un pays de l'UE, le
    Royaume-Uni ou les USA sont exclus (« sinon il skip » — jamais le repli US / EU de `[R59]`)."""

    if not variant.excluded_countries:
        return "global", ""
    names = frozenset(ISO2_TO_NAME[c] for c in variant.excluded_countries if c in ISO2_TO_NAME)
    eu_exclu = sorted(EU_MEMBERS & names)
    uk_exclu, us_exclu = UK in names, US in names
    if not eu_exclu and not uk_exclu and not us_exclu:
        return "row", ""
    parts = []
    if eu_exclu:
        parts.append("EU: " + ", ".join(eu_exclu[:3]) + ("…" if len(eu_exclu) > 3 else ""))
    if uk_exclu:
        parts.append("UK")
    if us_exclu:
        parts.append("US")
    return None, f"GREENMANGAMING LOCK ({' + '.join(parts)} excluded)"


def edition_refusal(variant: Variant, name: str) -> str | None:
    """Un lot de plusieurs clés, ou un palier nommé par la fiche que le titre ne porte pas."""

    label = variant.edition_name
    if _MULTI_KEY_RE.search(label) or _MULTI_KEY_RE.search(variant.game_name):
        return (f"Greenmangaming : « {label or variant.game_name} » est un lot de plusieurs "
                f"clés, pas une clé — non entré ({RULE})")
    title = (name or "").upper()
    tiers = [w for w in _TIER_WORDS if re.search(rf"\b{re.escape(w)}\b", label.upper())]
    missing = [w for w in tiers if w not in title]
    if missing:
        return (f"Greenmangaming : la fiche vend l'édition « {label} » mais le titre ne la nomme "
                f"pas — non entré ({RULE})")
    return None


# ── la requête (bibliothèque standard, comme Allyouplay : jamais `aks_env.http_get`) ───
_MAX_BODY = 3_000_000


def page_get(url: str, timeout: int = 20,
             user_agent: str = REQUIRED_USER_AGENT) -> HttpProbeResult:
    """GET d'une fiche greenmangaming.com (redirections suivies, hôte final vérifié)."""

    request = urllib.request.Request(
        url, headers={"User-Agent": user_agent, "Accept-Language": "en-GB,en;q=0.9"})
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
                               error=f"redirigé hors de greenmangaming.com : {final}")
    return HttpProbeResult(url=url, ok=status == 200, status=status, body=body)


_REAL_PAGE_GET = page_get                 # la requête réelle, pour la pause de politesse seule
_CACHE: dict[tuple[str, str], Variant | str] = {}
_BODIES: dict[str, str] = {}


def clear_cache() -> None:
    _CACHE.clear()
    _BODIES.clear()


def fetch_variant(url: str, http_get_fn: Callable[..., Any] | None = None) -> Variant:
    """Ouvre la fiche de ``u`` (une fois par processus) et rend l'édition ``prodsku``. Lève si
    illisible. ``http_get_fn`` est résolu à l'appel (``page_get`` du module) : un test qui
    remplace ``page_get`` est honoré, et la pause de politesse ne vaut que pour la vraie requête."""

    http_get_fn = http_get_fn or page_get
    target = landing(url)
    if not _on_domain(target):
        raise GreenmangamingPageUnreadable(
            f"lien sans fiche greenmangaming.com — aucune autre page n'est lue ({RULE})")
    sku = prodsku(url)
    if sku is None:
        raise GreenmangamingPageUnreadable(
            f"lien sans prodsku — l'édition de la fiche ne peut pas être identifiée ({RULE})")
    path = urlsplit(target).path.lower()
    key = (target, sku)
    cached = _CACHE.get(key)
    if isinstance(cached, Variant):
        return cached
    if isinstance(cached, str):
        raise GreenmangamingPageUnreadable(cached)
    try:
        body = _BODIES.get(target)
        if body is None:
            if http_get_fn is _REAL_PAGE_GET:
                time.sleep(PROBE_DELAY_S)
            try:
                response = http_get_fn(target, timeout=20, user_agent=REQUIRED_USER_AGENT)
            except Exception as exc:             # noqa: BLE001 — tout échec = refus
                raise GreenmangamingPageUnreadable(
                    f"fiche Greenmangaming injoignable : {exc}") from exc
            if not (response.ok and response.status == 200 and response.body):
                raise GreenmangamingPageUnreadable(
                    f"réponse inattendue : {response.status or response.error}")
            body = response.body
            if len(_BODIES) < 1024:
                _BODIES[target] = body
        variant = parse_product_page(body, path, sku)
    except GreenmangamingPageUnreadable as exc:
        if len(_CACHE) < 4096:
            _CACHE[key] = str(exc)
        raise
    if len(_CACHE) < 4096:
        _CACHE[key] = variant
    return variant


def console_pc_declared(name: str, url: str,
                        http_get_fn: Callable[..., Any] | None = None) -> bool:
    """« Xbox + PC » DÉCLARÉ par la fiche (Romain, 2026-10-09 : « consoles oui mais ça peut être
    xbox + PC sur certaines offres ») : l'édition liste PC ET une Xbox dans ses systèmes. Une
    fiche illisible ne déclare rien (le résolveur refusera la ligne de toute façon)."""

    if sku_platform(url) in SKU_PC_PLATFORMS or sku_platform(url) is None:
        return False
    try:
        variant = fetch_variant(url, http_get_fn)
    except GreenmangamingPageUnreadable:
        return False
    names = {p.upper() for p in variant.platform_names}
    return any(n == "PC" or n.startswith("WINDOWS") for n in names) and any(
        "XBOX" in n for n in names)


def offer_signals(url: str, name: str = "",
                  http_get_fn: Callable[..., Any] | None = None) -> MerchantOfferSignals:
    """Le résolveur `[R73]` : la fiche donne la plateforme (confrontée par le matcher à celle du
    titre / de l'URL) et TOUJOURS la région — titre et URL n'en disent rien chez ce marchand.
    Une fiche illisible, un DRM inconnu, un lot ou une édition que le titre ne nomme pas lèvent →
    le matcher refuse (R32)."""

    variant = fetch_variant(url, http_get_fn)
    platform = variant_platform(variant)
    refusal = edition_refusal(variant, name)
    if refusal:
        raise GreenmangamingPageUnreadable(refusal)
    base, label = variant_region(variant)
    if base is None:
        return MerchantOfferSignals(platform=platform, region_resolved=True,
                                    region_base=None, region_label=label)
    return MerchantOfferSignals(platform=platform, region_resolved=True, region_base=base)


CONFIG = make_config(
    "Greenmangaming",
    domain=DOMAIN,
    affiliate_hosts=(AFFILIATE_HOST,),
    # Le chemin du redirecteur (`/c/1297091/1272000/15105`) est le même pour les 482 lignes :
    # l'annonce est dans `u` (482 fiches distinctes le 21/09) ET dans `prodsku` (une fiche sert
    # plusieurs éditions — NHL 27 Standard / Deluxe sur la même page).
    url_identity_params=("u", "prodsku"),
    precheck=precheck,
    offer_page_resolver=offer_signals,
    console_url_families=console_url_families,
    console_pc_declared=console_pc_declared,
    # La fiche fait foi aussi sur la branche console (`[R68]`) : région lue sur la fiche pour
    # TOUTE ligne Xbox, une fiche « steam » sur une ligne console est un conflit.
    console_page_authoritative=True,
    notes=("feed store 22 — liens d'affiliation `greenmangaming.sjv.io/…?prodsku=<sku>&u=<fiche>` : "
           "la fiche de `u` fait foi, `u` + `prodsku` sont l'identité. [R73] plateforme = Drm de la "
           "fiche (steam / microsoft ; xbox-one = console), région = [R59] sur ExcludedCountries "
           "bornée par Romain (vide → GLOBAL ; exclusions hors UE/UK/USA → ROW ; UE, UK ou USA exclus "
           "→ refus), édition = Name confronté au titre, identité = Code == prodsku ; « (MAC) », "
           "crédits PSN, monnaies refusés (2026-10-09, PAS en liste blanche : aperçu à blanc d'abord)."),
)
