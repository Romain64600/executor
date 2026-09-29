"""[R66] La recherche catalogue AKS, en DERNIER recours du résolveur (Romain, 2026-09-29 :
« La recherche AKS en dernier recours me semble indispensable »).

Pourquoi. L'audit « pas de page produit » du 28/09 (`docs/AUDIT_2026-09-28_pages-produit-
absentes.md`, §4.4 et proposition 11) : la recherche de secours R30 (`/blog/?s=`) est MORTE depuis
le 22/09 (`HTTP 200`, corps vide) et, avec un index sitemap frais, `resolve_aks` rendait `None`
avant même de l'appeler. Il n'existait donc AUCUN filet pour un nom qu'on ne sait pas deviner
(« COD Black Ops Cold War », « Heroes of Might & Magic Olden Era »…). Le site, lui, cherche avec
une API JSON :

    https://www.allkeyshop.com/api/v2-1-250304/vakrs_catalogv2.php?action=CatalogV2&…

C'est l'``apiUrl`` que la page de recherche du site (``/blog/products/?search_name=…``) embarque
pour son propre front (``_app.version=2026-02-13``) — relu en direct le 2026-09-29. Avec
``fields=id,name,link,type`` elle répond ~500 octets en ~0,1 s, contre 2,8 Mo pour la page de
recherche. Ce n'est PAS un modèle ni une « résolution APIv2 » : du HTTP + JSON déterministe.

Ce que ce module fait — et seulement ça :

* **l'appel** : UNE requête GET par titre, agent « AKS/Staff » toujours, au plus une toutes les
  ``MIN_INTERVAL_S`` secondes, une seule reprise après ``RETRY_WAIT_S`` sur un 5xx / une erreur
  de transport ;
* **la version est un fait, jamais une supposition** : l'adresse porte une version
  (``v2-1-250304``) qui peut changer sans préavis. Une version retirée répond ``404`` à corps vide
  (vérifié le 29/09 sur ``v2-1-000000``). Un 404 / 410, un corps qui n'est pas du JSON ou un JSON
  qui n'a plus la forme attendue lèvent :class:`AksSearchChanged` avec une raison NOMMÉE, et la
  recherche se coupe (état persisté dans le dossier du balayage). On ne devine jamais la nouvelle
  version : c'est une constante qu'un humain met à jour. Revue du 2026-09-29 : un 404 / 410
  (version retirée) coupe pour TOUT le balayage ; un corps illisible (HTML de maintenance, JSON
  d'une autre forme) ne coupe que ``UNREADABLE_DISABLE_S`` — la même demi-heure que le
  disjoncteur R30, qui a perdu son « pour tout le balayage » le 20/09 pour la même raison : une
  passe dure ~30 h, une page de maintenance quelques minutes ;
* **le budget** : un plafond de requêtes PAR BALAYAGE (``DEFAULT_BUDGET``), compté dans un fichier
  d'état du dossier du balayage, recopié dans ``match_meta.json``. Il est PARTAGÉ par les
  marchands de la passe, dans leur ordre de passage (voir ``DEFAULT_BUDGET``) ;
* **le cache** : persistant (``state/``), par titre normalisé + gabarit de page, avec une durée de
  vie (``CACHE_TTL_S``) ; les réponses VIDES sont gardées aussi — les boucles relisent les mêmes
  lignes à chaque passe ; une erreur ne l'est jamais.

Ce qu'il ne fait PAS : décider. Il rend des CANDIDATS (les liens que le filtre du matcher
retient) ; chaque page candidate est ensuite lue comme une page devinée, et toutes les gardes
(R01, R01b, R20, R27, R43, E06…) s'appliquent inchangées. Le filtre lui-même vit dans
``src/matcher.py`` (`catalog_candidates`), qui connaît la grammaire des pages.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from src import aks_env

# L'adresse que le front du site utilise, relue sur /blog/products/ le 2026-09-29. Une version
# qui change ne se DEVINE pas : on met cette constante à jour à la main, après l'avoir relue.
API_VERSION = "v2-1-250304"
API_URL = "https://www.allkeyshop.com/api/{version}/vakrs_catalogv2.php"
# Les paramètres que le front envoie lui-même (même tri, même langue, même devise), réduits aux
# QUATRE champs utiles : sans eux la réponse porte prix, images et offres (plusieurs Ko).
API_QUERY = ("?action=CatalogV2&locale=en&currency=EUR&price_mode=price_card&search_name={q}"
             "&sort_field=popularity&sort_order=desc&pagenum=1&per_page=24"
             "&fields=id,name,link,type")
TIMEOUT_S = 8
# Une requête catalogue pèse ~500 octets, une page produit ~300 Ko : ce n'est pas la bande
# passante qui borne, c'est le rythme. Une seconde au moins entre deux appels (le matcher sonde
# les pages produit toutes les 0,15 s), une reprise unique après 2 s sur un 5xx.
MIN_INTERVAL_S = 1.0
RETRY_WAIT_S = 2.0
# Le budget PAR BALAYAGE (par passe en mode boucle : chaque passe a son dossier). Arithmétique
# (audit du 28/09) : ≈ 8 800 lignes « pas de page » côté groupe B, une passe ≈ 30 h. À 1 000
# requêtes par passe et 14 jours de cache, tout le stock est interrogé en ~9 passes et le régime
# permanent en demande ≈ 8 800 / 14 j ≈ 630 par jour, soit ≈ 790 par passe — le budget le
# tient. 1 000 requêtes sur 30 h font ≈ 0,6 par minute : rien à côté des sondes de pages. Les
# bans passés (28/08, 11/09) venaient de l'agent navigateur et de rafales, pas du rythme
# « AKS/Staff ».
#
# PARTAGÉ par les marchands de la passe, dans leur ORDRE (revue du 2026-09-29) : un seul fichier
# d'état par dossier de balayage. Le premier marchand (GameSeal, ≈ 2 300 lignes « pas de page »)
# peut épuiser la passe ; les suivants attendent une passe ou deux. Voulu : une part égale par
# marchand (1 000 / 8 = 125) ne couvrirait JAMAIS GameSeal dans la durée de vie du cache
# (≈ 2 300 / 11 passes ≈ 210 par passe > 125) — ses réponses expireraient avant d'être toutes
# obtenues —, alors que le budget partagé couvre tout le stock en ~9 passes (ci-dessus). Le coût
# est un DÉLAI pour les derniers marchands, jamais une ligne mal saisie ; `meta()["budget_scope"]`
# le dit dans chaque match_meta.json.
#
# Ce budget ne compte QUE l'API. Les pages candidates qu'elle fait lire sont des sondes de page
# ordinaires (rythme `AKS_PROBE_DELAY_S`, garde de throttle) : `resolve_aks` rend la PREMIÈRE
# page qui répond, donc ≈ UNE lecture par ligne qui a un candidat, à chaque passe tant que la
# réponse est en cache — exactement le coût d'une page devinée que les gardes refusent ensuite.
# Mesuré au rejeu du 29/09 (population de l'audit) : voir EXECUTOR_RULES [R66].
DEFAULT_BUDGET = 1000
BUDGET_SCOPE = "balayage — partagé par les marchands de la passe, dans leur ordre"
# Une coupure pour corps ILLISIBLE expire au bout de la même demi-heure que le disjoncteur R30
# (`scripts/03_match.py` SEARCH_CIRCUIT_TTL_S) ; une version RETIRÉE (404 / 410) ne l'est pas.
UNREADABLE_DISABLE_S = 30 * 60
# Une seule durée pour les réponses pleines et vides. Les vides dominent (≈ 47 % des lignes
# n'ont vraiment pas de page) : une durée plus courte pour elles ferait expirer le stock plus
# vite que le budget ne le couvre, et on ne ré-interrogerait que de vieux « rien ». Une page
# créée entre-temps sous un nom DÉRIVABLE est de toute façon trouvée par l'index sitemap, relu
# à chaque balayage.
CACHE_TTL_S = 14 * 24 * 3600
DEFAULT_CACHE_PATH = "state/aks_search_cache.json"
CACHE_FORMAT = 1
CACHE_MAX_ENTRIES = 60_000


class AksSearchUnavailable(Exception):
    """La recherche n'a pas répondu proprement (5xx, délai, 429…) : ce n'est PAS « aucun
    résultat ». ``status`` porte le code HTTP (``None`` pour une erreur de transport)."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class AksSearchChanged(AksSearchUnavailable):
    """L'API a CHANGÉ (version retirée, corps qui n'est plus du JSON attendu) : refus nommé, et
    la recherche se coupe pour le reste du balayage. Jamais une nouvelle version devinée."""


