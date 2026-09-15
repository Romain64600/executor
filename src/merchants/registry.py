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

from src.merchant_config import MerchantConfig
from src.merchants import (
    allyouplay,
    cjs,
    difmark,
    driffle,
    electronicfirst,
    eneba,
    g2a,
    gameboost,
    gamersoutlet,
    gameseal,
    gamivo,
    instant_gaming,
    k4g,
    kinguin,
    mmoga,
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
}


def merchant_config(merchant: str) -> MerchantConfig | None:
    """The config of ``merchant`` (case / whitespace-insensitive name), or None."""

    return MERCHANT_CONFIGS.get((merchant or "").strip().upper())
