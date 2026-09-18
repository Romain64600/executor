"""Gamerall (store 13, marchand AKS 317) — `[R54]`, 2026-09-18.

Romain : « pour le data entry auto, on va devoir travailler sur Gamerall ». Écrit à partir de
783 lignes réelles (pages 1-6 et 26-31), pas d'un échantillon d'une page — la page 1 de ce feed
est trompeuse et m'avait fait annoncer un chiffre faux (voir ci-dessous).

**La grammaire, mesurée.**

* Le titre est ``<Nom> (<Plateforme>)``. La plateforme est en fin de titre, entre parenthèses,
  dans 100 % des lignes : Steam 681, Xbox Live 38, EA App 25, Ubisoft Connect 14, Nintendo
  Switch 7, PSN 4, Microsoft Store 3, GOG.com 2, Epic Games 2, Rockstar 1.
* **Le titre ne porte JAMAIS de région.** Aucune, sur 783 lignes.
* L'URL est ``gamerall.com/<section>/<slug>``, et le slug finit par la plateforme puis, quand
  elle existe, la région : ``…-steam-global``, ``…-xbox-live-usa``, ``…-steam`` (sans région).
  Vocabulaire de région mesuré : ``global`` 514, ``europe`` 123, ``usa`` 6 — et rien d'autre.

**La région absente : on ouvre la page** (Romain 2026-09-18, « absence de région = ouvrir la
page pour s'en assurer »). Mesure honnête de ce que cela coûte : sur les 783 lignes, 82 %
portent leur région dans l'URL et **18 % ne l'ont nulle part**. Ma première estimation, tirée
de la seule page 1, annonçait 89 % — elle était fausse, et la répartition est très inégale :
11 % sur la page 1, 100 % sur les pages 26-31.

Le mécanisme existait déjà (``MerchantConfig.offer_page_resolver``, Instant Gaming) : il n'y
avait rien à construire, contrairement à ce que j'avais dit. La page Gamerall répond en 200 et
porte sa région dans son JSON embarqué (``"Region","value":"Global"``), vérifié en réel.

**Fail-closed, comme Instant Gaming (son audit #2).** Une page illisible, ou lisible mais sans
région exploitable, ne se replie PAS sur GLOBAL : elle lève, et l'offre est refusée. Deviner la
zone d'une clé, c'est la créer au mauvais endroit.

**Le résolveur ne coûte une requête que lorsqu'il le faut.** Le matcher l'appelle pour chaque
offre ; ici il lit d'abord l'URL et ne va chercher la page que pour les 18 % sans région. Sans
cette précaution, un sweep de 32 pages tirerait 3 200 pages de 550 ko.
"""

from __future__ import annotations

import html
import re
import time
from typing import Any, Callable

from src.aks_env import REQUIRED_USER_AGENT, http_get
from src.merchant_config import MerchantOfferSignals
from src.merchants.common import forbidden_reason, make_config

DOMAIN = "gamerall.com"
STORE_ID = "13"
AKS_MERCHANT_ID = "317"

PROBE_DELAY_S = 0.6        # politesse sur un sweep en masse, comme Instant Gaming / Difmark

# Plateforme lue en fin de titre, « (…) ». Vocabulaire OUVERT : un libellé inconnu n'est pas
# deviné, il est refusé par son nom — c'est ce qui a évité les faux classements chez Wyrel.
# Les JETONS RENDUS sont ceux du matcher (`_PLATFORM_WORDS`, `REGION_IDS`), jamais le nom
# commercial : Ubisoft Connect rend UBISOFT et non « UPLAY » (audit du 2026-09-18 — le
# fichier rendait UPLAY, absent de REGION_IDS, et 100 % des lignes Ubisoft Connect étaient
# refusées sur un faux « platform conflict: title=UBISOFT vs offer page=UPLAY »).
PLATFORM_TEXT: dict[str, str] = {
    "STEAM": "STEAM",
    "XBOX LIVE": "XBOX",
    "EA APP": "EA",
    "ORIGIN": "EA",
    "UBISOFT CONNECT": "UBISOFT",
    "UPLAY": "UBISOFT",
    "NINTENDO SWITCH": "NINTENDO",
    "PSN": "PSN",
    "MICROSOFT STORE": "MICROSOFT",
    "GOG.COM": "GOG",
    "GOG": "GOG",
    "EPIC GAMES": "EPIC",
    "ROCKSTAR": "ROCKSTAR",
    "BATTLE.NET": "BATTLENET",
}

# Région en fin de slug. Seules ces trois formes existent dans le feed mesuré ; une région
# inconnue n'est pas supposée sellable, elle passe par forbidden_reason comme partout.
URL_REGION: dict[str, str] = {
    "global": "global",
    "worldwide": "global",
    "europe": "eu",
    "eu": "eu",
    "usa": "us",
    "us": "us",
    "uk": "uk",
}

