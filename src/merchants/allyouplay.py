"""Allyouplay (feed store 17) — declaration only (2026-09-14, Romain's rule R32 / R45).

Romain: « pour la détection région / édition / plateforme, tu as un fichier de config par
marchand. Et si tu ne l'as pas, tu dois l'avoir. » Allyouplay is on the safe-auto allowlist
(``src/admin/auto_merchants.py``) but has NEVER been swept: no run directory, no saved
feed, no console row in the 2026-09-12 extraction (docs/MERCHANTS.md: « non, dry-run
d'abord » — Romain 2026-09-11). This file therefore DECLARES nothing but the identity: no
grammar is invented without an observed batch; the generic rules and the shared console
vocabulary apply, fail-closed.

Grammaire à apprendre au premier dry-run (``scripts/10 … --dry-run``): the title / URL
shapes, the region slot, the platform phrase, then the hooks (``precheck`` /
``title_region`` / ``resolve_name`` / ``console_region_slot`` / ``console_url_families``).
"""

from __future__ import annotations

from src.merchants.common import make_config

CONFIG = make_config(
    "Allyouplay",
    domain="allyouplay.com",          # to confirm at the first dry-run (a mismatch fails closed)
    notes=("feed store 17 — jamais balayé : grammaire à apprendre au premier dry-run "
           "(Romain 2026-09-11) ; aucun hook inventé sans lot observé (2026-09-14)"),
)
