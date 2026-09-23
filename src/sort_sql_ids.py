"""Le tri SQL **par identifiants** — pour ce qu'un motif d'URL ne sait pas dire (2026-09-22).

Romain, 2026-09-22 : « liste 22, go ». Objectif : sortir de la file Pending les lignes dont
AKS n'a tout simplement pas la page, et les poser en **22 « Pages for creation »**.

**Pourquoi une deuxième voie SQL.** Celle de `src/admin/sort_sql_view.py` route par
``url LIKE '%motif%'`` : elle ne sait exprimer que ce qui est ÉCRIT dans l'URL (une région,
une carte cadeau, un abonnement). « AKS n'a pas de page pour ce jeu » n'est pas dans l'URL —
c'est un VERDICT du matcher, obtenu en sondant le site. Aucun motif ne peut le formuler. On
déplace donc par identifiants : ``WHERE id IN (…)``, la liste venant d'un balayage réel.

**Ce que ça ne fait pas.** Rien n'est exécuté ici, comme pour l'autre voie : ce module rend du
TEXTE que Romain colle dans phpMyAdmin. Il n'importe aucun driver et n'ouvre aucune connexion.

**Les trois gardes, parce qu'un `UPDATE` collé à la main n'a pas de preuve après coup.**

1. *La colonne d'identifiant n'est pas prouvée de notre côté.* Le nom de table et les colonnes
   ``url`` / ``listId`` viennent des requêtes de Romain lui-même ; nous n'avons jamais vu le
   schéma. Le fichier commence donc par un **SELECT de vérification** obligatoire, avec les
   20 premières paires (id, url) attendues en commentaire juste à côté : si les URL rendues
   par la base ne sont pas celles-là, la colonne n'est pas la bonne et **on s'arrête**.
2. *Chaque `UPDATE` est précédé de son `SELECT COUNT(*)`*, avec le compte attendu annoncé. Un
   écart = on s'arrête. C'est la même philosophie que la mesure des motifs : on ne peut pas
   vérifier après, donc on vérifie avant.
3. *Le `WHERE` porte toujours ``AND listId=9``.* Une ligne qu'un autre tri a déjà déplacée ne
   bouge pas une seconde fois. Romain, 2026-09-22 : « j'ai fait un tri où l'on a envoyé
   certaines lignes vers la liste old games / no page ; les offres restantes qui n'ont pas de
   page iront dans page for creation. » Cette garde est exactement ce qui rend les deux tris
   compatibles : ce qui est parti en 27 a quitté la file 9 et ne peut plus être repris ici.
   C'est pourquoi le compte annoncé par lot est un MAXIMUM et non une égalité.

**Et une garde de justesse, en amont :** une ligne n'est proposée au déplacement que si le
sitemap d'AKS (`src/aks_sitemap.py`) confirme qu'AUCUNE page ne porte son slug — ni sous un
gabarit connu, ni sous un gabarit voisin trouvé par préfixe. Mesure du 2026-09-22 sur les
9 719 lignes « no AKS product page found » du balayage de nuit : 872 ont bel et bien une page
(gabarit ``-key``, ``-steam-account``…) et 944 ont un voisin douteux — 1 816 lignes que ce
filtre retient, et qui seraient parties en 22 sans lui.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.aks_sitemap import PAGE_KINDS, SitemapIndex
from src.merchants.registry import merchant_for_store

# Le seul identifiant acceptable : des chiffres. Il est injecté dans du texte SQL.
_ID_RE = re.compile(r"^[0-9]+$")

PENDING_LIST_ID = 9
TABLE = "aksfeeds_offer"
ID_COLUMN = "id"
DEFAULT_CHUNK = 500
VERIFY_SAMPLE = 20

# Les gabarits de page vivent dans `src/aks_sitemap.py` : le matcher en a besoin
# aussi (pass 3), et il ne doit pas importer un outil de tri.

# Les familles de verdict qu'on sait exporter. La clé est ce que Romain tape en ligne de
# commande ; `match` décide, sur le TEXTE du motif de refus écrit par le matcher.
FAMILIES: dict[str, dict[str, Any]] = {
    "no_aks_page": {
        "label": "AKS n'a aucune page pour ce jeu",
        "default_list": 22,
        # La variante console — « no AKS product page found (console) (R45) » — est un AUTRE
        # verdict : le jeu A une page PC, c'est la page de LA CONSOLE qui manque. La déplacer
        # en 22 demanderait la création d'une page qui existe déjà pour une autre plateforme.
        "match": lambda r: ("no AKS product page found" in r) and ("console" not in r),
    },
}


# Les marqueurs de NON-JEU trouvés dans l'export réel du 2026-09-22 par une vérification
# boutique par boutique. Ce ne sont pas des intuitions : chacun a été compté.
#
#   177 bandes dessinées, 71 livres, 4 configurateurs « compose ton pack » — tous chez
#   Fanatical, atteint par le redirecteur d'affiliation Awin. Le CHEMIN de l'URL marchande
#   type le produit (`/comic/`, `/book/`, `/pick-and-mix/`), c'est donc déterministe et
#   gratuit. « Halo: Collateral Damage » est un ROMAN ; sans ce filtre il partait en 22
#   comme un jeu.
#   137 démos : un produit gratuit, aucune clé vendue, aucun prix à comparer.
#   5 titres de remplacement non traduits (« product_title_1294777125 », « 2367709 ») : un
#   titre absent ne prouve rien, son verdict « pas de page » non plus.
#
# Soit 394 lignes sur 4 811 (8,2 %) qu'on ne demandera pas de créer.
NON_GAME_URL = re.compile(r"/(?:comics?|books?|pick-and-mix)/", re.I)
NON_GAME_TITLE = re.compile(r"\bdemos?\b", re.I)
PLACEHOLDER_TITLE = re.compile(r"^(?:product_title_\d+|\d+)$")


def _target_url(url: str) -> str:
    """L'URL du PRODUIT derrière un lien d'affiliation.

    `awin1.com` et `go.loaded.com` ne sont pas des boutiques : ce sont des redirecteurs, et
    la vraie adresse est dans un paramètre de la requête. Sans ce dépliage, le chemin qui
    type le produit (`/comic/`, `/book/`) est invisible."""

    from urllib.parse import parse_qs, unquote, urlparse
    q = parse_qs(urlparse(str(url or "")).query)
    for cle in ("u", "ued", "url", "p"):
        if q.get(cle):
            return unquote(q[cle][0])
    return str(url or "")


def non_game_reason(offer: Mapping[str, Any]) -> str | None:
    """Pourquoi cette ligne n'est pas un jeu à créer — ou None si elle en est un."""

    nom = str(offer.get("name") or "")
    if PLACEHOLDER_TITLE.match(nom.strip()):
        return "titre de remplacement non traduit — le verdict « pas de page » ne prouve rien"
    if NON_GAME_TITLE.search(nom):
        return "démo — produit gratuit, aucune clé vendue, aucun prix à comparer"
    m = NON_GAME_URL.search(_target_url(offer.get("url") or ""))
    if m:
        return f"l'URL marchande type le produit : {m.group(0)} — ce n'est pas un jeu"
    return None


