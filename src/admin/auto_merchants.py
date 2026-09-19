"""Allowlist of merchants eligible for UNVALIDATED safe-auto data entry.

Safe-auto (`/executor/auto`) sweeps a feed and **adds offers without human
validation**. Unlike the main page's free-text merchant entry (a mere typing
shortcut), this list is an *authoritative gate*: a merchant absent here cannot
be launched in auto mode. The frontend only offers these as suggestions, and
`POST /api/data-entry/auto` re-checks server-side so a hand-crafted request
can't bypass the UI (fail-closed).

Keep it in sync with what is actually vetted for unvalidated writing. Adding a
merchant here is a deliberate act: it authorises the pipeline to create its
offers on AKS with no operator review.
"""

from __future__ import annotations

# Ordered (name, store_id) — mirrors the AKS store id. Order drives display.
# Scope decided with Romain (2026-08-07): the mainstream CD-key sellers.
AUTO_MERCHANTS: list[tuple[str, str]] = [
    ("Kinguin", "58"),          # proven in safe-auto this session
    ("G2A", "38"),
    ("Driffle", "127"),
    ("Eneba", "19"),
    ("K4G", "92"),
    ("Gamivo", "51"),
    ("Instant Gaming", "28"),
    ("CJS-CDKeys", "30"),
    ("Allyouplay", "17"),
    ("GameSeal", "126"),
    ("GameBoost", "157"),       # Romain 2026-09-16 (« Ajoute Gameboost a la whiteliste »),
                                # après son 1er matching réel : 207 candidats sur 992 lignes
                                # (13 pages), zéro PUBLISHER, et la 1re passe de saisie. Son
                                # fichier (R47) refuse toute ligne sans région. Feed store 157.
    ("Electronicfirst", "70"),  # Romain 2026-09-16 (« On va whitelist Eletronicfirst et
                                # Gamersoutlet »): dé-parqué le même jour — le défaut qui
                                # l'avait fait parquer (2 lignes entrées PUBLISHER au lieu de
                                # STEAM sur un titre nu) est fermé par [R51], qui refuse
                                # désormais ces lignes. Feed store 70.
    ("GamersOutlet", "31"),     # Romain 2026-09-16, même message. Feed store 31. Petite file
                                # (~19 lignes, ~2 saisissables) : le volume viendra avec le temps.
    ("Gamerall", "13"),         # Romain 2026-09-19 (« Tu peux ajouter Gamerall aux marchands
                                # whitelisted ? »). Fichier écrit le 18/09 sur 783 lignes réelles
                                # (pages 1-6 et 26-31), 1re saisie 10/10 créées le même jour.
                                # [R54] : région lue titre → URL → PAGE, et la page marchand est
                                # OUVERTE pour les ~18 % de lignes sans région — une page
                                # illisible, ou lisible sans région, est un REFUS, jamais un repli
                                # sur GLOBAL. Deux défauts de ce fichier ont été corrigés le
                                # 18/09 au soir (audit complet) APRÈS cette 1re saisie : le jeton
                                # « UPLAY » inconnu de REGION_IDS, qui refusait 100 % des lignes
                                # Ubisoft Connect sur un faux conflit, et la branche console qui
                                # n'ouvrait jamais la page — donc les lignes PSN / Switch
                                # partaient en GLOBAL implicite. Les deux sont verrouillés par
                                # test. Feed store 13 ; marchand AKS 317.
    ("MMOGA", "12"),            # Romain 2026-09-10 (« je préfère passer directement par /auto »):
                                # authorised for safe-auto BEFORE a supervised validated run —
                                # the merchant rules (src/merchants/mmoga.py) fail closed on any
                                # region code they cannot map. Feed store 12; AKS page id 40.
]

# Deliberately NOT suggested (enforcement is simply "absent from the list";
# named here for humans):
#   Difmark (167)  — parked 2026-08-07, feed is console/Epic/Windows (~0 enterable).
#     (GameBoost 157 joined the list above on 2026-09-16.)
#     (Electronicfirst 70 and GamersOutlet 31 were moved INTO the list above on 2026-09-16.)
#     (Gamerall 13 joined the list above on 2026-09-19.)

_BY_NAME: dict[str, tuple[str, str]] = {
    name.casefold(): (name, store) for name, store in AUTO_MERCHANTS
}


def allowed_list() -> list[dict[str, str]]:
    """The suggestions, as JSON-friendly dicts (for the GET route / UI)."""
    return [{"name": name, "store_id": store} for name, store in AUTO_MERCHANTS]


def rejection_reason(merchant: str, store_id: str) -> str | None:
    """None if (merchant, store_id) is allowed for auto; else a human message.

    Enforces the canonical store too: since the UI derives the store from the
    picked merchant, a mismatched store means a tampered/stale request — refuse.
    """
    name = (merchant or "").strip()
    hit = _BY_NAME.get(name.casefold())
    if hit is None:
        return (f"« {name or '(vide)'} » n'est pas dans la liste des marchands "
                "suggérés — data-entry auto restreint aux marchands vettés")
    if hit[1] != str(store_id or "").strip():
        return (f"{hit[0]} attend le store {hit[1]}, pas "
                f"« {str(store_id or '').strip() or '(vide)'} »")
    return None


def is_allowed(merchant: str, store_id: str) -> bool:
    return rejection_reason(merchant, store_id) is None
