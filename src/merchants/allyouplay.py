"""Allyouplay (feed store 17) — le lien d'affiliation (2026-09-30).

Dans la liste blanche (``src/admin/auto_merchants.py``, groupe B) depuis le 14/09, fichier
d'identité seule jusqu'ici (« aucun hook inventé sans lot observé »). Le lot existe maintenant :
**six balayages du groupe B depuis le 17/09, 296 lignes distinctes, 100 % refusées par le
contrôle de domaine** (« offer URL not on allyouplay.com ») — aucune offre Allyouplay n'a
jamais été saisie. Première lecture complète le 29/09, à l'aperçu par page de Nivalis Nights
et Transport Fever 3.

**Le lien du feed n'est pas sur allyouplay.com.** Toutes les lignes passent par le même
redirecteur Impact :
``https://anandadigitalbv.sjv.io/c/1297091/2866230/30655?prodsku=42863&u=<fiche>&intsrc=CATF_22827``
— hôte, chemin, ``prodsku`` et ``intsrc`` identiques pour les 296 lignes ; la fiche est dans
``u`` (encodée), sur ``www.allyouplay.com``.

Règle de Romain (2026-09-30, « Go ») : « accepter le lien d'affiliation seulement si u pointe
vers allyouplay.com, et u sert d'identité comme Loaded ». D'où, ici :

* ``affiliate_hosts`` — l'hôte du redirecteur. ``MerchantConfig.landing_url`` rend la fiche de
  ``u`` quand elle est sur allyouplay.com ; le contrôle de domaine et toutes les lectures de
  signaux d'URL (région, région interdite, plateforme d'URL) lisent cette fiche. Un lien du
  redirecteur sans ``u``, ou dont ``u`` n'est pas sur allyouplay.com, reste refusé par le
  contrôle de domaine, avec un motif qui le NOMME (« affiliate link without a allyouplay.com
  product page in u »). L'URL stockée n'est jamais réécrite.
* ``url_identity_params=("u",)`` — comme Loaded : le chemin est le même pour toutes les
  offres, l'annonce est dans ``u``. Sans lui, demander la ligne 2 sélectionnait la ligne 1 et
  une sœur restée au feed empêchait de prouver la disparition d'une offre créée.

**Grammaire observée (296 lignes, runs du 17/09 au 26/09) — NON codée, décisions de Romain :**

* Premier segment de la fiche : ``/pc/`` 228, ``/xbox/`` 31, ``/cash-points/`` 25
  (monnaies de jeu, points), ``/subscription/`` 11 (Tinder Gold / Plus), ``/bundle/`` 1.
* Les titres PC ne portent **ni plateforme ni région** (« Nivalis Nights », « Transport Fever
  3 », « Worms Armageddon ») ; quelques « [Mac] ». Les titres Xbox portent la génération en
  queue (« - Xbox One », « - Xbox Series X|S »), parfois un pays (« … - Xbox Series X|S - BE »).
* Codes glissés dans certains slugs : ``-ga-ste-`` (Steam), ``-ga-gog-`` (GOG), ``-row-<uuid>``
  / ``-row-september-2026-…`` (Rest of World), ``-ww-<uuid>`` (monde), ``cnprc``, ``res30``,
  ``t2wwd``, ``glok2``, ``pointnxs``, suffixes ``-2`` … ``-11``. Le ``-row-`` est lu par le scan
  générique des régions interdites (la fiche est maintenant visible) : refus ``forbidden
  region: ROW``, conforme à la règle ROW du 24/09.
* La fiche produit est **lisible en HTTP** (200, pas de Cloudflare, vérifié le 29/09) : le
  payload Nuxt porte l'attribut « Platform: Steam » et ``available_countries``. Un lecteur de
  page (comme Gamesplanet FR ``[R59]``) est une option, pas codée.

Tant que Romain n'a pas tranché, les lignes suivent la lecture générique : plateforme par
défaut STEAM (vérifiée contre la page AKS, R20), région GLOBAL implicite, édition du titre.
Branche ``allyouplay-affiliate`` — pas en ligne tant que l'aperçu n'est pas validé.
"""

from __future__ import annotations

from src.merchants.common import make_config

DOMAIN = "allyouplay.com"
AFFILIATE_HOST = "anandadigitalbv.sjv.io"


CONFIG = make_config(
    "Allyouplay",
    domain=DOMAIN,
    affiliate_hosts=(AFFILIATE_HOST,),
    # Le chemin du redirecteur (`/c/1297091/2866230/30655`) est le même pour les 296 lignes :
    # l'annonce est dans `u`, comme chez Loaded (2026-09-26).
    url_identity_params=("u",),
    notes=("feed store 17 — liens d'affiliation `anandadigitalbv.sjv.io/…?u=<fiche "
           "allyouplay.com>` : la fiche de `u` fait foi pour le domaine et les signaux d'URL, "
           "`u` est l'identité (2026-09-30, branche allyouplay-affiliate). Titres PC sans "
           "plateforme ni région : région / plateforme / catégories à trancher par Romain."),
)
