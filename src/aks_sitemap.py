"""L'index des pages produit d'AKS, lu dans son propre sitemap (2026-09-22).

Romain, 2026-09-22 : « liste 22, go » — déplacer vers « Pages for creation » les lignes dont
AKS n'a pas la page. Avant de déplacer 8 817 lignes à la main dans phpMyAdmin, il faut PROUVER
que la page n'existe pas. Ce module est cette preuve.

**Pourquoi il existe.** Le seul moyen que le matcher avait de vérifier une page introuvable
était la recherche interne d'AKS (R30). Mesurée le 2026-09-22 depuis les deux VPS, elle répond
``HTTP 200`` avec ``Content-Length: 0`` — un corps VIDE, quel que soit le délai d'attente. Elle
est morte. Le disjoncteur R30 était donc ouvert sur 253 des 259 pages du balayage de nuit, et
9 719 lignes en sont ressorties « no AKS product page found » sans second regard.

Le sitemap d'AKS, lui, répond : ``sitemap_index.xml`` pointe 55 fichiers ``page-sitemap*.xml``
qui portent **213 404 pages produit**, téléchargées en quatre minutes. C'est la liste complète
et faisant autorité de ce qui existe. Confronté à elle, le verdict du balayage tient à 90,7 % ;
les 9,3 % restants sont des pages réelles sous un gabarit qu'on ne sonde pas (``-key`` 404
lignes, ``-steam-account`` 246), et ceux-là ne doivent surtout PAS être déplacés.

**Ce que ce module ne fait pas.** Il ne décide rien et ne touche pas au matcher. Il répond à
une seule question : « l'URL ``buy-<slug>-<gabarit>-compare-prices/`` est-elle dans le sitemap
d'AKS ? » — et, depuis le 2026-09-24, la même pour la forme ANCIENNE
``compare-and-buy-cd-key-for-digital-download-<slug>/`` (liste à part, ``has_legacy``). Un index
absent ou périmé répond « je ne sais pas » (``None``), jamais « non » — l'appelant reste
fail-closed. C'est le matcher qui s'en sert pour ne sonder que ce qui existe (sitemap d'abord,
``matcher.sitemap_first_probes``).

**Limite, dite franchement.** Le sitemap est une photo. Une page créée depuis la photo est
absente de l'index, et une page supprimée depuis y figure encore. L'index prouve donc
l'EXISTENCE (on a vu l'URL publiée), jamais l'ABSENCE définitive ; c'est pour ça que l'export
de tri l'utilise pour EXCLURE des lignes, et qu'il exige un index frais.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

SITEMAP_INDEX_URL = "https://www.allkeyshop.com/blog/sitemap_index.xml"
# `robots.txt` annonce « Crawl-delay: 0.5 » — on le respecte, c'est leur site.
CRAWL_DELAY_S = 0.5
# L'UA de nos sondes. Mémoire 2026-09-11 : une sonde ad-hoc avec l'UA navigateur a fait bannir
# l'IP du VPS pendant des heures. Jamais autre chose ici.
SITEMAP_UA = "AKS/Staff"
DEFAULT_PATH = "state/aks_sitemap.json"
DEFAULT_TTL_DAYS = 7

_LOC_RE = re.compile(rb"<loc>([^<]+)</loc>")
# La grammaire des pages produit : buy-<slug>-<gabarit>-compare-prices/
_PAGE_RE = re.compile(r"/blog/buy-(.+?)-compare-prices/?$")
# …et celle des pages ANCIENNES (≈ 2021), que le matcher sonde en passe 2 depuis le 2026-09-10 :
# compare-and-buy-cd-key-for-digital-download-<slug>/. Elles sont bien dans les page-sitemaps
# (72 dans page-sitemap.xml, 16 dans page-sitemap30.xml, relevé du 2026-09-24) mais la
# première version de ce module ne les gardait pas. Or ce sont des jeux très vendus —
# Battlefield 3, Far Cry 3, Borderlands 2, Minecraft : 10 résolutions sur ~9 000 depuis le
# 15/09. Elles vivent dans une liste À PART (`legacy`) : leur slug n'a pas de gabarit, le
# mélanger aux `entries` fausserait `kinds_for`, `flat_page` et le préfixe de l'export.
_LEGACY_RE = re.compile(r"/blog/compare-and-buy-cd-key-for-digital-download-(.+?)/?$")
_FLAT_RE = re.compile(r"[^a-z0-9]+")


def _flatten(slug: str) -> str:
    """Le slug réduit à ses lettres et ses chiffres : « re-birth3 » et « rebirth3 »
    deviennent la même clé, « 1-000-doors » et « 1000-doors » aussi."""

    return _FLAT_RE.sub("", str(slug or "").lower())


# Les gabarits de page qu'on sait nommer. L'index en couvre 96 % ; le reste est rattrapé par
# la recherche par préfixe (voir `SitemapIndex.any_page_starting_with`).
PAGE_KINDS: tuple[str, ...] = (
    "cd-key", "key", "game-code", "download-code",
    "steam-account", "windows-account", "epic-account", "origin-account", "ea-account",
    "uplay-account", "ubisoft-account", "battlenet-account", "rockstar-account",
    "gog-account", "psn-account", "xbox-account", "nintendo-account",
    "ps4", "ps5", "xbox-one", "xbox-series", "nintendo-switch", "nintendo-switch-2",
    "ps4-account", "ps5-account", "xbox-one-account", "xbox-series-account",
    "ps4-game-code", "ps5-game-code", "xbox-one-key", "xbox-series-key",
    "xbox-360-code", "nintendo-3ds", "wii-u", "gift-card",
)



class SitemapUnavailable(RuntimeError):
    """Le sitemap n'a pas pu être lu — on ne prétend pas connaître le catalogue."""


