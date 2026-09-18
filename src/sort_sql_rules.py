"""Les règles de tri SQL de Romain — la liste qu'il lance quotidiennement (2026-09-18).

Romain : « je te donne la liste des requêtes qu'on a déjà trouvé et qu'on lance daily ».
Elles vivent ici plutôt que dans un coin de terminal, pour trois raisons : elles sont
versionnées, elles sont MESURABLES contre un scan de tri réel (``scripts/13_sort_sql.py``),
et la console peut les afficher prêtes à copier.

Chaque règle est ``(motif LIKE, liste cible)``. Le motif est confronté à l'URL, en
minuscules : c'est le choix de Romain (« on filtre sur l'url »), et c'est aussi pourquoi
``%Month-Subscription%`` et ``%month-subscription%`` de sa liste ne font qu'une règle ici —
MySQL compare sans tenir compte de la casse avec les collations ``_ci`` usuelles, et notre
mesure, elle, replie explicitement la casse.

**Ce fichier n'exécute rien.** Il décrit. L'exécution reste manuelle, dans phpMyAdmin.
"""

from __future__ import annotations

GIFT_CARDS = "21"
BLACKLIST = "8"
ACCOUNTS = "30"

# (motif, liste) — l'ordre est celui de la liste de Romain, regroupé par destination.
RULES: list[tuple[str, str]] = [
    # --- cartes cadeaux, abonnements, monnaies et temps de jeu -> 21
    ("%gift-card%", GIFT_CARDS),
    ("%-giftcard%", GIFT_CARDS),
    ("%wallet-card%", GIFT_CARDS),
    ("%paypal-wallet%", GIFT_CARDS),
    ("%prepaid%", GIFT_CARDS),
    ("%-itunes%", GIFT_CARDS),
    ("%/itunes%", GIFT_CARDS),
    ("%-ikea-%", GIFT_CARDS),
    ("%-minecoins%", GIFT_CARDS),
    ("%-robux-%", GIFT_CARDS),
    ("%-coins-%", GIFT_CARDS),
    ("%-ancient-coins-%", GIFT_CARDS),
    ("%-nhl-points-%", GIFT_CARDS),
    ("%-fc-points-%", GIFT_CARDS),
    ("%-clothing-set-%", GIFT_CARDS),
    ("%-outfit-%", GIFT_CARDS),
    ("%-pass-psn-%", GIFT_CARDS),
    ("%-pass-xbox%", GIFT_CARDS),
    ("%months-subscription%", GIFT_CARDS),
    ("%month-subscription%", GIFT_CARDS),
    ("%year-subscription%", GIFT_CARDS),
    ("%-subscription-%", GIFT_CARDS),
    ("%1-months%", GIFT_CARDS),
    ("%2-months%", GIFT_CARDS),
    ("%3-months%", GIFT_CARDS),
    ("%4-months%", GIFT_CARDS),
    ("%6-months%", GIFT_CARDS),
    ("%-1-month-%", GIFT_CARDS),
    ("%1-year%", GIFT_CARDS),
    ("%valid-for-%", GIFT_CARDS),
    ("%0-days%", GIFT_CARDS),
    ("%-day-game-time-code%", GIFT_CARDS),
    ("%-day-credit%", GIFT_CARDS),
    ("%5-usd%", GIFT_CARDS),
    ("%0-usd%", GIFT_CARDS),
    ("%5-eur%", GIFT_CARDS),
    ("%0-eur%", GIFT_CARDS),
    ("%5-gbp%", GIFT_CARDS),
    ("%0-gbp%", GIFT_CARDS),
    # --- contenus non vendables seuls, régions fermées -> 8
    ("%soundtrack%", BLACKLIST),
    ("%digital_extras%", BLACKLIST),
    ("%digital_deluxe_content%", BLACKLIST),
    ("%costume_pack%", BLACKLIST),
    ("%-furniture-pack%", BLACKLIST),
    ("%-cosmetic-pack%", BLACKLIST),
    ("%-weapon-charm%", BLACKLIST),
    ("%-puzzles-%", BLACKLIST),
    ("%puzzle%", BLACKLIST),
    ("%steam-key-china%", BLACKLIST),
    ("%valid-until%", BLACKLIST),
    # --- comptes -> 30
    ("%online-account-activation%", ACCOUNTS),
    ("%steam-account%", ACCOUNTS),
]

# Règles que Romain lance mais qui CONTREDISENT une décision écrite, ou qui visent
# structurellement de vrais jeux. Elles restent dans RULES (c'est sa liste, il la lance),
# mais la console et le rapport les signalent pour qu'il tranche en connaissance de cause.
# Une entrée ici n'empêche rien : elle explique.
FLAGGED: dict[str, str] = {
    "%valid-until%": (
        "contredit une décision écrite : « Kinguin valid until juin 2027 on rentre » "
        "(Romain 2026-09-14, AGENTS.md « Reviewed decisions »). La note est une date "
        "limite d'activation, pas un produit ; ces clés sont ENTRÉES, et cette requête "
        "les blackliste."
    ),
    "%puzzle%": (
        "vise un GENRE de jeu, pas une catégorie non vendable — tout jeu de puzzle "
        "vendable dont l'URL contient le mot part en Blacklist."
    ),
    "%-coins-%": (
        "« coins » apparaît aussi dans des noms de jeux ; à mesurer avant de lancer."
    ),
    "%1-year%": (
        "vise aussi des jeux dont l'URL porte une durée ; mesuré une fois sur un "
        "échantillon, son unique ligne visée était un vrai jeu."
    ),
}