_PLATFORM_RE = re.compile(r"\(([^()]{2,24})\)\s*$")
_ANY_PLATFORM_RE = re.compile(r"\(([^()]{2,24})\)")

# La plateforme est AUSSI dans le slug — mesurée présente sur 274 des 275 lignes de la
# tranche. Le résolveur de page ne reçoit que l'URL : c'est de là qu'il tire la plateforme,
# et le matcher refuse ensuite si elle contredit celle du titre (son audit #1). Ordre du plus
# long au plus court, sinon « steam » capturerait « steam-games-and-more ».
URL_PLATFORM: list[tuple[str, str]] = [
    ("-xbox-live", "XBOX"), ("-ubisoft-connect", "UBISOFT"), ("-nintendo-switch", "NINTENDO"),
    ("-microsoft-store", "MICROSOFT"), ("-epic-games", "EPIC"), ("-battle-net", "BATTLENET"),
    ("-rockstar", "ROCKSTAR"), ("-gog-com", "GOG"), ("-ea-app", "EA"), ("-origin", "EA"),
    ("-uplay", "UBISOFT"), ("-psn", "PSN"), ("-steam", "STEAM"), ("-gog", "GOG"),
]
# La valeur « Region » du JSON embarqué de la page marchand, échappée ou non.
# Le guillemet ouvrant devant « Region » n'est pas exigé : la page porte les deux formes, et
# `html.unescape` d'un fragment échappé ne le restitue pas toujours.
_PAGE_REGION_RE = re.compile(r'Region"\s*,\s*"value"\s*:\s*"([^"]{2,30})"', re.IGNORECASE)

PAGE_REGION_TEXT: dict[str, str] = {
    "GLOBAL": "global",
    "WORLDWIDE": "global",
    "EUROPE": "eu",
    "EU": "eu",
    "UNITED STATES": "us",
    "USA": "us",
    "US": "us",
    "UNITED KINGDOM": "uk",
    "UK": "uk",
}


class GamerallPageUnreadable(RuntimeError):
    """Page marchand illisible, ou lisible sans région : on refuse, on ne devine pas."""


def _slug(url: str) -> str:
    path = (url or "").split("?")[0].split("#")[0].rstrip("/").lower()
    return path.rsplit("/", 1)[-1] if "/" in path else path


def title_platform(name: str) -> str | None:
    """Notre jeton de plateforme, ou None si la parenthèse finale est inconnue."""

    m = _PLATFORM_RE.search((name or "").strip())
    if not m:
        return None
    return PLATFORM_TEXT.get(m.group(1).strip().upper())


def url_platform(url: str) -> str | None:
    """Notre jeton de plateforme, lu en FIN de slug, ou None.

    Ancré sur la fin, pas sur la présence : la rubrique ``steam-games-and-more`` contient le
    mot « steam » sans être une plateforme, et un simple ``in`` la prenait pour du Steam —
    défaut trouvé par le test qui suit, pas en production.
    """

    slug = _slug(url)
    if not slug:
        return None
    parts = slug.split("-")
    # une région finale, quand elle existe, ne masque pas la plateforme qui la précède
    for take in (2, 1):
        if len(parts) > take and "-".join(parts[-take:]) in URL_REGION:
            parts = parts[:-take]
            break
    tail = "-" + "-".join(parts)
    for word, token in URL_PLATFORM:
        if tail.endswith(word):
            return token
    return None


def url_region(url: str) -> str | None:
    """La région écrite en fin d'URL, ou None quand elle n'y est pas."""

    parts = _slug(url).split("-")
    for take in (2, 1):                      # « united-states » puis « global »
        if len(parts) >= take:
            word = "-".join(parts[-take:])
            if word in URL_REGION:
                return URL_REGION[word]
    return None


def url_region_label(url: str) -> str | None:
    """Le mot de région brut, même s'il n'est pas vendable — pour le message de refus."""

    parts = _slug(url).split("-")
    return parts[-1] if parts else None


# Régions écrites en toutes lettres dans un titre. Le feed mesuré (783 lignes) n'en contient
# AUCUNE — Gamerall met tout dans l'URL. Le crible existe quand même, et il est premier :
# Romain, 2026-09-18, « pour certains marchands on peut avoir une info dans le titre qui n'est
# pas dans l'URL […] mets un check du titre par défaut avant d'ouvrir la page, ça reste plus
# opti ». Le jour où Gamerall écrit « (Steam) GLOBAL », on le lit au lieu d'ouvrir la page.
TITLE_REGION_TEXT: dict[str, str] = {
    "GLOBAL": "global", "WORLDWIDE": "global", "ROW": "global",
    "EUROPE": "eu", "EU": "eu",
    "UNITED STATES": "us", "USA": "us", "US": "us",
    "UNITED KINGDOM": "uk", "UK": "uk",
}
_TITLE_REGION_RE = re.compile(
    r"(?<![A-Za-z])(?P<w>"
    + "|".join(re.escape(k).replace(r"\ ", r"\s+")
               for k in sorted(TITLE_REGION_TEXT, key=len, reverse=True))
    + r")(?![A-Za-z])",
    re.IGNORECASE)


