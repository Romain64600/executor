"""The merchant registry — merchant name → ``MerchantConfig`` (R32, 2026-08-11).

Relocated from ``src.matcher`` on 2026-09-14 (R32 / R45, Romain: « un fichier de config
par marchand ») so that BOTH the matcher and the shared console classifier
(``src.console_keys``) read the same registry without a circular import: this module
imports the merchant modules (which import only ``src.merchant_config``, ``src.aks_env``
and the shared vocabulary of ``src.console_keys``); ``src.console_keys`` imports it
lazily (function-level) — never ``src.matcher``.

The pipeline "starts from the merchant config": ``match_offer`` reads
``merchant_config(offer.merchant)`` and applies its rules; a merchant with no config
keeps the generic behaviour. Every merchant of the safe-auto allowlist has its own
``src/merchants/<name>.py`` exporting a ``CONFIG`` (2026-09-14: kinguin / driffle / k4g /
cjs / allyouplay / gameseal joined mmoga / gamivo / eneba / g2a / instant_gaming /
difmark). ``src.matcher.MERCHANT_CONFIGS`` / ``src.matcher.merchant_config`` are THIS
dict / function (re-exported), so tests patching ``src.matcher.MERCHANT_CONFIGS`` in
place keep working.
"""

from __future__ import annotations

import functools
import urllib.parse

from src.merchant_config import MerchantConfig
from src.merchants import (
    allyouplay,
    cjs,
    difmark,
    discover,
    driffle,
    electronicfirst,
    eneba,
    g2a,
    gameboost,
    gamersoutlet,
    gameseal,
    gog,
    gamivo,
    instant_gaming,
    k4g,
    kinguin,
    loaded,
    mmoga,
    gamerall,
    gamesplanet,
    wyrel,
)

# Keys = the allowlist spelling (src/admin/auto_merchants.py AUTO_MERCHANTS) upper-cased;
# every allowlisted merchant has its module (Romain 2026-09-14: « si tu ne l'as pas, tu
# dois l'avoir »), Difmark (167) is parked but keeps its file. GameBoost (157) is NOT on
# the safe-auto allowlist either (R27, 2026-07-15 — batch cancelled live; R47, 2026-09-15 —
# the region is missing from about a third of its titles): its file exists so a SUPERVISED
# run (02 → 03 → 04 → 05) reads its grammar and fails closed on everything it cannot read.
MERCHANT_CONFIGS: dict[str, MerchantConfig] = {
    "KINGUIN": kinguin.CONFIG,
    "G2A": g2a.CONFIG,
    "DRIFFLE": driffle.CONFIG,
    "ENEBA": eneba.CONFIG,
    "K4G": k4g.CONFIG,
    "GAMIVO": gamivo.CONFIG,
    "INSTANT GAMING": instant_gaming.CONFIG,
    "CJS-CDKEYS": cjs.CONFIG,
    "ALLYOUPLAY": allyouplay.CONFIG,
    "GAMESEAL": gameseal.CONFIG,
    "MMOGA": mmoga.CONFIG,
    "DIFMARK": difmark.CONFIG,
    "GAMEBOOST": gameboost.CONFIG,
    "GAMERSOUTLET": gamersoutlet.CONFIG,
    "ELECTRONICFIRST": electronicfirst.CONFIG,
    "WYREL": wyrel.CONFIG,
    "GAMERALL": gamerall.CONFIG,
    "GOG": gog.CONFIG,
    # [R59] Gamesplanet FR (2026-09-25) — liste blanche le même jour, groupe A, après l'essai à
    # blanc (77 candidats sur 150 lignes).
    "GAMESPLANET FR": gamesplanet.CONFIG,
    # [R60] Discover.games (2026-09-25) — fichier écrit, PAS encore en liste blanche : essai à
    # blanc d'abord (docs/PROCHAINS_MARCHANDS.md).
    "DISCOVER.GAMES": discover.CONFIG,
    # [R61] Loaded, ex-CDKeys (2026-09-25) — fichier écrit, PAS encore en liste blanche.
    "LOADED": loaded.CONFIG,
}


# ── store id → canonical merchant name ───────────────────────────────────────────────
# The FEED store id of every registered merchant (each module states it in its own notes;
# ``src/admin/auto_merchants.py`` enforces the same pairing for the allowlist). Needed by
# any stage that reads a feed WITHOUT a store filter — the all-stores "sort" scan labels
# every row "all-stores", so without this map the merchant rules never fire (audit de
# Romain, 2026-09-16: an MMOGA "… RU Key" row was routed Blacklist under its real merchant
# and became an un-routed creation candidate in the all-stores scan).
MERCHANT_STORE_IDS: dict[str, str] = {
    "Kinguin": "58", "G2A": "38", "Driffle": "127", "Eneba": "19", "K4G": "92",
    "Gamivo": "51", "Instant Gaming": "28", "CJS-CDKeys": "30", "Allyouplay": "17",
    "GameSeal": "126", "GameBoost": "157", "Electronicfirst": "70",
    "GamersOutlet": "31", "MMOGA": "12", "Difmark": "167", "Wyrel": "162",
    "Gamerall": "13", "GOG": "34", "Gamesplanet FR": "55",
    "Discover.games": "168", "Loaded": "40",
}
_BY_STORE: dict[str, str] = {store: name for name, store in MERCHANT_STORE_IDS.items()}


def merchant_for_store(store_id: str | int | None) -> str | None:
    """The canonical merchant NAME of a feed store id ("12" → "MMOGA"), or None.

    Used to restore a row's merchant identity when the feed was read without a store
    filter. Returns None for an unknown store: the caller then keeps whatever label the
    feed gave, and the generic behaviour applies — never a guessed merchant."""

    key = str(store_id).strip() if store_id is not None else ""
    return _BY_STORE.get(key)


def url_identity_params(url: str) -> tuple[str, ...]:
    """Les paramètres de query qui font partie de l'identité d'une annonce, d'après l'HÔTE de
    son URL (`MerchantConfig.url_identity_params`, 2026-09-24) — ``()`` pour tout marchand qui
    n'en déclare pas, ou une URL illisible : la clé reste alors le chemin seul (P2-12)."""

    try:
        host = urllib.parse.urlparse(str(url or "")).netloc.lower()
    except ValueError:
        return ()
    return _identity_params_for_host(host)


@functools.lru_cache(maxsize=512)
def _identity_params_for_host(host: str) -> tuple[str, ...]:
    if not host:
        return ()
    host = host.split("@")[-1].split(":")[0]
    for cfg in MERCHANT_CONFIGS.values():
        dom = (cfg.domain or "").lower()
        if dom and cfg.url_identity_params and (host == dom or host.endswith("." + dom)):
            return tuple(cfg.url_identity_params)
    return ()


def merchant_config(merchant: str) -> MerchantConfig | None:
    """The config of ``merchant`` (case / whitespace-insensitive name), or None."""

    return MERCHANT_CONFIGS.get((merchant or "").strip().upper())
