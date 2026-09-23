"""GOG.com (feed store 34) — la boutique de premier rang, déclarée 2026-09-22 `[R55]`.

Romain, 2026-09-22 : « pour GOG, on peut prendre le titre en complément d'information.
Testons sur une page. »

Audit complet : `docs/AUDIT_2026-09-22_gog.md`, sur les 3 473 lignes du scan tous-magasins
`20260921-072420-sort` et huit pages AKS lues en direct.

**Ce que GOG est, et pourquoi ça change tout.** GOG n'est pas un revendeur de clés : c'est la
boutique de CD Projekt, qui vend ses propres jeux SANS DRM. Sur une page AKS elle voisine
Epic Games et le Humble Store, pas Kinguin. Il n'y a donc ni région ni plateforme à lire dans
ses titres — **il n'y en a qu'une**, et elle vient de l'identité de la boutique :

* la **plateforme** est GOG, parce que `gog.com` ne vend que du GOG ;
* la **région** est mondiale, parce qu'un jeu sans DRM n'a pas de verrou régional.

Vérifié côté AKS : sur huit pages produit et dix lignes GOG, le seau de région est **6**
(GOG GLOBAL) dix fois sur dix. Les seaux GOG EU (62), US (63) et UK (64) existent dans notre
table mais n'apparaissent jamais.

**Le titre est un COMPLÉMENT, jamais la source de la plateforme.** C'est la nuance de la
décision de Romain, et elle est mesurée. Le titre GOG est un nom de produit nu :

    The Mummy Demastered
    Book of Demons - Collector's Content
    Relayer Advanced DLC- Herschel NEXT
    Two Worlds Epic Edition Complete

Chercher la plateforme dedans donne **3 472 erreurs sur 3 473** (3 466 fois le défaut STEAM,
6 fois EPIC parce que « Epic » est dans le NOM du jeu — « Two Worlds Epic Edition », « Epic
Map Pack », « Epic Pinball »). D'où `title_is_platform_source=False` : la plateforme vient
du domaine, point. Ce que le titre apporte vraiment, et qu'on garde :

* l'**édition** (10,5 % des titres portent Deluxe / Gold / Collector's / Complete…) — lue par
  le `detect_edition` générique, inchangé ;
* le marqueur **DLC** (5,1 %) — lu par les règles R18 / R43 génériques, inchangées ;
* le mot **« demo »** (4,1 %, 142 lignes) — et celui-là, c'est un refus.

**Les mêmes mots pièges, côté région.** Douze titres contiennent « Europe », « US », « UK » ou
« Global » : « Strategic Command WWII: War in Europe », « Tiny Troopers: Global Ops »,
« Construction Simulator 2 US ». Douze sur douze sont des NOMS DE JEUX. C'est pourquoi
`title_region` ne lit pas le titre : il RÉPOND « global », qui est un fait sur la boutique,
et court-circuite ainsi le scan générique avant qu'il ne trouve « Europe » dans un nom de jeu.

**Ce que ce fichier NE fait pas.** Il n'ouvre aucune page GOG (`offer_page_resolver` absent) :
tout se décide sur le feed, l'URL et la page AKS. Il ne touche pas aux consoles : GOG est une
boutique PC, ses URL sont toutes `/en/game/<slug>` et aucune ne déclare de console.
"""

from __future__ import annotations

import re

from src.merchant_config import MerchantConfig

NAME = "GOG"
DOMAIN = "gog.com"
STORE_ID = "34"

# `demo` isolé, à n'importe quelle place du titre. Le mot est ancré sur ses frontières : sans
# ça « Demolition Company » et « Democracy 3 » partiraient avec les démos.
_DEMO_RE = re.compile(r"\bdemos?\b", re.I)
# …et le même mot dans le slug de l'URL, où il est séparé par des soulignés :
# gog.com/en/game/defend_the_rook_tactical_tower_defense_demo
_DEMO_URL_RE = re.compile(r"(?:^|[_/-])demos?(?:$|[_/-])", re.I)