def _fetch(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": SITEMAP_UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def refresh(dest: str | Path, *, fetch: Callable[[str], bytes] = _fetch,
            sleep: Callable[[float], None] = time.sleep,
            now: Callable[[], float] = time.time,
            on_progress: Callable[[str, int, int], None] | None = None) -> dict[str, Any]:
    """Télécharge le sitemap et écrit l'index dans ``dest``.

    Rend le petit résumé de ce qui a été lu. Un sous-sitemap illisible est SIGNALÉ et sauté :
    un index partiel est honnête tant qu'il le dit (``incomplete``), et l'export de tri refuse
    un index incomplet — on ne déplace pas des lignes sur la foi d'un catalogue troué."""

    index = fetch(SITEMAP_INDEX_URL)
    try:
        sous = _locs(index, racine="sitemapindex")
    except ValueError as exc:
        raise SitemapUnavailable(f"{SITEMAP_INDEX_URL} illisible : {exc}") from None
    cibles = [u for u in sous if "page-sitemap" in u]
    if not cibles:
        raise SitemapUnavailable(
            f"{SITEMAP_INDEX_URL} ne liste aucun 'page-sitemap' — grammaire changée ?")

    pages: set[str] = set()
    anciennes: set[str] = set()
    echecs: list[str] = []
    for i, url in enumerate(cibles, 1):
        try:
            corps = fetch(url)
            locs = _locs(corps, racine="urlset")
        except Exception as exc:                       # noqa: BLE001 — on note et on continue
            echecs.append(f"{url}: {exc}")
            continue
        for loc in locs:
            m = _PAGE_RE.search(loc)
            if m:
                pages.add(m.group(1))
                continue
            m = _LEGACY_RE.search(loc)
            if m:
                anciennes.add(m.group(1).lower())
        if on_progress:
            on_progress(url, i, len(cibles))
        sleep(CRAWL_DELAY_S)

    resume = {
        "fetched_at": _iso(now()),
        "source": SITEMAP_INDEX_URL,
        "sitemaps": len(cibles),
        "sitemaps_failed": echecs,
        "incomplete": bool(echecs),
        "pages": len(pages),
        "legacy_pages": len(anciennes),
    }
    chemin = Path(dest)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    # `legacy_indexed` dit que CE fichier a cherché les pages anciennes : un fichier écrit
    # avant le 2026-09-24 ne l'a pas fait, et son silence ne veut pas dire « aucune ».
    # ÉCRITURE ATOMIQUE (2026-09-24, relevé automatique au lancement des balayages) : le
    # matcher relit ce fichier à CHAQUE page d'un balayage qui tourne peut-être sur la même
    # machine. Écrit en place, une lecture tombant pendant l'écriture verrait un JSON tronqué.
    # Même convention que `recap.json` : un fichier voisin, puis `os.replace`.
    tmp = chemin.with_name(chemin.name + ".tmp")
    tmp.write_text(json.dumps({**resume, "legacy_indexed": True,
                               "legacy": sorted(anciennes), "entries": sorted(pages)},
                              ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, chemin)
    return resume


# Âge au-delà duquel un balayage relève l'index à son lancement. Moins de 24 h pour qu'un
# balayage lancé chaque soir à la même heure le relève toujours, même avec quelques minutes
# d'avance sur la veille.
AUTO_REFRESH_MAX_AGE_HOURS = 20.0


def ensure_fresh(dest: str | Path, *, max_age_hours: float = AUTO_REFRESH_MAX_AGE_HOURS,
                 fetch: Callable[[str], bytes] = _fetch,
                 sleep: Callable[[float], None] = time.sleep,
                 now: Callable[[], float] = time.time) -> dict[str, Any]:
    """Relève l'index s'il en a besoin, au lancement d'un balayage. Ne lève JAMAIS.

    Romain, 2026-09-24 : « oui pour le refresh auto ». Sans relevé, l'index expire au bout de
    `DEFAULT_TTL_DAYS` et le matching « sitemap d'abord » se coupe tout seul ; et une page
    qu'AKS publie entre deux relevés reste invisible jusqu'au suivant. Un relevé coûte une
    minute ou deux (≈ 56 fichiers, délai de crawl respecté, UA `AKS/Staff`).

    Relève quand l'index est absent, troué, sans les pages anciennes, ou plus vieux que
    ``max_age_hours``. Un relevé qui échoue ou revient TROUÉ ne remplace pas un index complet
    encore valable : on garde l'ancien et on le dit. Rend un résumé pour le recap du balayage —
    jamais une exception, parce qu'un sitemap injoignable n'est pas une raison d'arrêter une
    saisie : le matcher retombe alors sur les sondes d'avant, tout seul."""

    chemin = Path(dest)
    ancien = SitemapIndex.load(chemin)
    raison = None
    if ancien is None:
        raison = "absent"
    elif ancien.incomplete:
        raison = "incomplet"
    elif not ancien.legacy_indexed:
        raison = "sans les pages anciennes"
    else:
        age = ancien.age_days(now())
        if age is None or age * 24 > max_age_hours:
            raison = ("âge illisible" if age is None
                      else f"relevé il y a {age * 24:.0f} h (> {max_age_hours:.0f} h)")
    if raison is None:
        return {"refreshed": False, "reason": "frais", "fetched_at": ancien.fetched_at}

    ancien_valable = (ancien is not None and not ancien.incomplete
                      and ancien.fresh(now=now()))
    brouillon = chemin.with_name(chemin.name + ".releve")
    try:
        resume = refresh(brouillon, fetch=fetch, sleep=sleep, now=now)
    except Exception as exc:                            # noqa: BLE001 — jamais une halte
        brouillon.unlink(missing_ok=True)
        return {"refreshed": False, "reason": raison, "error": f"{type(exc).__name__}: {exc}",
                "fetched_at": ancien.fetched_at if ancien else None}
    if resume.get("incomplete") and ancien_valable:
        brouillon.unlink(missing_ok=True)
        return {"refreshed": False, "reason": raison,
                "error": f"relevé troué ({len(resume.get('sitemaps_failed') or [])} fichier(s) "
                         "illisible(s)) — l'index complet précédent est gardé",
                "fetched_at": ancien.fetched_at}
    os.replace(brouillon, chemin)
    return {"refreshed": True, "reason": raison, **resume}


def _locs(corps: bytes, *, racine: str) -> list[str]:
    """Les ``<loc>`` d'un document sitemap, après avoir vérifié que c'EN EST un.

    REVUE DE ROMAIN (2026-09-23) : « un sous-sitemap renvoyant du HTML ou un corps vide ne
    déclenche aucune erreur. Deux fichiers, dont un invalide, donnent incomplete=False.
    L'export SQL peut alors classer des pages existantes comme absentes. » Exact : la
    première version cherchait les ``<loc>`` à l'expression régulière, et une page d'erreur
    HTML, un corps vide ou un XML tronqué n'en contiennent simplement… aucun. Le sous-sitemap
    passait pour lu, ses milliers de pages manquaient, et l'index se disait complet. C'est
    précisément le cas où l'export déplacerait en 22 des lignes dont la page existe.

    Trois exigences, sans quoi le document est un ÉCHEC (et l'index devient incomplet) :
    un XML qui se lit, la bonne racine (``urlset`` pour une page, ``sitemapindex`` pour
    l'index), et au moins un ``<loc>``. Un sitemap sans aucune URL n'est pas « une page
    vide », c'est une réponse qu'on ne sait pas interpréter."""

    import xml.etree.ElementTree as ET
    if not corps or not corps.strip():
        raise ValueError("corps vide")
    try:
        arbre = ET.fromstring(corps)
    except ET.ParseError as exc:
        raise ValueError(f"XML illisible ({exc})") from None
    nom_racine = arbre.tag.rsplit("}", 1)[-1]
    if nom_racine != racine:
        raise ValueError(f"racine <{nom_racine}> au lieu de <{racine}>")
    locs = [(el.text or "").strip() for el in arbre.iter() if el.tag.rsplit("}", 1)[-1] == "loc"]
    locs = [l for l in locs if l]
    if not locs:
        raise ValueError(f"<{racine}> sans aucun <loc>")
    return locs


def _iso(epoch: float) -> str:
    import datetime
    return datetime.datetime.fromtimestamp(
        epoch, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class SitemapIndex:
    """Les pages produit d'AKS, telles que le sitemap les publiait à ``fetched_at``."""

    entries: frozenset[str]
    fetched_at: str
    incomplete: bool
    source: str = SITEMAP_INDEX_URL
    # Les pages anciennes `compare-and-buy-cd-key-for-digital-download-<slug>/`, par slug nu.
    # `legacy_indexed` est False pour un fichier d'avant le 2026-09-24 : il ne les a pas
    # cherchées, donc « absente de `legacy` » n'y prouve RIEN (voir `has_legacy`).
    legacy: frozenset[str] = frozenset()
    legacy_indexed: bool = False

    @classmethod
    def load(cls, path: str | Path = DEFAULT_PATH) -> "SitemapIndex | None":
        """L'index, ou **None** s'il est absent ou illisible — jamais un index vide.

        Un index vide et un index absent se ressemblent à l'usage mais disent le contraire :
        « AKS n'a aucune page » contre « je ne sais pas ». On ne rend que le second."""

        try:
            brut = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        entrees = brut.get("entries")
        if not isinstance(entrees, list) or not entrees:
            return None
        anciennes = brut.get("legacy")
        indexees = brut.get("legacy_indexed") is True and isinstance(anciennes, list)
        return cls(entries=frozenset(str(e) for e in entrees),
                   fetched_at=str(brut.get("fetched_at") or ""),
                   incomplete=bool(brut.get("incomplete")),
                   source=str(brut.get("source") or SITEMAP_INDEX_URL),
                   legacy=frozenset(str(e).lower() for e in anciennes) if indexees
                   else frozenset(),
                   legacy_indexed=indexees)

    def age_days(self, now: float | None = None) -> float | None:
        import datetime
        try:
            t = datetime.datetime.strptime(self.fetched_at, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            return None
        t = t.replace(tzinfo=datetime.timezone.utc)
        maintenant = (datetime.datetime.fromtimestamp(now, datetime.timezone.utc)
                      if now is not None else datetime.datetime.now(datetime.timezone.utc))
        return (maintenant - t).total_seconds() / 86400.0

    def fresh(self, ttl_days: int = DEFAULT_TTL_DAYS, now: float | None = None) -> bool:
        age = self.age_days(now)
        return age is not None and age <= ttl_days

    def has_page(self, full_slug: str) -> bool:
        """``hades-cd-key`` → la page existe-t-elle ? C'est le segment ENTIER entre
        ``buy-`` et ``-compare-prices``, gabarit compris — jamais le slug nu."""

        return str(full_slug or "").strip().lower() in self.entries

    def has_legacy(self, slug: str) -> bool | None:
        """La page ANCIENNE ``compare-and-buy-cd-key-for-digital-download-<slug>/`` existe-t-elle ?

        Trois réponses, pas deux : True (publiée), False (l'index l'a cherchée et ne l'a pas),
        **None** (l'index date d'avant le 2026-09-24 et ne les a jamais cherchées — « je ne
        sais pas », que l'appelant traite comme tel)."""

        if not self.legacy_indexed:
            return None
        return str(slug or "").strip().lower() in self.legacy

    def kinds_for(self, slug: str, kinds: Iterable[str]) -> list[str]:
        """Parmi ``kinds``, ceux sous lesquels ``slug`` a une page publiée."""

        s = str(slug or "").strip().lower()
        return [k for k in kinds if s and f"{s}-{k}" in self.entries]

    def flat_page(self, full_slug: str) -> str | None:
        """La page dont le slug, RÉDUIT à ses lettres et chiffres, est le même. Ou None.

        REVUE PAR AGENTS (2026-09-22). Une vérification boutique par boutique de l'export
        vers la liste 22 a trouvé des pages qui existent et que nous déclarions absentes :
        « Hyperdimension Neptunia Re;Birth3 » cherche ``…re-birth3…`` quand AKS écrit
        ``…rebirth3…``, « House of 1,000 Doors » cherche ``…1-000-doors…`` quand AKS écrit
        ``…1000-doors…``, « MotoGP24 » contre ``motogp-24``. La ponctuation et le groupement
        des chiffres divergent, pas le produit. En aplatissant les deux côtés, 140 lignes de
        l'export (2,9 %) retrouvent leur page.

        Pourquoi c'est sûr des deux côtés : pour l'EXPORT, une correspondance à tort ne fait
        que RETENIR une ligne (on ne déplace pas) ; pour le MATCHER, l'URL rendue est ensuite
        réellement téléchargée et passe les gardes de nom R01 habituelles, qui refusent un
        homonyme. On ne saute aucune vérification, on propose seulement une URL de plus."""

        cle = _flatten(full_slug)
        return self._flat.get(cle) if cle else None

    @property
    def _flat(self) -> dict[str, str]:
        cache = getattr(self, "_flat_cache", None)
        if cache is None:
            cache = {}
            for e in self.entries:
                cache.setdefault(_flatten(e), e)
            object.__setattr__(self, "_flat_cache", cache)
        return cache

    def any_page_starting_with(self, slug: str) -> str | None:
        """La PREMIÈRE page dont le slug commence par ``<slug>-``, ou None.

        Pourquoi en plus de :meth:`kinds_for` : la liste des gabarits qu'on connaît couvre
        96 % de l'index, pas 100 % (``xbox-360-code``, ``ps5-account``, ``nintendo-3ds``,
        ``wii-u``, ``download-code``… existent aussi). Avant de déplacer des milliers de
        lignes à la main, une correspondance par PRÉFIXE attrape les gabarits qu'on n'a pas
        énumérés. Elle attrape aussi des voisins homonymes (« hades » préfixe « hades-2 ») :
        c'est un excès de prudence ASSUMÉ, il laisse la ligne en attente au lieu de la
        déplacer — et l'export les compte à part pour qu'on voie ce que ça coûte.

        Recherche dichotomique sur la liste triée : ``O(log n)`` sur 213 000 entrées."""

        import bisect
        s = str(slug or "").strip().lower()
        if not s:
            return None
        pref = s + "-"
        i = bisect.bisect_left(self._sorted, pref)
        if i < len(self._sorted) and self._sorted[i].startswith(pref):
            return self._sorted[i]
        return None

    @property
    def _sorted(self) -> tuple[str, ...]:
        cache = getattr(self, "_sorted_cache", None)
        if cache is None:
            cache = tuple(sorted(self.entries))
            object.__setattr__(self, "_sorted_cache", cache)
        return cache