@dataclass(frozen=True)
class CatalogProduct:
    id: int
    name: str
    link: str
    type: str


def api_url(query: str, version: str = API_VERSION) -> str:
    return API_URL.format(version=version) + API_QUERY.format(q=quote(query))


def normalize_query(query: str) -> str:
    return " ".join(str(query or "").lower().split())


def cache_key(kind: str, query: str, filter_version: int, context: str = "") -> str:
    """La clé : version d'API + version du filtre + gabarit de page + titre normalisé. Changer
    l'une des deux constantes invalide tout le cache, sans rien effacer à la main.

    ``context`` (revue du 2026-09-29) : ce dont le FILTRE dépend en plus de la requête — le
    matcher y met les mots du titre BRUT, contre lesquels il vérifie chaque nom. Deux titres qui
    partagent une requête (« The Tartarus Key (PC) Steam Gift » et « The Tartarus (PC) Steam »
    donnent tous deux « The Tartarus ») ne partagent donc pas leurs candidats filtrés."""

    key = f"{API_VERSION}|f{int(filter_version)}|{kind}|{normalize_query(query)}"
    return f"{key}|{normalize_query(context)}" if context else key


def parse_response(body: str) -> list[CatalogProduct]:
    """Le JSON de l'API → produits. Toute forme inattendue lève :class:`AksSearchChanged` —
    c'est le signe qu'on ne lit plus la même API, pas une absence de résultat."""

    try:
        data = json.loads(body)
    except (TypeError, ValueError) as exc:
        raise AksSearchChanged(f"réponse qui n'est pas du JSON ({exc.__class__.__name__})") from None
    if not isinstance(data, dict):
        raise AksSearchChanged("réponse JSON qui n'est pas un objet")
    products = data.get("products")
    pagination = data.get("pagination")
    if not isinstance(products, list) or not isinstance(pagination, dict):
        raise AksSearchChanged("réponse sans 'products' (liste) ni 'pagination' (objet)")
    if not isinstance(pagination.get("total"), int):
        raise AksSearchChanged("'pagination.total' absent ou non entier")
    out: list[CatalogProduct] = []
    for item in products:
        if not isinstance(item, dict):
            raise AksSearchChanged("produit qui n'est pas un objet")
        name, link, kind, pid = item.get("name"), item.get("link"), item.get("type"), item.get("id")
        if not (isinstance(name, str) and isinstance(link, str) and isinstance(kind, str)
                and isinstance(pid, int)):
            raise AksSearchChanged("produit sans id / name / link / type")
        out.append(CatalogProduct(id=pid, name=name, link=link, type=kind))
    return out


