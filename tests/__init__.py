"""Les tests ne lisent jamais l'index sitemap AKS vivant de la machine (``state/aks_sitemap.json``).

10/10/2026 : le premier balayage K4G lancé depuis l'admin a écrit un index complet (214 560 pages) et neuf tests du matcher
(``test_matcher``, ``test_consoles_decisions_2026_09_25``) qui supposaient « pas d'index » ont rougi : ``resolve_aks`` trouvait
les pages dans l'index au lieu de sonder. Les tests qui veulent un index le posent eux-mêmes (``set_sitemap_index``)."""
import os

os.environ.setdefault("AKS_SITEMAP_PATH", "/nonexistent/aks_sitemap-tests.json")