# La forme d'URL de GOG, seule et unique sur 3 473 lignes : /en/game/<slug>.
_GAME_URL_RE = re.compile(r"//(?:www\.)?gog\.com/", re.I)


def precheck(name: str, url: str) -> str | None:
    """Les refus propres à GOG, avant tout scan générique.

    Une seule famille aujourd'hui : les DÉMOS. Un produit gratuit ne se vend pas, n'a pas de
    prix à comparer et n'a donc rien à faire sur un comparateur — ni comme offre à créer, ni
    comme page à demander. 142 lignes sur 3 473 (4,1 %). Le mot est cherché dans le titre ET
    dans le slug, parce qu'il arrive qu'il ne soit que dans l'un des deux."""

    if _DEMO_RE.search(name or "") or _DEMO_URL_RE.search(url or ""):
        return ("GOG demo — produit gratuit, aucune clé vendue, aucun prix à comparer "
                "(audit 2026-09-22)")
    return None


def url_platform(url: str) -> str | None:
    """La plateforme, déclarée par le DOMAINE — jamais devinée.

    `[R51]` (2026-09-16) refuse d'INFÉRER la plateforme d'un titre nu depuis la ligne
    « Direct Publisher » de la page AKS, parce que cette ligne décrit le JEU et non la clé du
    marchand. Rien de tel ici : `gog.com` est la boutique de GOG et ne vend que du GOG. C'est
    un fait sur le vendeur, pas une déduction sur le produit — la porte que R51 a fermée
    reste fermée. Un audit re-proposera le rapprochement : ce n'est pas le même mécanisme."""

    return "GOG" if _GAME_URL_RE.search(url or "") else None


def title_region(name: str) -> str | None:
    """Toujours « global » — et c'est un fait sur la BOUTIQUE, pas une lecture du titre.

    Un jeu GOG est sans DRM : il n'a pas de verrou régional, et AKS le range en seau 6
    (GOG GLOBAL) dix fois sur dix sur les pages observées. Ce que ce crochet empêche, en
    répondant avant le scan générique, c'est que celui-ci trouve une région dans un NOM DE
    JEU : « War in Europe », « Global Ops », « Construction Simulator 2 US » — douze titres
    du corpus, douze faux positifs."""

    return "global"


CONFIG = MerchantConfig(
    name=NAME,
    domain=DOMAIN,
    # Le titre ne déclare PAS la plateforme (3 472 erreurs sur 3 473 si on l'écoute).
    title_is_platform_source=False,
    url_platform=url_platform,
    title_region=title_region,
    precheck=precheck,
    # `[R56]` (Romain, 2026-09-22 : « pour GOG pas besoin que la page déclare GOG »).
    # R20 refuse une ligne dont la plateforme déclarée n'est pas dans les plateformes
    # officielles de la page. Ce garde protège un marchand dont la plateforme est LUE dans
    # un titre ; celle de GOG vient de son domaine, et la liste d'une page AKS peut être
    # incomplète sans rien prouver. Mesuré avant de le poser, sur les 128 lignes que R20
    # refusait : 125 de ces pages n'ont AUCUN seau GOG (6) et retombent sur « no region
    # id » — le vrai refus. Une seule ligne est réellement débloquée.
    require_page_platform=False,
    # On n'ouvre pas la page marchande : tout se décide sur le feed, l'URL et la page AKS.
    offer_page_readable=True,
    publisher_from_merchant_page=False,
    notes=("Boutique de premier rang, sans DRM. Plateforme GOG déclarée par le domaine, "
           "région toujours GOG GLOBAL (seau 6). Le titre ne sert qu'à l'édition, aux "
           "marqueurs DLC et au refus des démos. Audit : docs/AUDIT_2026-09-22_gog.md"),
)
