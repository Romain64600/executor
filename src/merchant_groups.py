"""Les groupes de marchands — un par VPS, pour balayer en parallèle.

Romain, 2026-09-21 : « je voudrais qu'on puisse lancer des marchands aussi par groupe. Donc
là, je voudrais que tu divises nos marchands en deux groupes, vu qu'on a deux VPS. »

**Pourquoi deux groupes et pas autre chose.** La contrainte n'est pas le réseau ni AKS : c'est
qu'un balayage tient **un onglet de navigateur par machine** (le verrou `state/browser.lock`,
OP1). Deux machines = deux balayages simultanés, donc deux groupes.

**Comment ils sont équilibrés.** Sur la charge RÉELLE en attente, mesurée le 2026-09-21 par le
scan tous-magasins (20 185 lignes pending, liste 9) :

    GameSeal 5522 · Gamivo 2960 · Eneba 2612 · Kinguin 2146 · G2A 2137 · CJS 1859
    GameBoost 885 · Gamerall 569 · Driffle 349 · Electronicfirst 316 · Instant Gaming 264
    Allyouplay 206 · MMOGA 189 · K4G 162 · GamersOutlet 9

→ groupe **A** 9 355 lignes, groupe **B** 10 830. GameSeal, à lui seul 27 % du travail, est
isolé avec des petits ; les trois suivants (Gamivo, Eneba, Kinguin) sont répartis pour que les
deux machines finissent à peu près ensemble.

**La limite de cet équilibrage, dite franchement.** Le temps d'un balayage n'est pas
proportionnel aux lignes : une page coûte ~2,5 min à extraire et matcher, puis **~1 min par
offre créée**. Une page dense (80 créations) prend une heure et demie, une page vide dix
minutes. Les taux de création varient du simple au trentuple selon le marchand (GameSeal ~21 %,
Gamivo ~5 %, CJS 0,6 %). Ces groupes sont donc un point de départ raisonnable, pas un optimum
démontré — et c'est exactement pourquoi ils vivent dans une liste éditable plutôt que dans du
code : après un tour complet, on les rééquilibre sur les durées observées.

**Difmark n'est dans aucun groupe.** Sa file Pending est VIDE : ses lignes vivent dans la liste
*account* (30), que le balayage ne sait pas lire (il lit la 9). L'y mettre ferait une passe à
vide. Il se saisit à la main, avec `02_extract_feed --list 30` puis `05_submit --list 30`.
"""

from __future__ import annotations

from src.admin.auto_merchants import AUTO_MERCHANTS

# Les lignes en attente au 2026-09-21, pour mémoire (elles bougent : à re-mesurer avant de
# rééquilibrer, avec un scan tous-magasins).
PENDING_2026_09_21 = {
    "GameSeal": 5522, "Gamivo": 2960, "Eneba": 2612, "Kinguin": 2146, "G2A": 2137,
    "CJS-CDKeys": 1859, "GameBoost": 885, "Gamerall": 569, "Driffle": 349,
    "Electronicfirst": 316, "Instant Gaming": 264, "Allyouplay": 206, "MMOGA": 189,
    "K4G": 162, "GamersOutlet": 9, "Difmark": 0,
}

# Hors groupes, avec la raison — un marchand absent des deux groupes n'est PAS un oubli.
EXCLUDED: dict[str, str] = {
    "Difmark": ("file Pending vide — ses lignes sont dans la liste account (30), que le "
                "balayage ne lit pas ; saisie à la main avec --list 30"),
}

GROUPS: dict[str, tuple[str, ...]] = {
    # ~9 355 lignes : le poids lourd isolé, entouré de petites files.
    "A": ("GameSeal", "G2A", "GameBoost", "Driffle", "Instant Gaming", "MMOGA", "GamersOutlet"),
    # ~10 830 lignes : trois files moyennes et le reste.
    "B": ("Gamivo", "Eneba", "Kinguin", "CJS-CDKeys", "Gamerall", "Electronicfirst",
          "Allyouplay", "K4G"),
}