def _load_cache(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}                   # un cache illisible est un cache vide : jamais bloquant
    if not isinstance(raw, dict) or raw.get("format") != CACHE_FORMAT:
        return {}
    entries = raw.get("entries")
    return dict(entries) if isinstance(entries, dict) else {}


class AksCatalogSearch:
    """Une session de recherche catalogue pour UN processus de match (une page de feed).

    ``used`` : les requêtes déjà dépensées par le balayage (fichier d'état) ; ``budget`` : le
    plafond du balayage. ``disabled_reason`` non vide (lu dans l'état du balayage, ou posé ici
    sur une API changée) coupe tout appel réseau — le cache reste servi : ce sont des réponses
    de l'API d'avant, dans leur durée de vie, et chaque page candidate est relue de toute façon.
    ``disabled_until`` (horodatage, 0 = jusqu'à la fin du balayage) : l'échéance d'une coupure
    pour corps illisible ; passée, la recherche reprend (et se recoupe si l'API l'est encore).
    """

    def __init__(self, *, budget: int = DEFAULT_BUDGET, used: int = 0,
                 cache_path: str | None = None, ttl_s: float = CACHE_TTL_S,
                 disabled_reason: str = "", disabled_until: float = 0.0,
                 now: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep,
                 min_interval_s: float = MIN_INTERVAL_S,
                 retry_wait_s: float = RETRY_WAIT_S) -> None:
        self.budget = max(0, int(budget))
        self.used_before = max(0, int(used))
        self.used = self.used_before
        self.cache_path = cache_path
        self.ttl_s = float(ttl_s)
        self.disabled_reason = str(disabled_reason or "")
        self.disabled_until = float(disabled_until or 0.0) if self.disabled_reason else 0.0
        self._now = now
        self._sleep = sleep
        self._min_interval_s = float(min_interval_s)
        self._retry_wait_s = float(retry_wait_s)
        self._last_request: float | None = None
        self._cache = _load_cache(cache_path)
        self._fresh: dict[str, Any] = {}           # entrées écrites par CE processus
        self.stats: dict[str, int] = {
            "requests": 0,            # requêtes HTTP vers l'API (reprise comprise)
            "queries": 0,             # titres effectivement interrogés
            "cache_hits": 0,
            "hits": 0,                # interrogés, au moins un candidat
            "empty": 0,               # interrogés, aucun candidat retenu
            "failures": 0,            # 5xx / délai / 429 / API changée
            "budget_exhausted_offers": 0,
            "disabled_offers": 0,
            "search_off_offers": 0,   # disjoncteur R30 ouvert : cache seulement
            "candidate_pages_read": 0,
            "resolved": 0,            # une page candidate a répondu (les gardes décident ensuite)
            # revue du 29/09 : une page lue dont le NOM contredit le titre (mot répété, ordre,
            # article en tête) est écartée — candidat suivant (`catalog_name_mismatch`).
            "rejected_after_read": 0,
        }

    # -- lecture -----------------------------------------------------------------------------
    @property
    def remaining(self) -> int:
        return max(0, self.budget - self.used)

    def _is_disabled(self) -> bool:
        """La coupure tient-elle encore ? Une coupure à échéance (corps illisible) passée est
        levée ici : la recherche reprend, et se recoupe si l'API est toujours illisible."""

        if not self.disabled_reason:
            return False
        if self.disabled_until and self._now() >= self.disabled_until:
            self.disabled_reason, self.disabled_until = "", 0.0
            return False
        return True

    def _cached(self, key: str) -> list[tuple[str, str, str]] | None:
        entry = self._fresh.get(key) or self._cache.get(key)
        if not isinstance(entry, dict):
            return None
        try:
            age = self._now() - float(entry.get("t"))
            cands = [tuple(str(x) for x in c) for c in entry.get("c", [])]
        except (TypeError, ValueError):
            return None
        if age < 0 or age >= self.ttl_s or any(len(c) != 3 for c in cands):
            return None
        return cands                                        # type: ignore[return-value]

    def lookup(self, kind: str, query: str, http_get_fn: Callable[..., Any],
               select: Callable[[list[CatalogProduct]], list[tuple[str, str, str]]], *,
               filter_version: int, allow_request: bool = True, context: str = ""
               ) -> list[tuple[str, str, str]] | None:
        """Les candidats ``(slug, url, nom)`` pour ``query``, ``[]`` si l'API n'en a aucun, ou
        ``None`` si elle n'a PAS été interrogée (disjoncteur, API coupée, budget épuisé) — le
        résolveur rend alors « pas de page », comme avant. Lève :class:`AksSearchUnavailable`
        / :class:`AksSearchChanged` sur une réponse douteuse."""

        key = cache_key(kind, query, filter_version, context)
        cached = self._cached(key)
        if cached is not None:
            self.stats["cache_hits"] += 1
            return list(cached)
        if not allow_request:
            self.stats["search_off_offers"] += 1
            return None
        if self._is_disabled():
            self.stats["disabled_offers"] += 1
            return None
        if self.used >= self.budget:
            self.stats["budget_exhausted_offers"] += 1
            return None
        products = self._fetch(query, http_get_fn)
        candidates = [tuple(c) for c in select(products)]
        self.stats["queries"] += 1
        self.stats["hits" if candidates else "empty"] += 1
        self._fresh[key] = {"t": self._now(), "c": [list(c) for c in candidates],
                            "n": len(products)}
        return candidates                                   # type: ignore[return-value]

    def _pace(self, http_get_fn: Callable[..., Any]) -> None:
        if http_get_fn is not aks_env.http_get or self._last_request is None:
            return
        wait = self._min_interval_s - (time.monotonic() - self._last_request)
        if wait > 0:
            self._sleep(wait)

    def _fetch(self, query: str, http_get_fn: Callable[..., Any]) -> list[CatalogProduct]:
        url = api_url(query)
        for attempt in (1, 2):
            self._pace(http_get_fn)
            self.used += 1
            self.stats["requests"] += 1
            probe = http_get_fn(url, timeout=TIMEOUT_S, user_agent=aks_env.AKS_STAFF_UA)
            self._last_request = time.monotonic()
            status = getattr(probe, "status", None)
            body = getattr(probe, "body", "") or ""
            if status == 200 and getattr(probe, "ok", False) and body:
                try:
                    return parse_response(body)
                except AksSearchChanged as exc:
                    # Corps illisible : coupure à ÉCHÉANCE (revue du 29/09) — une page de
                    # maintenance ne doit pas couper les ~30 h d'une passe.
                    self._disable(f"{API_VERSION} : {exc}",
                                  until=self._now() + UNREADABLE_DISABLE_S)
                    raise AksSearchChanged(self.disabled_reason, status=status) from None
            if status in (404, 410):
                # Une version retirée : 404 à corps vide (vérifié le 29/09). Jamais « rien ».
                self._disable(f"{API_VERSION} : HTTP {status}, version d'API introuvable")
                raise AksSearchChanged(self.disabled_reason, status=status)
            transient = status is None or status >= 500 or (status == 200 and not body)
            if attempt == 1 and transient and status != 429 and self.used < self.budget:
                if http_get_fn is aks_env.http_get:
                    self._sleep(self._retry_wait_s)
                continue
            self.stats["failures"] += 1
            detail = status if status is not None else (getattr(probe, "error", "") or "transport")
            if status == 200:
                detail = "200, corps vide"
            raise AksSearchUnavailable(f"AKS search -> {detail}", status=status)
        raise AssertionError("unreachable")                 # pragma: no cover

    def _disable(self, reason: str, *, until: float = 0.0) -> None:
        """``until`` = 0 : pour le reste du balayage (version retirée) ; sinon l'échéance."""

        self.stats["failures"] += 1
        self.disabled_reason = reason
        self.disabled_until = float(until)

    # -- écriture ----------------------------------------------------------------------------
    def flush(self) -> int:
        """Écrit les entrées de ce processus dans le cache, fusionnées avec ce que le fichier
        contient MAINTENANT (la plus récente gagne), les périmées retirées. Écriture atomique.
        Rend le nombre d'entrées écrites ; ne lève jamais (le cache est un accélérateur)."""

        if not self.cache_path or not self._fresh:
            return 0
        try:
            merged = _load_cache(self.cache_path)
            for key, entry in self._fresh.items():
                old = merged.get(key)
                if not isinstance(old, dict) or float(old.get("t", 0)) <= float(entry["t"]):
                    merged[key] = entry
            now = self._now()
            vivantes = {k: v for k, v in merged.items()
                        if isinstance(v, dict) and 0 <= now - float(v.get("t", 0)) < self.ttl_s}
            if len(vivantes) > CACHE_MAX_ENTRIES:
                garde = sorted(vivantes, key=lambda k: float(vivantes[k]["t"]))[-CACHE_MAX_ENTRIES:]
                vivantes = {k: vivantes[k] for k in garde}
            dest = Path(self.cache_path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".aks_search_", dir=str(dest.parent))
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"format": CACHE_FORMAT, "api": API_VERSION, "entries": vivantes}, fh)
            os.replace(tmp, dest)
        except (OSError, ValueError, TypeError):
            return 0
        written = len(self._fresh)
        self._fresh = {}
        return written

    def meta(self) -> dict[str, Any]:
        """Le bloc ``match_meta.json['aks_search']``."""

        return {"active": True, "api_version": API_VERSION, "budget": self.budget,
                "budget_scope": BUDGET_SCOPE,
                "used_before": self.used_before, "used_after": self.used,
                "disabled_reason": self.disabled_reason,
                "disabled_until": self.disabled_until, **dict(self.stats)}


