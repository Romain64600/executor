"""Per-merchant plugins — one module per merchant with real specifics (R32d,
2026-08-28, Romain: "un fichier config par marchand … le contrat commun + surcharge").

The COMMON contract lives elsewhere and is untouched here:
- ``src.merchant_config`` — the ``MerchantConfig`` / ``MerchantOfferSignals`` schema;
- ``src.matcher`` — the generic ``match_offer`` pipeline (platform/region/edition,
  R01/R20/R27) and the merchant-agnostic GMG green-gift handling.

Each ``merchants/<name>.py`` holds only that merchant's SPECIFIC pieces — its
``MerchantConfig`` values, its offer-page resolver(s), and its data tables — importing
only the low layers (``src.aks_env`` for ``http_get``; ``src.merchant_config`` for the
dataclasses). It must NOT import ``src.matcher`` (that would be circular: matcher reads
the merchant registry). Trivial merchants (Kinguin/Driffle/K4G/CJS/Allyouplay/GameSeal)
need no module — they fall through to the generic behaviour.

Migration is incremental (one merchant per commit, 0 behaviour change); the registry
(``MERCHANT_CONFIGS`` / ``merchant_config``) still lives in ``src.matcher`` and imports
these modules until every merchant with specifics has moved.
"""