class ExportRefused(RuntimeError):
    """On refuse de produire des requêtes qu'on ne peut pas justifier."""


@dataclass
class Partition:
    """Le tri des lignes d'une famille : celles qu'on déplace, et celles qu'on retient."""

    to_move: list[dict[str, Any]] = field(default_factory=list)
    page_exists: list[dict[str, Any]] = field(default_factory=list)
    doubtful: list[dict[str, Any]] = field(default_factory=list)
    not_a_game: list[dict[str, Any]] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return {"a_deplacer": len(self.to_move), "page_existe": len(self.page_exists),
                "doute_prefixe": len(self.doubtful), "pas_un_jeu": len(self.not_a_game)}


def collect(runs_dir: str | Path, run_prefix: str, family: str) -> list[dict[str, Any]]:
    """Les offres refusées pour ``family`` dans tous les sous-runs de ``run_prefix``.

    Un balayage écrit un dossier par PAGE (``<run>-<marchand>-s<store>-p<n>``) ; on les
    parcourt tous. Dédoublonnage par ``offer_id`` : la même ligne peut être revue d'une page
    à l'autre, et un identifiant répété dans un ``IN (…)`` est au mieux du bruit."""

    regle = FAMILIES.get(family)
    if regle is None:
        raise ExportRefused(
            f"famille {family!r} inconnue — connues : {', '.join(sorted(FAMILIES))}")
    racine = Path(runs_dir)
    vus: dict[str, dict[str, Any]] = {}
    for chemin in sorted(racine.glob(f"{run_prefix}*/skipped.json")):
        try:
            brut = json.loads(chemin.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        lot = brut if isinstance(brut, list) else brut.get("skipped", [])
        for entree in lot:
            if not isinstance(entree, dict):
                continue
            raison = str(entree.get("reason", ""))
            if not regle["match"](raison):
                continue
            offre = entree.get("offer") or {}
            oid = str(offre.get("offer_id") or "").strip()
            if not _ID_RE.match(oid):
                continue                      # un identifiant non numérique n'entre pas en SQL
            vus.setdefault(oid, {
                "offer_id": oid,
                "name": str(offre.get("name") or ""),
                "url": str(offre.get("url") or ""),
                "merchant": str(offre.get("merchant") or ""),
                "store_id": str(offre.get("store_id") or ""),
                "reason": raison,
                "seen_in": chemin.parent.name,
            })
    return [vus[k] for k in sorted(vus, key=int)]


def partition(offers: Iterable[dict[str, Any]], index: SitemapIndex,
              slug_candidates, kinds: Iterable[str] = PAGE_KINDS,
              name_variants=None) -> Partition:
    """Sépare ce qu'on peut déplacer de ce que le sitemap retient.

    ``slug_candidates`` est injecté (c'est ``matcher.build_slug_candidates``) pour que ce
    module ne dépende pas du matcher : ses tests restent rapides et sans effet de bord.

    ``name_variants(offre) -> [noms]`` rend les noms sous lesquels chercher la page. REVUE DE
    ROMAIN (2026-09-23) : l'export ne cherchait que le titre BRUT, alors que le matcher
    cherche le titre NETTOYÉ par la grammaire du marchand (« Zombies Invasion (PC) Steam
    Gift- EU » → « Zombies Invasion (PC) »). Le CLI passe donc le titre brut ET le nom de
    résolution du matcher (`matcher.resolution_name`) : on retient la ligne dès que L'UN des
    deux trouve une page. C'est le sens prudent — chaque nom de plus ne peut qu'empêcher un
    déplacement, jamais en provoquer un."""

    kinds = tuple(kinds)
    out = Partition()
    for offre in offers:
        pourquoi = non_game_reason(offre)
        if pourquoi:
            out.not_a_game.append({**offre, "pas_un_jeu": pourquoi})
            continue
        noms = name_variants(offre) if name_variants else [offre.get("name") or ""]
        cands: list[str] = []
        for nom in noms:
            for c in slug_candidates(nom or ""):
                if c not in cands:
                    cands.append(c)
        gabarits: list[str] = []
        voisin = None
        for c in cands:
            trouves = index.kinds_for(c, kinds)
            if trouves:
                gabarits = [f"{c}-{k}" for k in trouves]
                break
            # …et la même question en aplatissant la ponctuation des deux côtés
            plat = next((index.flat_page(f"{c}-{k}") for k in kinds
                         if index.flat_page(f"{c}-{k}")), None)
            if plat:
                gabarits = [plat]
                break
        if gabarits:
            out.page_exists.append({**offre, "pages_aks": gabarits})
            continue
        for c in cands:
            voisin = index.any_page_starting_with(c)
            if voisin:
                break
        if voisin:
            out.doubtful.append({**offre, "page_voisine": voisin})
            continue
        out.to_move.append(offre)
    return out


def _chunks(ids: list[str], taille: int) -> list[list[str]]:
    return [ids[i:i + taille] for i in range(0, len(ids), taille)]


def render_sql(offers: list[dict[str, Any]], target_list: int, *,
               chunk: int = DEFAULT_CHUNK, sample: int = VERIFY_SAMPLE,
               header: str = "") -> str:
    """Le fichier .sql : vérification d'abord, puis les lots, chacun compté avant d'écrire."""

    cible = int(target_list)
    if cible == PENDING_LIST_ID:
        raise ExportRefused(
            f"liste cible {cible} = la file Pending elle-même — un déplacement vers la liste "
            "d'origine ne veut rien dire")
    if not offers:
        raise ExportRefused("aucune ligne à déplacer — rien à écrire")
    ids = [o["offer_id"] for o in offers]
    mauvais = [i for i in ids if not _ID_RE.match(str(i))]
    if mauvais:
        raise ExportRefused(f"identifiant non numérique refusé : {mauvais[:3]}")

    lots = _chunks(ids, max(1, int(chunk)))
    lignes: list[str] = []
    a = lignes.append
    a("-- " + "=" * 76)
    a("-- Tri par identifiants — généré par scripts/17_sort_sql_ids.py")
    if header:
        for l in header.splitlines():
            a("-- " + l)
    a("--")
    a(f"-- {len(ids)} ligne(s) -> liste {cible}, en {len(lots)} lot(s) de {chunk} maximum.")
    a("--")
    a("-- LIRE AVANT DE COLLER :")
    a("--   1. L'ÉTAPE 0 est obligatoire. Nous n'avons jamais vu le schéma de la base : le")
    a(f"--      nom de la colonne d'identifiant ({ID_COLUMN}) est une HYPOTHÈSE. L'étape 0 la")
    a("--      vérifie en affichant des URL qu'on connaît déjà. Si elles ne correspondent")
    a("--      pas, ou si la requête échoue : ARRÊTER, ne rien écrire, me le dire.")
    a("--   2. Chaque lot est précédé d'un COUNT. Le nombre annoncé est un MAXIMUM, pas une")
    a("--      égalité : Romain a déjà trié une partie de ces lignes vers la 27 « Old games /")
    a("--      No pages » (2026-09-22), et celles-là ont quitté la file Pending. Un compte")
    a("--      INFÉRIEUR est donc normal — c'est le tri déjà fait. Un compte SUPÉRIEUR au lot")
    a("--      est impossible : s'il arrive, arrêter.")
    a("--   3. Chaque requête porte AND `listId`=9 : une ligne déjà triée ailleurs ne bouge")
    a("--      pas une seconde fois.")
    a("-- " + "=" * 76)
    a("")
    a("-- ÉTAPE 0 — VÉRIFICATION DE LA COLONNE (à lancer seul, et à lire)")
    echantillon = offers[:max(1, int(sample))]
    a(f"SELECT `{ID_COLUMN}`, `url` FROM `{TABLE}`")
    a(f"  WHERE `{ID_COLUMN}` IN ({', '.join(o['offer_id'] for o in echantillon)})")
    a(f"    AND `listId`={PENDING_LIST_ID};")
    a("")
    a("-- Les URL attendues pour ces identifiants, vues par notre balayage :")
    for o in echantillon:
        a(f"--   {o['offer_id']}  {o['url'][:110]}")
    a("")
    for i, lot in enumerate(lots, 1):
        dedans = ", ".join(lot)
        a(f"-- ---- lot {i}/{len(lots)} — {len(lot)} ligne(s) ----")
        a(f"-- attendu : au plus {len(lot)} (moins si ces lignes sont déjà triées ailleurs)")
        a(f"SELECT COUNT(*) FROM `{TABLE}` WHERE `{ID_COLUMN}` IN ({dedans}) "
          f"AND `listId`={PENDING_LIST_ID};")
        a(f"UPDATE `{TABLE}` SET `listId`={cible} WHERE `{ID_COLUMN}` IN ({dedans}) "
          f"AND `listId`={PENDING_LIST_ID};")
        a("")
    return "\n".join(lignes) + "\n"

# --- deuxième source : un scan de TRI tous-magasins -------------------------------------
# Romain, 2026-09-22 : « lance le même export sur les autres marchands ». Les 44 boutiques
# hors liste blanche n'ont jamais été balayées — il n'existe pour elles aucun `skipped.json`.
# Mais le scan de tri tous-magasins (`scripts/08_sort_plan.py`) a déjà fait passer TOUTES les
# lignes de la file par notre routeur, marchand par marchand, avec leurs configurations
# (R53b Wyrel, GameBoost, allyouplay…). Il nous donne donc la même information de départ :
# ce que le routeur tient pour un VRAI JEU À CRÉER.
#
# Ce qu'il ne donne PAS, et c'est la différence avec un balayage : la page AKS n'a pas été
# sondée. C'est précisément ce que l'index sitemap remplace — il répond hors ligne à « cette
# page existe-t-elle ? ». Le verdict rendu ici est donc le même que celui d'un balayage,
# obtenu sans une requête.

CANDIDATE = "__candidat__"


def domain_of(url: str) -> str:
    from urllib.parse import urlparse
    h = (urlparse(str(url or "")).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def collect_from_sort_scan(run_dir: str | Path, *, exclude_stores: Iterable[str] = (),
                           only_domains: Iterable[str] = ()) -> list[dict[str, Any]]:
    """Les lignes qu'un scan de tri tient pour de VRAIS JEUX À CRÉER.

    Trois seaux dans un plan de tri : ``by_list`` (le routeur les envoie ailleurs),
    ``unrouted`` (il les garde en attente avec une raison — console, bundle, région…), et le
    reste, qui est ce qu'il tiendrait pour un jeu à créer. C'est ce reste qu'on prend : une
    ligne déjà réclamée par une autre liste n'a rien à faire en 22.

    ``exclude_stores`` écarte des marchands par **store_id**, et c'est délibéré : le
    ``store_id`` EST la clé de la liste blanche, alors que le domaine se devine. Première
    version de ce code, qui filtrait par domaine : deux marchands sur seize étaient mal
    orthographiés — GamersOutlet vit sur ``gamers-outlet.net`` (avec un tiret) et Allyouplay
    n'a pas de domaine à lui du tout, ses liens passent par ``anandadigitalbv.sjv.io``. Leurs
    lignes tombaient donc dans l'export « des autres », en double. Le ``store_id`` ne se
    trompe pas.

    ``only_domains`` reste, lui, un confort de lecture pour isoler une boutique à la main."""

    d = Path(run_dir)
    plan = json.loads((d / "sort_plan.json").read_text(encoding="utf-8"))
    brut = json.loads((d / "offers.json").read_text(encoding="utf-8"))
    rows = brut if isinstance(brut, list) else brut.get("offers", [])

    reclamees: set[str] = set()
    for r in plan.get("unrouted") or []:
        u = str(r.get("url") or "")
        if u:
            reclamees.add(u)
    for _, groupe in (plan.get("by_list") or {}).items():
        for r in groupe.get("offers") or []:
            u = str(r.get("url") or "")
            if u:
                reclamees.add(u)

    exclus = {str(x).strip() for x in exclude_stores}
    seuls = {str(x).lower() for x in only_domains}
    vus: dict[str, dict[str, Any]] = {}
    for r in rows:
        url = str(r.get("url") or "")
        if not url or url in reclamees:
            continue
        dom = domain_of(url)
        if exclus and str(r.get("store_id") or "").strip() in exclus:
            continue
        if seuls and dom not in seuls:
            continue
        oid = str(r.get("offer_id") or "").strip()
        if not _ID_RE.match(oid):
            continue
        store = str(r.get("store_id") or "").strip()
        vus.setdefault(oid, {
            "offer_id": oid,
            "name": str(r.get("name") or ""),
            "url": url,
            # Le nom CANONIQUE quand le registre connaît la boutique (Wyrel, GOG…) : c'est lui
            # qui donne accès à la grammaire du marchand, donc au nettoyage du titre. Le
            # domaine seul ne la retrouve pas.
            "merchant": merchant_for_store(store) or dom,
            "store_id": store,
            "domain": dom,
            "reason": CANDIDATE,
            "seen_in": d.name,
        })
    return [vus[k] for k in sorted(vus, key=int)]