# -- état du balayage (budget + coupure) ----------------------------------------------------
def load_sweep_state(path: str | None, budget: int, *,
                     now: Callable[[], float] = time.time) -> tuple[int, str, float]:
    """``(requêtes déjà dépensées, raison de coupure, échéance)`` du balayage. Fichier absent →
    ``(0, "", 0.0)``. Fichier ILLISIBLE → budget réputé épuisé : un compteur qu'on ne sait plus
    lire ne doit pas rouvrir 1 000 requêtes (le cache reste servi). Une coupure dont l'échéance
    est passée est rendue levée ; ``0.0`` = coupure pour tout le balayage (version retirée)."""

    if not path or not Path(path).exists():
        return 0, "", 0.0
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        used = int(raw["requests_used"])
        reason = str(raw.get("disabled_reason") or "")
        until = float(raw.get("disabled_until") or 0.0)
    except (OSError, ValueError, TypeError, KeyError):
        return max(0, int(budget)), "", 0.0
    if not reason or (until and now() >= until):
        return max(0, used), "", 0.0
    return max(0, used), reason, until


def save_sweep_state(path: str | None, session: AksCatalogSearch) -> None:
    if not path:
        return
    try:
        Path(path).write_text(json.dumps({
            "requests_used": session.used,
            "budget": session.budget,
            "api_version": API_VERSION,
            "disabled_reason": session.disabled_reason,
            "disabled_until": session.disabled_until,
            "written_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }, indent=2), encoding="utf-8")
    except OSError:
        pass
