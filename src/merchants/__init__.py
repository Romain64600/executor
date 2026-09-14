"""Per-merchant plugins — one module per merchant with real specifics (R32d,
2026-08-28, Romain: "un fichier config par marchand … le contrat commun + surcharge";
2026-09-14 ultimatum: « pour la détection région / édition / plateforme, tu as un fichier
de config par marchand. Et si tu ne l'as pas, tu dois l'avoir. »).

The COMMON contract lives elsewhere and is untouched here:
- ``src.merchant_config`` — the ``MerchantConfig`` / ``MerchantOfferSignals`` schema,
  PC-side hooks (precheck / title_region / resolve_name / url_platform) and console-side
  hooks (console_url_families / console_pc_declared / console_region_slot /
  console_noise, R45 2026-09-14);
- ``src.matcher`` — the generic ``match_offer`` pipeline (platform/region/edition,
  R01/R20/R27) and the merchant-agnostic GMG green-gift handling;
- ``src.console_keys`` — the SHARED console vocabulary (platform phrase grammar,
  families, buckets, non-game / store / delivery markers, region text → base / label,
  plain slug runs) and the classifier that consults the merchant hooks.

Each ``merchants/<name>.py`` holds only that merchant's SPECIFIC pieces — its
``MerchantConfig`` values, its offer-page resolver(s), its data tables and its console
grammar hooks — importing only the low layers (``src.aks_env`` for ``http_get``;
``src.merchant_config`` for the dataclasses; ``src.console_keys`` for the shared console
vocabulary: skip reasons, ``slug_families``, ``path_tokens``). It must NOT import
``src.matcher`` (that would be circular: the matcher reads the merchant registry).

The registry (``MERCHANT_CONFIGS`` / ``merchant_config``) lives in
``src.merchants.registry`` since 2026-09-14 (re-exported by ``src.matcher``); register a
new merchant module there. ``src.console_keys`` imports the registry at call time only,
so a merchant module may import ``src.console_keys`` at module level without a cycle.
"""
