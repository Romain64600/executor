"""Per-merchant configuration — the merchant-specific instructions the pipeline
starts from (Romain 2026-08-11: "on part avec la config marchand").

Merchant-specific handling used to be scattered across the matcher. A
``MerchantConfig`` is the single declarative place for a merchant's rules;
``match_offer`` reads ``merchant_config(offer.merchant)`` and applies it. A
merchant WITHOUT a config falls through to the generic behaviour (platform/region/
edition from the feed title + URL), exactly as before.

Migrated (incremental, no regression): **Kinguin** domain, **Difmark** url-ignore,
**Instant Gaming** offer-page platform resolver, **Gamivo** URL language lock,
**Eneba** URL platform prefixes. Difmark's complex offer-page branch (accounts /
region maps) still lives in ``src.matcher`` and is represented by its config
entry — fold it in when next touched. The consuming code keeps each rule's scope
(e.g. Eneba prefixes apply only on eneba.com) and reads the DATA from here.

This module is pure data (no matcher import) to stay circular-import free — the
registry that binds resolvers lives in ``src.merchants.registry`` (relocated from
``src.matcher`` on 2026-09-14 so that ``src.console_keys`` can consult the merchant hooks
without importing the matcher).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Pattern, Union


@dataclass(frozen=True)
class MerchantOfferSignals:
    """What a merchant's own offer page yields (R32/R33 — Instant Gaming).
    - ``platform``: our platform token (STEAM/EPIC/…) or None (unrecognized → skip).
    - ``region_resolved``: True when the page gave a region → it OVERRIDES the
      title/URL default. False → keep the title-derived region (platform-only).
    - When resolved, exactly one holds:
        * ``region_base`` set (global/eu/us/uk) → ENTER with that region;
        * ``region_base`` None → the offer is region-locked to a region we don't
          enter; ``region_label`` carries the raw region text so the caller emits a
          ``forbidden region: <label>`` skip. The blacklist-vs-park-vs-skip routing
          of that label is decided in ONE merchant-agnostic place
          (``aks_lists.suggest_target_list``) — LATAM / Brazil / Asia / Russia →
          Blacklist (Romain 2026-08-13), the rest → garder."""

    platform: Optional[str] = None
    region_resolved: bool = False
    region_base: Optional[str] = None
    region_label: str = ""


@dataclass(frozen=True)
class MerchantConfig:
    name: str
    # The offer URL must be on this host (Kinguin → kinguin.net). None = no check.
    domain: Optional[str] = None
    # Merchant-specific URL boilerplate stripped before deriving region/edition
    # from the URL (Difmark → "buy-console-account-").
    url_ignore_substrings: tuple[str, ...] = ()
    # When platform/region are not in the feed title, read them from the
    # merchant's own offer page: ``offer_page_resolver(offer_url) ->
    # MerchantOfferSignals``. Raising means the page was unreadable → the caller
    # fails closed. (Instant Gaming: platform from data-platform, region from the
    # page <title> suffix.)
    # ``offer_page_resolver(offer_url, offer_name)`` — le TITRE est passé depuis le
    # 2026-09-18 (Romain : « pour certains marchands on peut avoir une info dans le titre qui
    # n'est pas dans l'URL […] mets un check du titre par défaut avant d'ouvrir la page, ça
    # reste plus opti »). Un résolveur lit donc dans cet ordre : titre, URL, puis la page —
    # et n'ouvre la page que si les deux premiers n'ont rien dit.
    offer_page_resolver: Optional[Callable[..., "MerchantOfferSignals"]] = None
    # Eneba: the URL's leading path segment encodes the platform
    # ("eneba.com/steam-…" → STEAM). {prefix: platform token}.
    url_platform_prefixes: dict[str, str] = field(default_factory=dict)
    # Platform-source control (R32b, 2026-08-27 — Romain: "ça dépend du marchand").
    # By default the merchant TITLE declares the platform. A merchant whose titles are
    # unreliable for the platform sets ``title_is_platform_source=False`` — then the
    # platform comes from the URL/page instead of the title (G2A). ``url_platform_scan``
    # scans the WHOLE URL path for a platform token collocated with the key marker
    # (G2A "…-steam-key-…"), as opposed to ``url_platform_prefixes``' leading segment
    # (Eneba). Kinguin is left title-sourced on purpose (Romain: it works today).
    title_is_platform_source: bool = True
    url_platform_scan: bool = False
    # The MAINTAINED list of "we can't open this merchant's offer page yet" (R32c,
    # 2026-08-28 — Romain: "les marchands [dont] on arrive pas à ouvrir la page … par la
    # suite on travaillera dessus"). G2A hard-blocks non-browser fetches (HTTP 403), so
    # a signal only on its offer page (a green-gift's real platform) is UNVERIFIABLE →
    # fail-closed skip, NOT a guess. Flip to True once page-opening via the browser (CDP)
    # lands. Default True (openable) preserves every other merchant.
    offer_page_readable: bool = True
    # [R51] (2026-09-16, Romain: « avant de decider si publisher ou non on doit ouvrir la page
    # marchant pour verifier la region et l'edition, si on arrive pas a ouvrir la page marchant
    # on skip l'offre … on devrait ajouter cette securite par defaut pour tous les marchants »).
    # True = this merchant's OWN offer page is opened and read to decide whether a key whose
    # title AND url declare no platform is really a PUBLISHER key. Default **False**, i.e. the
    # safety is ON for every merchant: the "Direct Publisher" line of the AKS page describes
    # the GAME, not this merchant's key, so it can no longer carry the decision alone — such a
    # row is refused (R51) instead of being entered PUBLISHER. Flip to True only together with
    # a real page read; no merchant declares it today (every product page we probed on
    # 2026-09-16 is either Cloudflare-403 — Gamivo, Electronicfirst, GamersOutlet, Kinguin,
    # Driffle, G2A — or belongs to a merchant whose resolver already sets the platform upstream).
    publisher_from_merchant_page: bool = False
    # [R56] (2026-09-22, Romain : « pour GOG pas besoin que la page déclare GOG »).
    # R20 refuse une ligne dont la plateforme DÉCLARÉE n'apparaît pas dans les plateformes
    # officielles de la page AKS. Le garde vaut pour un marchand dont la plateforme est LUE
    # dans un titre : une contradiction y signale une mauvaise lecture. Il ne vaut pas pour
    # un marchand MONO-PLATEFORME dont la plateforme vient de son domaine — GOG.com ne vend
    # que du GOG, la liste de la page ne peut pas le contredire, elle peut seulement être
    # incomplète. Mettre False lève ce contrôle POUR CE MARCHAND SEULEMENT.
    #
    # Ne PAS y adjoindre un contrôle « la page porte-t-elle le seau de région ? » : essayé le
    # 2026-09-22, retiré le 23. `extract_regions` rend les régions sous lesquelles le produit
    # est DÉJÀ VENDU (une liste de filtre), pas ce que le formulaire propose — le menu des
    # régions est un CATALOGUE GLOBAL, identique pour tous les produits, résolu en direct par
    # le soumetteur. Le contrôle refusait 136 lignes sur 250 pour une case qui existe.
    require_page_platform: bool = True
    # Generic-behaviour OVERRIDE hooks (Romain 2026-09-10: « un fichier de config marchand
    # par marchand, qui peut ajouter, overwrite, modifier des comportements génériques »).
    # Each is optional; the matcher calls it FIRST and falls through to the generic rule
    # when it returns None. All pure functions of the feed row (no network).
    #   precheck(name, url) -> skip reason | None   — an extra categorical skip, evaluated
    #       right after the domain check (before the generic console/region/category scans).
    #   title_region(name) -> "eu" | "us" | "uk" | "global" | None — the region the
    #       merchant's title grammar declares; wins over the generic title/URL scan.
    #   resolve_name(name) -> str — the text handed to AKS resolution (slug guessing +
    #       site search) instead of the raw title; e.g. a grammar tail peeled off.
    #   url_platform(url) -> platform token | None — the platform the merchant's URL
    #       grammar declares (our token STEAM/GOG/EPIC/UBISOFT/EA/BATTLENET/ROCKSTAR/
    #       MICROSOFT) or None; consulted FIRST by ``explicit_platform_from_url``, before
    #       the ``url_platform_prefixes`` / ``url_platform_scan`` modes ([R46], 2026-09-12:
    #       Gamivo "…-pc-steam-us-standard" — the platform run sits between the game slug
    #       and the region code, neither a leading segment nor collocated with "key").
    #   guard_name(name) -> str — the merchant title the IDENTITY guards read for a PC row
    #       (R01 missing AKS words, R16 extra words, R01b dangerous qualifier) and
    #       ``detect_edition``: the RAW title by default (every merchant without the hook,
    #       unchanged). A merchant whose grammar appends a note that is NOT a product word
    #       strips that note here — and ONLY it (Romain's rulings of 2026-09-14: « Kinguin
    #       valid until juin 2027 on rentre » → Kinguin "(valid until <Month> <Year>)",
    #       trailing only; « Steam Altergift = Steam Gift on rentre » → the delivery word
    #       "Altergift", K4G and Kinguin). The hook can never launder a title past the name
    #       gate: the game words it leaves are still compared with the AKS name, and an
    #       empty answer falls back to the raw title.
    #   gift_delivery(name, url) -> bool | None — the merchant's OWN gift-delivery verdict,
    #       layered by ``detect_region`` as the platform's GIFT bucket (Steam 25 / gift_eu
    #       259 / 2577 / 2572, Battle.net 570 / 567 / 568, Ubisoft 501 / 504 / 505 — the US /
    #       UK buckets were mapped on 2026-09-16 ([R50], Romain: « si ça existe le fichier
    #       marchand ne devrait pas affirmer le contraire »); a base a platform really lacks
    #       (an EA / Epic / GOG / Publisher / Rockstar plain gift, a Battle.net gift UK) still
    #       yields the fail-closed "no region id" skip). True / False wins; None → the generic read (a "gift" URL
    #       segment, " GIFT " / "GIFT)" in the title). K4G / Kinguin: a "… Steam Altergift"
    #       row whose URL agrees → True (Romain 2026-09-14: « on rentre sous gift tous les
    #       altergifts »). The hook reads BOTH arguments: a title / URL delivery conflict
    #       (title Altergift, slug "-cd-key") or a non-Steam Altergift is never a verdict —
    #       it is the merchant ``precheck``'s fail-closed skip (review fixes 2026-09-14), so
    #       no row is filed under a bucket class the row itself contradicts.
    # MMOGA uses the first three ("<Product> <CODE> Key", src/merchants/mmoga.py); Gamivo
    # uses the first four (src/merchants/gamivo.py); Kinguin and K4G add guard_name +
    # gift_delivery (2026-09-14).
    precheck: Optional[Callable[[str, str], Optional[str]]] = None
    title_region: Optional[Callable[[str], Optional[str]]] = None
    resolve_name: Optional[Callable[[str], str]] = None
    url_platform: Optional[Callable[[str], Optional[str]]] = None
    guard_name: Optional[Callable[[str], str]] = None
    gift_delivery: Optional[Callable[[str, str], Optional[bool]]] = None
    #   account_row(name, url) -> bool — « chez ce marchand, cette ligne est un COMPTE »
    #       (Romain, 2026-09-21 : « elle ne doit pas continuer à passer par la branche
    #       console, elle doit être routée vers une branche compte »). Une ligne qui répond
    #       True NE PASSE PAS par le classifieur console : le compte est le PRODUIT vendu,
    #       pas un marqueur non-jeu. La branche compte dispatche ensuite selon le TYPE de
    #       compte (page + seau AKS dédiés) — Steam seul est confirmé aujourd'hui, les
    #       autres tombent sur un refus qui NOMME ce qui manque, prêt à être complété le
    #       jour où l'on trouve une page « Epic Account » / « PS4 Account » dans AKS.
    #       Défaut None = comportement d'avant, inchangé pour tous les autres marchands.
    account_row: Optional[Callable[[str, str], bool]] = None
    # Console-side hooks (R32 / R45, 2026-09-14 — Romain: « pour la détection région /
    # édition / plateforme, tu as un fichier de config par marchand. Et si tu ne l'as pas,
    # tu dois l'avoir. »). The shared classifier ``src.console_keys.classify_console`` owns
    # the SHARED vocabulary only (platform phrase grammar, families, buckets, non-game and
    # store/delivery markers, region text → base/label mapping); everything a merchant
    # writes in its OWN way is declared here. All optional, all pure functions of the feed
    # row (no network, no matcher import); a merchant without them gets the shared reading.
    #   console_url_families(url) -> tuple of families | skip reason | None — the
    #       families the merchant's URL grammar declares, in order (a subset of XBOX_ONE /
    #       XBOX_SERIES / PS4 / PS5 / SWITCH / SWITCH2 — never XBOX_PC), or a fail-closed
    #       "console: … (R45)" skip reason ("console: Xbox 360 (R45)", "console: PC-only
    #       Xbox Live key (R45)", "console: <MARKER> — not a game (R45)"), or None when the
    #       URL says nothing. Consulted ONLY when the title declares no family; it REPLACES
    #       the shared hyphen-run slug reading for that merchant (MMOGA category segment,
    #       Gamivo fused runs, Eneba slot before the store-key marker).
    #   console_pc_declared(name, url) -> bool — the merchant declares PC / Windows NEXT TO
    #       the console platform in its own grammar (Gamivo "-pc" / "-windows" runs, Eneba
    #       "-windows-" before the run); OR-ed with the shared title phrase check
    #       ("/ Windows", "PC/XBOX …"), which stays generic.
    #   console_region_slot(name) -> str | None — the region TEXT the merchant writes next
    #       to the platform phrase, verbatim ("US", "CA", "Europe", "United Kingdom",
    #       "Hong Kong", "EUROPE"); the mapping text → base (eu/us/uk/global) or forbidden
    #       label stays in ``src.console_keys`` (shared vocabulary). None → the classifier
    #       falls back to its shared tail / bracket reads.
    #   console_noise — merchant phrases stripped from ``resolve_name`` in addition to the
    #       shared store / delivery markers ("Download Code" MMOGA, "Digital Key" /
    #       "Digital Code" Driffle, "(valid until <Month> <Year>)" Kinguin — a Pattern,
    #       entered since Romain's ruling of 2026-09-14). A ``str`` is a LITERAL phrase
    #       (case-insensitive, whole words, any whitespace between the words); a compiled
    #       ``re.Pattern`` is used as written (its own flags) — for the forms a literal
    #       cannot spell (Gamivo's "EN" / "EN/PL/CS" language tail, Kinguin's note).
    # MMOGA / Gamivo / Eneba declare theirs in src/merchants/<name>.py.
    console_url_families: Optional[Callable[[str], Optional[Union[tuple[str, ...], str]]]] = None
    console_pc_declared: Optional[Callable[[str, str], bool]] = None
    console_region_slot: Optional[Callable[[str], Optional[str]]] = None
    console_noise: tuple[Union[str, Pattern[str]], ...] = ()
    # Free-form notes / extension point for future per-merchant knobs.
    notes: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