def title_region(name: str) -> str | None:
    """La région écrite dans le TITRE, ou None. Lue en premier, avant l'URL et la page.

    Le nom du jeu est écarté d'abord : « Europa Universalis » ne doit pas devenir « eu ». On ne
    regarde donc que ce qui suit la parenthèse de plateforme, seul endroit où ce marchand
    écrirait une région.
    """

    # On cherche la DERNIÈRE parenthèse, pas celle de fin de chaîne : quand le titre porte
    # une région, la parenthèse de plateforme n'est plus le dernier élément (« (Steam) GLOBAL »)
    # et _PLATFORM_RE, ancré sur la fin, ne la voyait pas — le crible ne servait alors jamais.
    paren = None
    for paren in _ANY_PLATFORM_RE.finditer((name or "").strip()):
        pass
    tail = (name or "").strip()[paren.end():] if paren else ""
    if not tail.strip():
        return None
    found = _TITLE_REGION_RE.search(tail)
    if not found:
        return None
    return TITLE_REGION_TEXT.get(re.sub(r"\s+", " ", found.group("w")).upper().strip())


def resolve_name(name: str) -> str:
    """Le nom du jeu : la plateforme finale est retirée, le reste est intact."""

    base = _PLATFORM_RE.sub("", (name or "").strip()).strip()
    return base.rstrip("-–—").strip() or (name or "").strip()


def precheck(name: str, url: str) -> str | None:
    """Refus déterministes AVANT toute résolution de page."""

    if title_platform(name) is None:
        m = _PLATFORM_RE.search((name or "").strip())
        shown = m.group(1).strip() if m else "aucune"
        return (f"Gamerall: plateforme non reconnue en fin de titre ({shown!r}) — "
                f"refus plutôt que supposition (R54)")
    region = url_region(url)
    if region is None:
        return None                          # la page tranchera (offer_page_resolver)
    return forbidden_reason(region)


def fetch_page_region(url: str, http_get_fn: Callable[..., Any] = http_get) -> str:
    """Le libellé de région lu sur la page marchand. Lève si illisible ou absent."""

    if http_get_fn is http_get:
        time.sleep(PROBE_DELAY_S)
    try:
        page = http_get_fn(url, timeout=20, user_agent=REQUIRED_USER_AGENT)
    except Exception as exc:                 # noqa: BLE001 — tout échec = refus
        raise GamerallPageUnreadable(f"page Gamerall injoignable : {exc}") from exc
    if not (page.ok and page.status == 200 and page.body):
        raise GamerallPageUnreadable(f"réponse inattendue : {page.status or page.error}")
    m = _PAGE_REGION_RE.search(html.unescape(page.body))
    if not m:
        raise GamerallPageUnreadable(
            "aucune valeur « Region » sur la page (changement de gabarit ?) — "
            "on ne se replie pas sur GLOBAL")
    return m.group(1).strip()


def offer_signals(url: str, name: str = "",
                  http_get_fn: Callable[..., Any] = http_get) -> MerchantOfferSignals:
    """Hook de configuration : la région, dans cet ordre — TITRE, puis URL, puis la page.

    L'ordre est la consigne de Romain (2026-09-18) et c'est aussi le moins cher : ouvrir la
    page coûte 550 ko, lire le titre ne coûte rien. Le matcher appelle ce hook pour CHAQUE
    offre ; sur 32 pages, tirer une page par ligne serait déraisonnable.

    Mesuré sur ce marchand : le titre ne donne rien (0 ligne sur 783), l'URL répond pour 82 %,
    la page pour les 18 % restants. Le crible du titre reste en tête parce qu'il est gratuit
    et qu'il couvre le jour où ce feed changera d'habitude.
    """

    platform = url_platform(url) or title_platform(name)
    from_title = title_region(name)
    if from_title is not None:
        return MerchantOfferSignals(platform=platform, region_resolved=True,
                                    region_base=from_title)
    from_url = url_region(url)
    if from_url is not None:
        return MerchantOfferSignals(platform=platform, region_resolved=True,
                                    region_base=from_url)

    label = fetch_page_region(url, http_get_fn)   # dernier recours
    base = PAGE_REGION_TEXT.get(label.upper())
    if base is None:
        # Région lue mais non vendable : le libellé brut part en « forbidden region: … »,
        # dont le routage (Blacklist / garder) est décidé en UN seul endroit.
        return MerchantOfferSignals(platform=platform, region_resolved=True,
                                    region_base=None, region_label=label)
    return MerchantOfferSignals(platform=platform, region_resolved=True, region_base=base)


CONFIG = make_config(
    "Gamerall",
    domain=DOMAIN,
    precheck=precheck,
    resolve_name=resolve_name,
    offer_page_resolver=offer_signals,
    title_is_platform_source=True,
)
