"""CJS-CDKeys (feed store 30) — declaration only (2026-09-14, Romain's rule R32 / R45).

On the safe-auto allowlist (``src/admin/auto_merchants.py``, spelled "CJS-CDKeys") but
NEVER swept: no run directory, no saved feed, no console row in the 2026-09-12 extraction
(docs/MERCHANTS.md: « non, dry-run d'abord » — Romain 2026-09-11). Nothing is invented
without an observed batch: the generic rules and the shared console vocabulary apply,
fail-closed. The registry must map both spellings "CJS-CDKeys" (auto_merchants) and "CJS"
to this CONFIG.

Grammaire à apprendre au premier dry-run (``scripts/10 … --dry-run``): the title / URL
shapes, the region slot, the platform phrase, then the hooks.
"""

from __future__ import annotations

from src.merchants.common import make_config

CONFIG = make_config(
    "CJS-CDKeys",
    domain="cjs-cdkeys.com",          # to confirm at the first dry-run (a mismatch fails closed)
    notes=("feed store 30 — jamais balayé : grammaire à apprendre au premier dry-run "
           "(Romain 2026-09-11) ; aucun hook inventé sans lot observé (2026-09-14)"),
)
