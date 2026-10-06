"""Indiegala (feed store 95) — la fiche produit fait foi, `[R69]` (2026-10-06).

Romain, 2026-10-06 : « garde ca de coté, regarde si possible de se former sur l ajout auto des
offres indiegala.com », puis, l'étude lue (docs/PROCHAINS_MARCHANDS.md, section du 06/10) :
« Si on peut ouvrir la page, on trouvera les infos ». Fichier écrit le 06/10, **hors liste
blanche** : aperçu à blanc d'abord (règle de Romain), aucune saisie sans son go. Modèle :
Allyouplay `[R68]` (``src/merchants/allyouplay.py``) — même ordre titre → URL → fiche, même
règle de région `[R59]`, même requête par la bibliothèque standard, mêmes refus nommés.

**Grammaire du feed (175 lignes du scan tous-magasins du 21/09)** : titre = le nom du jeu seul
(« Reach », « Monster Hunter Wilds Gold Edition », « SCUM Specialist Scout Pack ») ; URL
``https://www.indiegala.com/store/game/<slug>/<id steam>[_us|_deluxe|_del|…]`` (l'identité est dans
le chemin : pas de ``url_identity_params``). **Ni plateforme ni région dans le titre ou l'URL**
(0 / 175), sauf 7 suffixes « (US) » / « (EU) » en queue de titre (SILENT HILL: Townfall ×2,
PAC-MAN World 2 ×2, Katamari, Castlevania Belmont's Curse ×2 — le slug les répète : ``-us`` /
``-eu``). 5 titres multilingues « A / B / C » (parties japonaise et chinoise), 2 « Attack on
Titan 3 / A.O.T. 3 ». Sans lecteur de fiche, les 161 lignes qui passent le precheck générique
s'arrêtent sur R27 / `[R51]` (« no platform in title … ») : zéro saisie possible.

**La fiche est lisible** (HTTP 200, pas de Cloudflare, UA navigateur ; 8 fiches sur 8 le 06/10)
et dit tout :

* **plateforme** : « *<Nom>* is provided via **Steam Key** » (8 / 8). Un libellé connu → notre
  jeton (``PLATFORM_TEXT``) ; absent ou inconnu → refus NOMMÉ, jamais STEAM par défaut.
* **DLC** : l'encart « This content requires the base product … » (``ProductPage.is_dlc``, 2 fiches
  sur 8 : SCUM Specialist Scout Pack, Thunder Ray - Origin) est une GARDE, pas un routage
  (``MerchantOfferSignals.dlc`` → ``matcher.page_dlc_refusal``) : le seau reste décidé par les
  règles de titre R18 / `[R43]` / `[R57]` et la page AKS (aucun hook ``dlc_marker`` inventé : le
  titre Indiegala ne porte pas de grammaire DLC propre), mais une fiche DLC qui n'aboutit pas en
  DLC(16) est REFUSÉE. Aperçu du 06/10 : « Thunder Ray - Origin » (ORIGIN = bruit de plateforme
  pour le matcher, titre sans marqueur) sortait Standard(1) sur la page du jeu de base
  `thunder-ray` ; les quatre autres fiches DLC (SCUM ×2, Sherman Commander Supporter Pack, V8
  Power Pack) ont leur page AKS à seau DLC unique et entrent en DLC(16).
* **région** — TROIS blocs, à ne pas confondre :

  1. l'encart latéral ``store-product-contents-aside-note-alt`` « Region locked product — It will
     only work in the region from where it is bought » (7 fiches sur 8, absent de Thunder Ray) :
     la clé est liée à la région d'ACHAT. **IGNORÉ** : c'est la politique de vente du marchand,
     pas la liste d'activation du produit — la même lecture que pour Gamesplanet FR `[R59]`, où
     la politique de vente n'est pas lue non plus ; Romain : « si on trouve les infos sur la
     page, OK ».
  2. l'avertissement d'article ``store-product-contents-article-warning-inner`` dont le h3 est
     « **Region locked product** » (« The keys of this product can only be activated in the
     country they were purchased », Reach) : verrou PAYS → refus « clé activable seulement dans
     le pays d'achat — non entrée (R69) », rendu ``forbidden region: INDIEGALA LOCK (COUNTRY OF
     PURCHASE)`` (le routeur central ``aks_lists.suggest_target_list`` → garder).
  3. l'avertissement « **Country availability** » / « **Banned countries** » + la liste des pays
     où la vente est interdite « as per publisher request » (MHW Gold 18 pays, SCUM 59, LBA2 77,
     Belmont's Curse (EU) 125, Castlevania bundle 215, SH Townfall (US) 222) → la règle `[R59]`
     de Romain (Gamesplanet FR, 2026-09-25) sur les pays EXCLUS, par la MÊME table
     (``gamesplanet.region_from_lock(("NOT", pays), label="INDIEGALA")``) : ni UE, ni UK, ni USA
     exclus → GLOBAL ; UE entière autorisée, USA exclus → EU ; USA autorisés, un pays de l'UE
     exclu → US ; UE touchée ET USA exclus → ``INDIEGALA LOCK (EU + US)`` ; UK seul → ``… (UK)``.
     Pas de bloc d'avertissement du tout → GLOBAL (Thunder Ray).

**Règle de région PROPOSÉE par Claude, à confirmer par Romain à l'aperçu** — ce n'est PAS une
décision revue : AKS n'affiche aucune offre Indiegala (5 pages lues le 06/10), il n'y a donc
aucun précédent. Résultat sur les 8 fiches : MHW Gold / SCUM / LBA2 / Thunder Ray → GLOBAL ;
SH Townfall (US) (toute l'UE + UK interdits, USA autorisés) → US ; Castlevania LoS2 bundle (USA
interdits, UE entière autorisée) → EU — refusé bundle au precheck de toute façon ; Reach → verrou
pays, refus ; **Belmont's Curse (EU) → refus « LOCK (EU + US) »** : la liste interdit les USA ET
Chypre, donc l'UE n'est pas entière — la lecture stricte de `[R59]` (« UE sans USA → EU » vaut
pour l'UE complète) refuse une clé que son titre dit « (EU) ». Point à trancher par Romain :
tel quel (refus, aucune écriture fausse possible), ou « (EU) du titre + UE quasi complète → EU ».
Rien de plus souple n'est codé.

**Le titre** (``title_region`` / ``resolve_name`` / ``guard_name``) :

* un suffixe « (US) » / « (EU) » / « (UK) » en QUEUE de titre déclare la région (``title_region``)
  et sort du nom résolu et du nom des gardes ; il doit S'ACCORDER avec la fiche (« (US) » sur une
  fiche GLOBAL ou EU → refus nommé), la fiche décidant seule du reste ;
* un titre multilingue « A / B / C » est réduit à sa PREMIÈRE partie quand chaque autre partie est
  une traduction dans une autre écriture (kana, han, hangul, cyrillique… — un caractère hors du
  latin étendu) ou le même nom répété ; une alternative LATINE différente (« Attack on Titan 3 /
  A.O.T. 3 », « … / Ensemble Edition Deluxe Complet ») n'est PAS coupée : le titre reste entier
  et les gardes d'identité (R01 / R16) le comparent tel quel à la page AKS — un refus, jamais une
  écriture sur un nom deviné. Décision de Claude, à confirmer par Romain (2 lignes AOT 3).

**Fail-closed** : lien hors indiegala.com ou hors ``/store/game/``, fiche injoignable, statut ≠ 200,
lien canonique absent ou autre que la fiche demandée (une fiche périmée renvoie à l'ACCUEIL,
canonique ``/store`` : « Attack on Titan 3 … Digital Deluxe » le 06/10), repères de fiche absents,
pas de « is provided via », libellé de plateforme inconnu, avertissement d'article inconnu, liste
de pays absente ou vide → refus, JAMAIS un repli sur STEAM ou GLOBAL. Aucune page d'un autre
marchand n'est lue. Politesse : une requête par fiche et par processus (cache, échecs compris),
~1 requête / s.
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
# La normalisation des noms de pays de `[R59]` (minuscules, « Czech Republic » → « czechia »…) :
# UNE table, pas une copie — la décision ne se prend que sur les 27 noms de l'UE, « united
# kingdom » et « united states » de `gamesplanet`.
from src.merchants.gamesplanet import _country as country_name
from src.merchants.gamesplanet import region_from_lock

DOMAIN = "indiegala.com"
PRODUCT_PATH_PREFIX = "/store/game/"
PROBE_DELAY_S = 1.0                   # ~1 requête / s sur un balayage complet (~175 fiches)
RULE = "R69"


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def _on_domain(url: str) -> bool:
    host = _host(url)
    return host == DOMAIN or host.endswith("." + DOMAIN)


# ── le titre ──────────────────────────────────────────────────────────────────────────
_SUFFIX_RE = re.compile(r"\s*\(\s*(?P<code>US|EU|UK)\s*\)\s*$", re.IGNORECASE)
# « A / B », « A /B » (vu : « … /完全豪華組合包 ») — jamais un « / » collé des deux côtés
# (« Half-Life/Portal » serait un nom).
_ALT_SEP_RE = re.compile(r"\s+/\s*")
# Un caractère au-delà du latin étendu (U+024F) : kana, han, hangul, cyrillique, grec, arabe…
# Un accent latin (« Édition ») n'en est pas un : une partie accentuée reste une alternative
# latine, donc pas de coupe.
_NON_LATIN_RE = re.compile(r"[^\u0000-ɏ]")


def title_region(name: str) -> str | None:
    """La région qu'un suffixe « (US) » / « (EU) » / « (UK) » en queue de titre déclare, sinon
    None (le générique lit alors le titre et l'URL ; la fiche décide de toute façon)."""

    m = _SUFFIX_RE.search(name or "")
    return m.group("code").lower() if m else None


def strip_region_suffix(name: str) -> str:
    return _SUFFIX_RE.sub("", name or "").strip()


def _words(part: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", part.lower())


def first_name(name: str) -> str:
    """La première partie d'un titre multilingue « A / B / C », quand chaque autre partie est une
    traduction dans une autre écriture ou le même nom répété ; sinon le titre entier."""

    parts = [p.strip() for p in _ALT_SEP_RE.split(name or "") if p.strip()]
    if len(parts) < 2:
        return (name or "").strip()
    head = parts[0]
    for part in parts[1:]:
        if _NON_LATIN_RE.search(part):
            continue                          # traduction dans une autre écriture
        if _words(part) == _words(head):
            continue                          # le même nom, répété
        return (name or "").strip()           # une alternative latine : on ne devine pas
    return head


def resolve_name(name: str) -> str:
    """Le texte remis à la résolution AKS : sans le suffixe de région, première partie d'un
    titre multilingue."""

    return first_name(strip_region_suffix(name))


def guard_name(name: str) -> str:
    """Le titre que lisent les gardes d'identité (R01 / R16 / R01b) et ``detect_edition`` :
    la même lecture que ``resolve_name`` — « (US) » n'est pas un mot du produit."""

    return resolve_name(name)


# ── la fiche ──────────────────────────────────────────────────────────────────────────
# Libellés « is provided via <strong>…</strong> » → notre jeton. OBSERVÉ le 06/10 : « Steam Key »
# seul (8 / 8). Les autres libellés sont ceux que le magasin affiche pour ses autres clés ;
# un libellé hors de cette table est un refus nommé (jamais STEAM par défaut) et la page AKS
# doit vendre la plateforme lue (R20).
PLATFORM_TEXT: dict[str, str] = {
    "steam key": "STEAM",
    "gog key": "GOG", "gog.com key": "GOG",
    "epic games key": "EPIC", "epic games store key": "EPIC",
    "origin key": "EA", "ea app key": "EA",
    "ubisoft connect key": "UBISOFT", "uplay key": "UBISOFT",
    "rockstar key": "ROCKSTAR", "rockstar games launcher key": "ROCKSTAR",
    "battle.net key": "BATTLENET",
    "microsoft store key": "MICROSOFT",
}

WARNING_LOCK = "region locked product"                      # verrou PAYS (Reach)
WARNING_LISTS = frozenset({"country availability", "banned countries"})
LOCK_LABEL = "INDIEGALA LOCK (COUNTRY OF PURCHASE)"
DLC_TEXT = "This content requires the base product"
_PRODUCT_MARKER = 'class="store-product-contents'

_LINK_RE = re.compile(r"<link\b[^>]*>", re.I)
_HREF_RE = re.compile(r'\bhref="(?P<href>[^"]+)"', re.I)
_PROVIDED_RE = re.compile(r"is provided via\s*<strong>(?P<text>[^<]*)</strong>", re.I)
_WARNING_RE = re.compile(
    r'class="store-product-contents-article-warning-inner"[^>]*>\s*<h3[^>]*>(?P<h3>[^<]*)</h3>',
    re.I)
_LIST_RE = re.compile(
    r'class="store-product-contents-article-warning-list"[^>]*>(?P<list>.*?)</div>', re.S | re.I)


class IndiegalaPageUnreadable(RuntimeError):
    """Fiche injoignable, non identifiée, ou lisible mais sans ce qu'il faut pour décider : on
    refuse, on ne devine ni la plateforme ni la région."""


@dataclass(frozen=True)
class ProductPage:
    path: str                                           # chemin canonique, en minuscules
    platform_text: str                                  # « Steam Key »
    is_dlc: bool                                        # « This content requires the base product »
    # (genre d'avertissement, pays normalisés) — le verrou pays porte un ensemble vide.
    warnings: tuple[tuple[str, frozenset[str]], ...]

    @property
    def banned_countries(self) -> frozenset[str]:
        return frozenset().union(*(pays for _, pays in self.warnings)) if self.warnings else frozenset()

    @property
    def country_locked(self) -> bool:
        return any(kind == WARNING_LOCK for kind, _ in self.warnings)


def _norm_path(path: str) -> str:
    return (path or "").rstrip("/").lower()


def canonical_path(body: str) -> str | None:
    """Le chemin du ``<link rel="canonical">`` (attributs dans n'importe quel ordre), sinon None."""

    for tag in _LINK_RE.findall(body):
        if re.search(r'\brel="canonical"', tag, re.I):
            m = _HREF_RE.search(tag)
            return urlsplit(html.unescape(m.group("href"))).path if m else None
    return None


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def parse_product_page(body: str, expected_path: str) -> ProductPage:
    """Lit une fiche indiegala.com. Lève ``IndiegalaPageUnreadable`` pour tout ce qui n'est pas
    la fiche demandée, lisible, avec sa plateforme et ses avertissements compris."""

    canon = canonical_path(body)
    if canon is None:
        raise IndiegalaPageUnreadable(f"fiche sans lien canonique — non identifiée ({RULE})")
    if _norm_path(canon) != _norm_path(expected_path):
        # Une fiche périmée est redirigée vers l'ACCUEIL du magasin (canonique `/store`).
        raise IndiegalaPageUnreadable(
            f"la page servie n'est pas la fiche demandée (canonique {canon}) — fiche périmée "
            f"ou retirée, non identifiée ({RULE})")
    if _PRODUCT_MARKER not in body:
        raise IndiegalaPageUnreadable(
            f"page sans les repères d'une fiche produit (store-product-contents) ({RULE})")
    provided = _PROVIDED_RE.search(body)
    if provided is None:
        raise IndiegalaPageUnreadable(
            f"fiche sans « is provided via … » — plateforme inconnue, non entrée ({RULE})")
    heads = list(_WARNING_RE.finditer(body))
    warnings: list[tuple[str, frozenset[str]]] = []
    for i, head in enumerate(heads):
        kind = _clean(head.group("h3")).lower()
        if kind == WARNING_LOCK:
            warnings.append((kind, frozenset()))
            continue
        if kind not in WARNING_LISTS:
            raise IndiegalaPageUnreadable(
                f"avertissement inconnu sur la fiche : « {_clean(head.group('h3'))} » — gabarit "
                f"changé, non entrée ({RULE})")
        segment = body[head.end():heads[i + 1].start() if i + 1 < len(heads) else len(body)]
        liste = _LIST_RE.search(segment)
        if liste is None:
            raise IndiegalaPageUnreadable(
                f"avertissement « {_clean(head.group('h3'))} » sans liste de pays ({RULE})")
        # La liste est séparée par des virgules, et certains NOMS en portent une (« Korea,
        # Republic of », « Congo, The Democratic Republic of the », « Virgin Islands, U.S. »).
        # La coupe produit alors des fragments (« republic of », « u.s. ») — SANS EFFET sur la
        # décision : seuls les 27 noms de l'UE, « united kingdom » et « united states » comptent,
        # et aucun fragment ne les vaut (« united states minor outlying islands » reste entier :
        # pas de virgule). Épinglé par un test.
        pays = frozenset(c for c in (country_name(x) for x in liste.group("list").split(",")) if c)
        if not pays:
            raise IndiegalaPageUnreadable(
                f"avertissement « {_clean(head.group('h3'))} » avec une liste de pays vide ({RULE})")
        warnings.append((kind, pays))
    return ProductPage(path=_norm_path(canon), platform_text=_clean(provided.group("text")),
                       is_dlc=DLC_TEXT in body, warnings=tuple(warnings))


def page_platform(page: ProductPage) -> str:
    """Le jeton de la plateforme PC ; lève pour un libellé inconnu — jamais STEAM par défaut."""

    token = PLATFORM_TEXT.get(page.platform_text.lower())
    if token is None:
        raise IndiegalaPageUnreadable(
            f"plateforme de la fiche inconnue : « {page.platform_text} » — non entrée ({RULE})")
    return token


def page_region(page: ProductPage) -> tuple[str | None, str]:
    """La règle `[R59]` de Romain sur la liste des pays INTERDITS ; le verrou pays d'achat est
    un refus nommé avant toute liste ; aucun avertissement = GLOBAL."""

    if page.country_locked:
        return None, LOCK_LABEL
    if not page.warnings:
        return region_from_lock(None, label="INDIEGALA")
    return region_from_lock(("NOT", page.banned_countries), label="INDIEGALA")


# ── la requête ────────────────────────────────────────────────────────────────────────
# Comme Allyouplay `[R68]` : la fiche est lue par la bibliothèque standard, PAS par
# `aks_env.http_get` (son moteur `requests` envoie « User-agent », forme que le Cloudflare
# d'Allyouplay refusait : 241 / 241 en 403 le 30/09), et le moteur partagé des requêtes vers AKS
# n'est pas touché. Même contrat que `http_get` : un `HttpProbeResult`, jamais d'exception.
_MAX_BODY = 2_000_000


def page_get(url: str, timeout: int = 20,
             user_agent: str = REQUIRED_USER_AGENT) -> HttpProbeResult:
    """GET d'une fiche indiegala.com (redirections suivies, hôte final vérifié)."""

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
                               error=f"redirigé hors d'indiegala.com : {final}")
    return HttpProbeResult(url=url, ok=status == 200, status=status, body=body)


_CACHE: dict[str, ProductPage | str] = {}


def clear_cache() -> None:
    _CACHE.clear()


def product_url(url: str) -> str | None:
    """L'URL de la fiche à ouvrir (sans query ni fragment), ou None si ce n'en est pas une."""

    if not _on_domain(url):
        return None
    parts = urlsplit(url)
    if not _norm_path(parts.path).startswith(PRODUCT_PATH_PREFIX):
        return None
    return f"{parts.scheme or 'https'}://{parts.netloc}{parts.path.rstrip('/')}"


def fetch_product_page(url: str, http_get_fn: Callable[..., Any] = page_get) -> ProductPage:
    """Ouvre la fiche indiegala.com de l'offre (une fois par processus). Lève si illisible."""

    target = product_url(url)
    if target is None:
        raise IndiegalaPageUnreadable(
            f"lien sans fiche produit indiegala.com (/store/game/…) — aucune autre page n'est "
            f"lue ({RULE})")
    path = _norm_path(urlsplit(target).path)
    cached = _CACHE.get(target)
    if isinstance(cached, ProductPage):
        return cached
    if isinstance(cached, str):
        raise IndiegalaPageUnreadable(cached)
    if http_get_fn is page_get:
        time.sleep(PROBE_DELAY_S)
    try:
        try:
            response = http_get_fn(target, timeout=20, user_agent=REQUIRED_USER_AGENT)
        except Exception as exc:             # noqa: BLE001 — tout échec = refus
            raise IndiegalaPageUnreadable(f"fiche Indiegala injoignable : {exc}") from exc
        if not (response.ok and response.status == 200 and response.body):
            raise IndiegalaPageUnreadable(
                f"réponse inattendue : {response.status or response.error}")
        page = parse_product_page(response.body, path)
    except IndiegalaPageUnreadable as exc:
        if len(_CACHE) < 4096:
            _CACHE[target] = str(exc)
        raise
    if len(_CACHE) < 4096:
        _CACHE[target] = page
    return page


def offer_signals(url: str, name: str = "",
                  http_get_fn: Callable[..., Any] = page_get) -> MerchantOfferSignals:
    """Le résolveur `[R69]` : la fiche donne la plateforme (confrontée par le matcher à celle du
    titre / de l'URL, qui n'en disent rien ici) et TOUJOURS la région. Un suffixe « (US) » /
    « (EU) » du titre doit s'accorder avec elle. Une fiche illisible lève → refus R32."""

    page = fetch_product_page(url, http_get_fn)
    platform = page_platform(page)
    base, label = page_region(page)
    if base is None:
        return MerchantOfferSignals(platform=platform, region_resolved=True,
                                    region_base=None, region_label=label, dlc=page.is_dlc)
    suffix = title_region(name)
    if suffix is not None and suffix != base:
        raise IndiegalaPageUnreadable(
            f"le suffixe « ({suffix.upper()}) » du titre contredit la fiche "
            f"({base.upper() if base != 'global' else 'GLOBAL'}) — non entrée ({RULE})")
    # `dlc` : la fiche dit « DLC » → garde du matcher (`page_dlc_refusal`), jamais un routage.
    return MerchantOfferSignals(platform=platform, region_resolved=True, region_base=base,
                                dlc=page.is_dlc)


CONFIG = make_config(
    "Indiegala",
    domain=DOMAIN,
    title_region=title_region,
    resolve_name=resolve_name,
    guard_name=guard_name,
    offer_page_resolver=offer_signals,
    # Indiegala vend des clés PC (« Steam Key », 8 / 8). Aucune ligne console dans le feed du
    # 21/09 ; si la grammaire console partagée en lisait une un jour, la fiche est lue pour
    # elle aussi (`[R68]`, revue adverse du 30/09) : une fiche « Steam Key » sur une ligne console
    # est un conflit, refusé — jamais une page Xbox / PlayStation écrite sur une clé Steam.
    console_page_authoritative=True,
    notes=("feed store 95 — URL `indiegala.com/store/game/<slug>/<id>` (identité dans le chemin). "
           "[R69] (2026-10-06 ; aperçu à blanc du 06/10 : 34 / 175, puis « go pour la liste blanche ») : plateforme = « is "
           "provided via » de la fiche (jamais STEAM par défaut) ; région = liste des pays "
           "interdits de la fiche, règle [R59] de Romain — PROPOSÉE, à confirmer à l'aperçu ; "
           "verrou « Region locked product » (article) → refus ; encart « région d'achat » "
           "ignoré ; suffixe (US)/(EU)/(UK) du titre = title_region, doit s'accorder avec la "
           "fiche ; titre multilingue « A / B / C » réduit à sa première partie quand les autres "
           "sont dans une autre écriture ; DLC de la fiche = GARDE (une fiche DLC qui n'aboutit "
           "pas en DLC(16) est refusée — « Thunder Ray - Origin », aperçu du 06/10), jamais un "
           "routage."),
)