def split(n: int, *, charge: dict[str, int] | None = None) -> list[list[str]]:
    """Répartit les marchands de la liste blanche en ``n`` groupes équilibrés.

    Romain, 2026-09-21 : « je compte prendre un troisième et quatrième VPS pour paralléliser
    plus. » Les groupes ne sont donc pas gravés à deux : cette fonction en produit autant
    qu'il y a de machines, sur la même mesure de charge.

    Méthode : **LPT** (longest processing time first) — on pose le plus gros marchand sur la
    machine la moins chargée, puis le suivant, etc. C'est l'heuristique classique du
    problème des machines parallèles ; elle ne promet pas l'optimum mais s'en approche, et
    surtout elle est DÉTERMINISTE (même entrée, même sortie), donc un groupe est
    reproductible d'un lancement à l'autre. Les marchands de `EXCLUDED` en sont écartés.

    Sa limite est celle de la mesure : la charge est comptée en LIGNES en attente, alors que
    le temps réel dépend surtout du nombre de CRÉATIONS (~1 min chacune). À re-mesurer sur
    les durées observées après un tour complet."""

    n = max(1, int(n))
    poids = charge or PENDING_2026_09_21
    candidats = [nom for nom, _ in AUTO_MERCHANTS if nom not in EXCLUDED]
    # tri décroissant par charge, puis par nom : déterministe même à charges égales
    candidats.sort(key=lambda nom: (-poids.get(nom, 0), nom))
    groupes: list[list[str]] = [[] for _ in range(n)]
    totaux = [0] * n
    for nom in candidats:
        i = totaux.index(min(totaux))
        groupes[i].append(nom)
        totaux[i] += poids.get(nom, 0)
    return groupes


def targets_for(spec: str) -> list[tuple[str, str]]:
    """``"A"`` → le groupe figé A ; ``"2/4"`` → le 2e de 4 groupes calculés à la volée.

    La forme ``i/n`` sert les machines qu'on ajoute : avec un 3e et un 4e VPS, chacun lance
    ``--group 1/4``, ``2/4``, ``3/4``, ``4/4`` sans qu'on ait à réécrire les groupes."""

    texte = (spec or "").strip()
    if "/" in texte:
        gauche, droite = texte.split("/", 1)
        try:
            i, n = int(gauche), int(droite)
        except ValueError:
            raise KeyError(f"groupe {spec!r} illisible — attendu 'A' ou 'i/n' (ex. 2/4)") from None
        if not 1 <= i <= n:
            raise KeyError(f"groupe {spec!r} hors bornes — i doit être entre 1 et n")
        index = _by_name()
        return [index[nom.casefold()] for nom in split(n)[i - 1]]
    return group_targets(texte)


def _by_name() -> dict[str, tuple[str, str]]:
    return {nom.casefold(): (nom, store) for nom, store in AUTO_MERCHANTS}


def group_names() -> list[str]:
    return sorted(GROUPS)


def group_targets(name: str) -> list[tuple[str, str]]:
    """Les cibles ``(marchand, store_id)`` d'un groupe, dans l'ordre déclaré.

    Fail-closed : un groupe inconnu ou un membre absent de la liste blanche lève — on ne
    lance pas un balayage sur une cible approximative."""

    key = (name or "").strip().upper()
    if key not in GROUPS:
        raise KeyError(f"groupe {name!r} inconnu — groupes connus : {', '.join(group_names())}")
    index = _by_name()
    cibles: list[tuple[str, str]] = []
    for membre in GROUPS[key]:
        entree = index.get(membre.casefold())
        if entree is None:
            raise KeyError(
                f"groupe {key} : « {membre} » n'est pas dans la liste blanche "
                "(src/admin/auto_merchants.py) — groupe et liste blanche ont divergé")
        cibles.append(entree)
    return cibles


def coverage() -> dict[str, object]:
    """De quoi vérifier d'un coup d'œil que rien n'est perdu ni compté deux fois."""

    membres = [m for groupe in GROUPS.values() for m in groupe]
    connus = {nom for nom, _ in AUTO_MERCHANTS}
    return {
        "groupes": {g: list(m) for g, m in GROUPS.items()},
        "charge_estimee": {g: sum(PENDING_2026_09_21.get(m, 0) for m in membres_g)
                           for g, membres_g in GROUPS.items()},
        "doublons": sorted({m for m in membres if membres.count(m) > 1}),
        "hors_groupes": sorted(connus - set(membres)),
        "inconnus": sorted(set(membres) - connus),
    }
