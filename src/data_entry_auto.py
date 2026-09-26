"""Safe-auto data-entry sweep engine (pure, testable core) — v2.

Romain's "mode rapide safe auto" (2026-08-04): for a merchant, sweep the feed
page by page — extract → match → auto-approve EVERY matcher candidate → submit
(``--mode safe``) — with NO human validation, keeping a per-page recap. The
matcher is the safety gate (it already skips console / no-AKS-page / ambiguous
offers); Romain audits the recap and deletes any mistake afterwards.

This module is the deterministic loop ONLY — every side-effecting stage is
injected, so the loop's stop conditions and recap shape are unit-tested without a
browser. ``scripts/10_data_entry_auto.py`` wires the real stages.

Design after the 2026-08-04 adversarial review (which found real defects):

* REFLOW-SAFE HIGHEST-FIRST. Creating an offer removes it from the merchant
  feed, so the feed SHRINKS as we submit. Paging 1→N positionally would let
  offers slide down into already-processed pages and be skipped. We instead
  process pages from the feed's advertised last page DOWN to the first (like the
  P1.6 mover): removing offers from a higher page never shifts a LOWER,
  not-yet-processed page. ``feed_last_page`` comes from the extractor (authoritative
  nav), never the offers<page_size proxy (a throttled short page must not be read
  as end-of-feed).

* FAIL-CLOSED on EVERY non-clean stage — including a mid-batch submitter STOP.
  The submitter signals a broken session mid-page via ``stopped`` (feed_unreadable
  / guard_blocked / ten_consecutive_failures), NOT ``aborted``; both must halt the
  whole sweep. ``limit_reached`` is the only benign ``stopped`` (never in safe
  mode). A NotLoggedIn/feed-unreadable is a STOP, never an auto re-auth — with ONE
  bounded exception since 2026-09-24: a failure where NOTHING can have been written (a
  transient extract error, a submit stopped before any Create click, a failed pre-flight
  index scan) redoes the page after a pause, three times at most (TRANSIENT_SIGNATURES).

* COVERAGE HONESTY. Hitting the ``max_pages`` cap while the feed advertises more
  pages (or a feed that grew mid-sweep) is recorded in the recap's ``coverage``
  field (``incomplete_max_pages`` / ``incomplete_feed_grew``), never a silent clean
  end — but it is NOT a halt (audit 2026-09-09): the sweep is clean, a multi-merchant
  batch continues and the process exits 0.

* OPERATOR STOP is re-checked between stages (and before the real submit), so a
  stop that lands mid-page still prevents that page's writes when it can.

* LA PAGE EN COURS SE VOIT (Romain, 2026-09-26 : « 4. Go »). ``recap["current"]`` dit la
  page qu'on traite, son run et son ÉTAPE (``probe`` / ``extract`` / ``match`` / ``submit``
  / ``move`` / ``pause``), remis à ``None`` dès qu'elle finit ; ``on_progress`` est appelé à
  chaque changement d'étape. Sans lui, la console restait sur « 0 offres créées · 0
  marchand » pendant toute la première page — une heure pour Gamesplanet FR le 25/09 (52
  saisies à ~58 s). Pur affichage : rien ici ne décide d'une écriture, et un ``on_progress``
  qui lève est ignoré.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.admin.auto_merchants import rejection_reason
from src.validation import candidate_fingerprint

# ``stopped`` values that are NOT a broken/blocked session. ``limit_reached``
# never occurs in safe mode (no limit); ``operator_stop`` = a cooperative stop the
# submitter honored at an offer boundary — its partial page is recorded clean and
# the sweep then halts via its OWN should_stop() check. Every OTHER stopped value
# (feed_unreadable / guard_blocked / ten_consecutive_failures) halts fail-closed.
_BENIGN_STOPPED = {"limit_reached", "operator_stop"}

# REPRISE APRÈS UNE ERREUR PASSAGÈRE (Romain, 2026-09-24 : « pour Wyrel j'ai dû relancer 3 fois,
# tu vois pas le pb ? », puis « go pour les deux correctifs »). Le 24/09, trois arrêts du même
# balayage, tous passagers et tous SANS écriture en jeu : 12:04 et 14:41 une page du feed qui ne
# répond pas en 20 s pendant l'extraction (`CdpTimeoutError`), 14:00 AKS qui refuse la connexion
# (`net::ERR_CONNECTION_REFUSED`) avant tout clic sur « Create ». Chacun arrêtait le balayage et
# Romain relançait à la main. On refait désormais LA PAGE après une pause — seulement quand rien
# n'a pu être écrit : un extract en échec (lecture seule) sur une de ces signatures, un submit
# arrêté AVANT tout clic (`feed_unreadable_prewrite`, src/submitter.py) ou dont le scan d'index
# d'avant la première offre a échoué (`aborted == "feed_unreadable"`). Un doute APRÈS un clic
# (`feed_unreadable` = état INCONNU), une déconnexion, un garde, dix échecs d'affilée, un échec
# de match ou d'approbation restent des haltes immédiates.
TRANSIENT_SIGNATURES = (
    "CdpTimeoutError",
    "net::ERR_CONNECTION_REFUSED", "net::ERR_CONNECTION_RESET", "net::ERR_CONNECTION_CLOSED",
    "net::ERR_TIMED_OUT", "net::ERR_EMPTY_RESPONSE", "net::ERR_NETWORK_CHANGED",
    "net::ERR_INTERNET_DISCONNECTED", "net::ERR_ADDRESS_UNREACHABLE",
    "net::ERR_NAME_NOT_RESOLVED",
)
# Le submit n'a rien écrit : aucun clic sur « Create » (src/submitter.py), ou le scan d'index
# d'avant la première offre a échoué.
_PREWRITE_STOPPED = {"feed_unreadable_prewrite"}
_PREWRITE_ABORTED = {"feed_unreadable"}


def transient_reason(detail: str | None) -> str | None:
    """La signature passagère trouvée dans un détail d'échec, ou None. Une déconnexion
    (« not logged in ») n'est JAMAIS passagère : elle arrête tout, comme avant."""

    text = str(detail or "")
    if "not logged in" in text.lower():
        return None
    for sig in TRANSIENT_SIGNATURES:
        if sig in text:
            return sig
    return None


def _halt_label(stage_label: str, should_stop: Callable[[], bool]) -> str:
    """Le motif de halte d'un étage qui vient d'échouer — « operator_stop » si c'est NOUS qui
    l'avons tué.

    2026-09-19, vécu en direct. Romain clique « Arrêter » pour réordonner ses marchands ; le
    stop SIGTERM l'enfant du stage en vol, l'étage rend ``exit -15``, et le sweep l'a étiqueté
    ``GameSeal: match_failed_p103`` — un arrêt DÉLIBÉRÉ présenté comme une panne fail-closed,
    avec un code de sortie 2. Romain a naturellement demandé ce qui était cassé : rien. Les
    trois étages testaient déjà ``should_stop()`` AVANT de se lancer, mais aucun ne le
    re-testait APRÈS un échec — or c'est précisément là que l'information arrive, puisque le
    signal a été reçu pendant l'attente. Un arrêt demandé est un arrêt demandé, quel que soit
    l'étage qui en meurt."""

    return "operator_stop" if should_stop() else stage_label


@dataclass
class SweepConfig:
    merchant: str
    store_id: str
    start_page: int = 1
    # None = TOUTES les pages que le feed annonce (Romain 2026-09-18 : « je ne veux pas
    # couvrir les marchands seulement sur 10 pages, on fait toutes les pages sauf lors d'un
    # arrêt pour sécurité »). Un entier garde l'ancien plafond.
    max_pages: int | None = 30  # shallow-index cap, same default as scripts/10 --max-pages (the
                              # submit index is only productive on the ~28-30 shallowest pages)
    # [R45] match the pages WITH the console branch (03_match --consoles). Default ON since
    # Romain's decision « 1 » of 2026-09-15 (consoles by default everywhere, after the two
    # modal-v2 canaries and the MMOGA console dry-run); False = a PC-only sweep (scripts/10
    # --no-consoles: console rows keep the 'console' skip). Recorded in the recap so an
    # audit can tell a console sweep from a PC one.
    consoles: bool = True
    # Pauses avant de REFAIRE une page après une erreur passagère (voir TRANSIENT_SIGNATURES) :
    # 2, 5 puis 10 min — au plus trois reprises par page, ensuite la halte d'avant.
    transient_retry_waits: tuple[float, ...] = (120.0, 300.0, 600.0)


@dataclass
class ExtractOutcome:
    ok: bool
    offers: int = 0
    feed_last_page: int | None = None   # authoritative last page from the extractor's nav
    detail: str = ""


@dataclass
class MatchOutcome:
    ok: bool
    candidates: int = 0
    movable: int = 0          # routable skips on this page (→ Move-to-List step)
    probe_unreliable: int = 0  # offers skipped on an unreliable AKS probe (below the abort bar)
    detail: str = ""


@dataclass
class SubmitOutcome:
    ok: bool                              # process finished clean (exit 0)
    aborted: str | None = None            # submit_plan.aborted (pre-write abort)
    stopped: str | None = None            # submit_plan.stopped (mid-batch stop signal)
    created: int = 0                      # offers proven gone-from-feed
    offers: list[dict[str, Any]] = field(default_factory=list)
    detail: str = ""

    def clean(self) -> bool:
        """A submit is clean only if it exited 0, did not abort, and did not stop
        on a broken/blocked session (a non-benign ``stopped``)."""
        if not self.ok or self.aborted:
            return False
        return not (self.stopped and self.stopped not in _BENIGN_STOPPED)

    def halt_reason(self) -> str | None:
        if not self.ok:
            return self.detail or "exit≠0"
        if self.aborted:
            return self.aborted
        if self.stopped and self.stopped not in _BENIGN_STOPPED:
            return self.stopped
        return None


@dataclass
class MoveOutcome:
    """Result of a page's Move-to-List step (the routable skips → their target
    lists). Same clean/halt discipline as :class:`SubmitOutcome` — a move that does
    not finish clean halts the whole sweep fail-closed (a broken/blocked session
    must not let later pages plow through)."""
    ok: bool                              # process finished clean (exit 0)
    aborted: str | None = None            # move plan aborted (pre-write abort / gate)
    stopped: str | None = None            # mid-batch stop signal
    moved: int = 0                        # offers proven relocated (RV2: gone-from-source)
    offers: list[dict[str, Any]] = field(default_factory=list)
    detail: str = ""

    def clean(self) -> bool:
        if not self.ok or self.aborted:
            return False
        return not (self.stopped and self.stopped not in _BENIGN_STOPPED)

    def halt_reason(self) -> str | None:
        if not self.ok:
            return self.detail or "exit≠0"
        if self.aborted:
            return self.aborted
        if self.stopped and self.stopped not in _BENIGN_STOPPED:
            return self.stopped
        return None


@dataclass
class Stages:
    """Injected side-effecting stages, each keyed by the page's run id."""
    extract: Callable[[int, str], ExtractOutcome]     # (page, run_id) -> ExtractOutcome
    match: Callable[[str], MatchOutcome]              # (run_id) -> MatchOutcome
    approve: Callable[[str], int]                     # (run_id) -> approved_count (raises on failure)
    submit: Callable[[str], SubmitOutcome]            # (run_id) -> SubmitOutcome
    # Optional Move-to-List step: relocate the page's routable skips to their target
    # lists AFTER the ADDs are submitted+verified (Romain 2026-08-13, unified
    # per-page workflow). None = ADD-only sweep (unchanged legacy behaviour).
    move: Callable[[str], MoveOutcome] | None = None
    # Les offer_id extraits d'une page, pour mesurer la couverture RÉELLE (2026-09-20).
    # None = mesure indisponible (le balayage se comporte alors exactement comme avant).
    offer_ids: Callable[[str], tuple[str, ...]] | None = None
    # Avant de REFAIRE une page (reprise passagère), mettre de côté les traces d'écriture de
    # la tentative ratée — (run_id, n° de tentative). None = rien à conserver (tests).
    archive_attempt: Callable[[str, int], None] | None = None


class StageError(Exception):
    """A stage (e.g. auto-approve) failed — recorded as a fail-closed halt."""


def _utc_stamp() -> str:
    """Le format des ``ts`` des journaux de page (``2026-09-25T16:05:15Z``) : la console
    compare les deux."""

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_sweep(
    cfg: SweepConfig,
    stages: Stages,
    *,
    page_run_id: Callable[[int], str],
    should_stop: Callable[[], bool] = lambda: False,
    on_page: Callable[[dict[str, Any]], None] = lambda e: None,
    sleep: Callable[[float], None] = time.sleep,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    clock: Callable[[], str] = _utc_stamp,
) -> dict[str, Any]:
    """Sweep a merchant's feed reflow-safe (highest page first), halting fail-closed.

    Returns ``{merchant, store_id, pages:[…], total_created, total_moved, halted,
    feed_last_page, coverage}`` — ``coverage`` (set only when ``halted`` is None) is
    ``None`` | ``'incomplete_max_pages (feed has N pages)'`` | ``'incomplete_feed_grew
    (a→b pages)'``; a page entry may carry ``probe_unreliable`` (unreliable-probe skips).
    ``on_page`` is called after each page with the LIVE recap dict (mutated in
    place) so the caller can persist per-page progress before the sweep returns.
    ``on_progress`` (optional) gets the same dict at every STAGE change of the page in
    progress (``recap["current"]``, 2026-09-26) — display only, its exceptions are
    swallowed; ``clock`` stamps those changes.
    """

    recap: dict[str, Any] = {
        "merchant": cfg.merchant, "store_id": cfg.store_id,
        "pages": [], "total_created": 0, "total_moved": 0,
        "halted": None, "feed_last_page": None, "coverage": None,
        "consoles": bool(cfg.consoles),        # [R45] matched with the console branch?
        # AUDIT DU 2026-09-20. Le balayage annonçait « 58 pages faites » sans jamais
        # regarder CE QU'ELLES CONTENAIENT : sur 20260919-082932, les pages 86→73 ont rendu
        # QUATORZE FOIS la même centaine d'offres (empreinte identique, skipped.json
        # byte-identiques), 58→53 six fois de plus — 5861 lignes lues pour 2059 distinctes,
        # 65 % de relecture, et un recap qui disait « couverture : rien à signaler ». Le
        # submitter avait déjà la garde (src/submitter.py : deux pages sans id NOUVEAU
        # terminent la marche) ; l'orchestrateur, lui, comptait des pages. On mesure
        # désormais les OFFRES : `new_offers` par page, et la liste des pages qui n'ont
        # rien apporté. Ce n'est PAS une halte (une page vraiment vide est légitime) —
        # c'est la vérité sur la couverture, que `coverage` refusait de dire.
        "distinct_offers": 0, "pages_without_new_offers": [],
        # Reprises après une erreur passagère (2026-09-24) : leur nombre, pour la console.
        "transient_retries": 0,
        # La page EN COURS (2026-09-26) : {page, run, since, stage, stage_at} + ce que
        # l'étape sait déjà (offers, candidates, approved, movable, attempt, wait_s,
        # reason). None entre deux pages et à la fin.
        "current": None,
    }

    waits = tuple(cfg.transient_retry_waits or ())

    def show(stage: str, page: int, run_id: str, **fields: Any) -> None:
        """Pose l'étape de la page en cours et prévient ``on_progress``. Une (nouvelle)
        tentative — ``probe`` / ``extract``, seules étapes qui suivent une pause — repart
        d'une fiche vierge : seul ``since``, l'heure du premier essai de CETTE page, survit.
        Jamais une raison d'échouer."""

        now = clock()
        cur = recap.get("current")
        if not (isinstance(cur, dict) and cur.get("page") == page and cur.get("run") == run_id):
            cur = {"page": page, "run": run_id, "since": now}
        if stage in ("probe", "extract"):
            cur = {"page": page, "run": run_id, "since": cur.get("since") or now}
        cur.update(fields)
        cur["stage"] = stage
        cur["stage_at"] = now
        recap["current"] = cur
        if on_progress is not None:
            try:
                on_progress(recap)
            except Exception:   # noqa: BLE001 — un affichage n'arrête jamais un balayage
                pass

    def pause(seconds: float) -> bool:
        """Attend ``seconds`` par tranches de 5 s au plus, en surveillant l'arrêt opérateur :
        « Arrêter » reste immédiat pendant une pause de dix minutes. False = arrêt demandé."""

        restant = float(seconds)
        while restant > 0:
            if should_stop():
                return False
            tranche = min(5.0, restant)
            sleep(tranche)
            restant -= tranche
        return not should_stop()

    def finish_page(entry: dict[str, Any]) -> None:
        recap["current"] = None          # la page est finie : plus rien « en cours »
        recap["pages"].append(entry)
        recap["total_created"] = sum(p.get("created", 0) for p in recap["pages"])
        recap["total_moved"] = sum(p.get("moved", 0) for p in recap["pages"])
        on_page(recap)   # the LIVE recap (this dict, mutated in place) — so a
                         # caller can persist per-page progress before the sweep
                         # returns (the console's live recap panel).

    if should_stop():
        recap["halted"] = "operator_stop"
        return recap

    # Probe the start page to learn the feed's authoritative last page.
    probe_id = page_run_id(cfg.start_page)
    probe_retries: list[dict[str, Any]] = []
    while True:
        show("probe", cfg.start_page, probe_id)
        probe = stages.extract(cfg.start_page, probe_id)
        if probe.ok:
            break
        why = transient_reason(probe.detail)
        n = len(probe_retries)
        if why is None or n >= len(waits) or should_stop():
            break
        probe_retries.append({"attempt": n + 1, "wait_s": waits[n], "stage": "extract",
                              "reason": str(probe.detail or why)[:300]})
        recap["transient_retries"] += 1
        on_page(recap)
        show("pause", cfg.start_page, probe_id, wait_s=waits[n],
             reason=str(probe.detail or why)[:160])
        if not pause(waits[n]):
            break
    if not probe.ok:
        recap["halted"] = _halt_label(f"extract_failed_p{cfg.start_page}", should_stop)
        if probe.detail:
            recap["halted_detail"] = probe.detail      # the WHY, surfaced by the console/monitor
        entry = {"page": cfg.start_page, "run": probe_id, "offers": probe.offers,
                 "error": "extract: " + (probe.detail or "failed")}
        if probe_retries:
            entry["transient_retries"] = probe_retries
        finish_page(entry)
        return recap
    feed_last = probe.feed_last_page if probe.feed_last_page else cfg.start_page
    recap["feed_last_page"] = feed_last
    if probe.offers == 0 and feed_last <= cfg.start_page:
        finish_page({"page": cfg.start_page, "run": probe_id, "offers": 0, "end_of_feed": True})
        return recap

    # `max_pages=None` : on couvre tout ce que le feed annonce. Seul un arrêt fail-closed
    # (extract/match/submit en échec, stop opérateur) écourte alors la passe — la couverture
    # ne peut plus être rognée en silence par un plafond.
    top = (feed_last if cfg.max_pages is None
           else min(feed_last, cfg.start_page + cfg.max_pages - 1))
    capped = feed_last > top
    max_seen = feed_last   # largest feed_last_page any extract advertised (feed growth)

    # Highest page first (reflow-safe): a higher page's removals never shift a
    # lower, not-yet-processed page.
    seen_offer_ids: set[str] = set()

    def measure_coverage(entry: dict[str, Any], run_id: str) -> None:
        """`new_offers` = les ids que cette page apporte et qu'aucune n'avait apportés."""
        if stages.offer_ids is None:
            return
        try:
            ids = [str(i) for i in stages.offer_ids(run_id) if i]
        except Exception:
            return                       # une mesure n'est jamais une raison d'échouer
        if not ids:
            return
        fresh = [i for i in ids if i not in seen_offer_ids]
        entry["new_offers"] = len(fresh)
        seen_offer_ids.update(ids)
        recap["distinct_offers"] = len(seen_offer_ids)
        if not fresh:
            entry["repeated_page"] = True
            pages = recap["pages_without_new_offers"]
            if entry["page"] not in pages:
                pages.append(entry["page"])

    def attempt_page(page: int, run_id: str, entry: dict[str, Any]) -> tuple[str, str | None]:
        """UNE tentative d'une page. Rend ``("next", None)`` (page finie, on continue),
        ``("halt", None)`` (halte fail-closed, page finie) ou ``("retry", motif)`` : un échec
        PASSAGER sans écriture en jeu — la page n'est PAS finie, l'appelant décide de la
        refaire. Les champs de halte (`entry["error"]`, `recap["halted"]`) sont posés dans
        les trois cas d'échec : si les reprises sont épuisées, la halte est déjà écrite."""

        nonlocal max_seen
        essais = len(entry.get("transient_retries") or [])
        show("extract", page, run_id, **({"attempt": essais + 1} if essais else {}))
        ex = stages.extract(page, run_id)
        entry["offers"] = ex.offers
        if ex.feed_last_page and ex.feed_last_page > max_seen:
            max_seen = ex.feed_last_page   # a re-import grew the feed mid-sweep
        if not ex.ok:
            entry["error"] = "extract: " + (ex.detail or "failed")
            recap["halted"] = _halt_label(f"extract_failed_p{page}", should_stop)
            if ex.detail:
                recap["halted_detail"] = ex.detail
            why = transient_reason(ex.detail)
            if why is not None and recap["halted"] != "operator_stop":
                entry["retry_stage"] = "extract"
                return "retry", str(ex.detail or why)[:300]
            finish_page(entry)
            return "halt", None
        measure_coverage(entry, run_id)
        if ex.offers == 0:
            entry["empty"] = True   # feed shrank past this page — nothing to do here
            finish_page(entry)
            return "next", None
        if entry.get("repeated_page"):
            # Romain, 2026-09-24 : « go pour sauter les pages vides ». Une page dont TOUTES les
            # offres ont déjà été servies par une page précédente de CE balayage n'a rien à
            # apprendre : chacune a déjà été matchée, et saisie ou refusée. La refaire ne coûte
            # que du temps et des sondes — et rejoue les échecs : « Conclave » (Wyrel, refus
            # déterministe d'AKS) a été retentée sur les pages 44, 43, 42 et 41 du 24/09. Mesuré
            # le même jour : Kinguin 44 pages sur 120 dans ce cas, GameSeal 51 sur 208. Une page
            # PARTIELLEMENT neuve, ou dont la mesure manque (`offer_ids` absent ou en échec),
            # est traitée comme avant.
            entry["skipped_repeated"] = True
            entry["candidates"] = 0
            entry["created"] = 0
            entry["offers_created"] = []
            finish_page(entry)
            return "next", None

        show("match", page, run_id, offers=ex.offers)
        mt = stages.match(run_id)
        entry["candidates"] = mt.candidates
        if mt.movable:
            entry["movable"] = mt.movable
        if mt.probe_unreliable:
            entry["probe_unreliable"] = mt.probe_unreliable   # a throttled page ≠ an empty one
        if not mt.ok:
            entry["error"] = "match: " + (mt.detail or "failed")
            recap["halted"] = _halt_label(f"match_failed_p{page}", should_stop)
            finish_page(entry)
            return "halt", None

        if mt.candidates > 0:
            if should_stop():   # re-check right before any real write
                entry["stopped_before_submit"] = True
                recap["halted"] = "operator_stop"
                finish_page(entry)
                return "halt", None
            try:
                entry["approved"] = stages.approve(run_id)
            except StageError as exc:
                entry["error"] = "approve: " + str(exc)
                recap["halted"] = _halt_label(f"approve_failed_p{page}", should_stop)
                finish_page(entry)
                return "halt", None
            show("submit", page, run_id, candidates=mt.candidates, approved=entry["approved"])
            sub = stages.submit(run_id)
            entry["created"] = sub.created
            entry["offers_created"] = sub.offers
            entry["aborted"] = sub.aborted
            entry["stopped"] = sub.stopped
            if not sub.clean():
                entry["error"] = "submit: " + (sub.halt_reason() or "not clean")
                recap["halted"] = f"submit_not_clean_p{page}"
                if should_stop():
                    finish_page(entry)
                    return "halt", None
                if sub.stopped in _PREWRITE_STOPPED or (
                        sub.aborted in _PREWRITE_ABORTED and not sub.stopped):
                    # Rien n'a été écrit sur l'offre en échec (voir TRANSIENT_SIGNATURES) ;
                    # les offres créées AVANT elle sur cette page sont prouvées et gardées.
                    entry["retry_stage"] = "submit"
                    return "retry", str(sub.stopped or sub.aborted)
                finish_page(entry)
                return "halt", None
        else:
            entry["created"] = 0
            entry["offers_created"] = []

        # Move-to-List: after the ADDs are submitted+verified, relocate this page's
        # routable skips (blacklist regions, softwares, gift cards, …) to their
        # target lists. Runs even when the page had 0 ADDs — a page can be all
        # skips. Fail-closed like submit: an unclean move halts the whole sweep.
        if stages.move is not None and mt.movable > 0:
            if should_stop():   # re-check right before any real write
                entry["stopped_before_move"] = True
                recap["halted"] = "operator_stop"
                finish_page(entry)
                return "halt", None
            show("move", page, run_id, movable=mt.movable)
            mv = stages.move(run_id)
            entry["moved"] = mv.moved
            entry["offers_moved"] = mv.offers
            entry["move_aborted"] = mv.aborted
            entry["move_stopped"] = mv.stopped
            if not mv.clean():
                entry["error"] = "move: " + (mv.halt_reason() or "not clean")
                recap["halted"] = f"move_not_clean_p{page}"
                finish_page(entry)
                return "halt", None

        finish_page(entry)
        return "next", None

    for page in range(top, cfg.start_page - 1, -1):
        if should_stop():
            recap["halted"] = "operator_stop"
            break
        run_id = page_run_id(page)
        retries: list[dict[str, Any]] = []
        carried_created = 0
        carried_offers: list[dict[str, Any]] = []
        # La mesure de couverture d'une tentative ratée ne doit pas faire passer sa
        # reprise pour une page « déjà vue » (elle serait sautée sans rien refaire).
        seen_before = set(seen_offer_ids)
        repeated_before = list(recap["pages_without_new_offers"])
        distinct_before = recap["distinct_offers"]
        while True:
            entry: dict[str, Any] = {"page": page, "run": run_id}
            if retries:
                entry["transient_retries"] = list(retries)
            verdict, motif = attempt_page(page, run_id, entry)
            if verdict == "retry":
                n = len(retries)
                if n < len(waits) and not should_stop():
                    carried_created += int(entry.get("created") or 0)
                    carried_offers += list(entry.get("offers_created") or [])
                    retries.append({"attempt": n + 1, "wait_s": waits[n],
                                    "stage": entry.get("retry_stage"), "reason": motif,
                                    "created_before": int(entry.get("created") or 0)})
                    recap["transient_retries"] += 1
                    recap["halted"] = None
                    recap.pop("halted_detail", None)
                    seen_offer_ids.clear()
                    seen_offer_ids.update(seen_before)
                    recap["pages_without_new_offers"][:] = repeated_before
                    recap["distinct_offers"] = distinct_before
                    if stages.archive_attempt is not None:
                        try:
                            stages.archive_attempt(run_id, n + 1)
                        except Exception:   # noqa: BLE001 — une trace mise de côté n'est jamais une halte
                            pass
                    on_page(recap)
                    show("pause", page, run_id, wait_s=waits[n], reason=str(motif or "")[:160])
                    if pause(waits[n]):
                        continue
                    recap["halted"] = "operator_stop"
                    # REVUE DE ROMAIN (2026-09-25, [P2]) : « deux créations avant l'erreur
                    # deviennent quatre si l'opérateur arrête pendant la pause ». Les créations de
                    # CETTE tentative viennent d'être reportées dans `carried_*` : l'entrée ne
                    # les ajoute pas une seconde fois.
                    entry["created"] = carried_created
                    entry["offers_created"] = list(carried_offers)
                    finish_page(entry)
                    verdict = "halt"
                    break
                # Reprises épuisées : la halte d'avant.
                verdict = "halt"
                if carried_created or carried_offers:
                    entry["created"] = int(entry.get("created") or 0) + carried_created
                    entry["offers_created"] = carried_offers + list(entry.get("offers_created") or [])
                finish_page(entry)
            elif carried_created or carried_offers:
                # La page a fini (ou s'est arrêtée) sur une reprise : ses créations d'avant la
                # coupure comptent — elles sont prouvées, et le recap les doit.
                entry["created"] = int(entry.get("created") or 0) + carried_created
                entry["offers_created"] = carried_offers + list(entry.get("offers_created") or [])
                recap["total_created"] = sum(p.get("created", 0) for p in recap["pages"])
                on_page(recap)
            break
        if verdict == "halt":
            break

    # Coverage honesty: a max_pages cap over a longer feed, OR a feed that GREW past the
    # probed last page mid-sweep (a re-import), is NOT a full sweep — the tail pages beyond
    # ``top`` were never processed. Recorded in ``coverage``, never a silent clean end (the
    # operator re-runs deeper / on the fresh feed to catch the tail). Audit 2026-09-09: this
    # used to be a ``halted`` fail-closed halt, which with the default --max-pages 30 stopped
    # EVERY multi-merchant batch on its first deep feed (exit 2, later merchants never swept,
    # run shown as failed). A cap is the expected outcome of the shallow-index default, not
    # a broken session — so it is coverage information, not a halt.
    if recap["halted"] is None:
        if capped:
            recap["coverage"] = f"incomplete_max_pages (feed has {feed_last} pages)"
        elif max_seen > feed_last:
            recap["coverage"] = f"incomplete_feed_grew ({feed_last}→{max_seen} pages)"
    # Une page qui REDONNE une page déjà lue n'a rien couvert : la pagination du feed a
    # glissé sous le balayage. Dit dans `coverage` (jamais une halte) — un plafond garde la
    # priorité, il décrit la même chose : ce qui n'a pas été vu.
    repeated = recap["pages_without_new_offers"]
    if repeated and recap["coverage"] is None:
        recap["coverage"] = (
            f"incomplete_repeated_pages ({len(repeated)} page(s) sans offre nouvelle : "
            f"{', '.join(str(p) for p in repeated[:12])}"
            f"{'…' if len(repeated) > 12 else ''})"
        )

    recap["current"] = None
    return recap


def preview_incomplete_reason(from_recap: dict) -> "str | None":
    """A by-urls dry-run is submittable ONLY when it is COMPLETE (P2-3, audit
    2026-09-02). Returns a fail-closed reason string when the preview is partial,
    else None. Mirrors the console's incomplete-preview gate (``submit_manager``) so
    the DETERMINISTIC path (``scripts/12`` calling ``run_by_urls_submit`` directly,
    bypassing the HTTP handler) can never ship partial coverage the console would 409:
    a HARD stop (``aborted``), a game that never resolved or carries a per-game
    ``error``, a TRUNCATED search (offers beyond the cap never seen — it *continues*,
    so it never sets ``aborted``), or FEWER game entries than requested (a run
    interrupted on a generic error flushes a short list while leaving aborted=None)."""

    if from_recap.get("aborted"):
        return f"source_aborted: l'aperçu s'est arrêté ({from_recap['aborted']})"
    for g in from_recap.get("games") or []:
        label = g.get("aks_name") or g.get("url") or "?"
        if not g.get("resolved"):
            return f"preview_incomplete: jeu non résolu ({g.get('url') or label})"
        if g.get("error"):
            return f"preview_incomplete: erreur '{g['error']}' sur {label}"
        if (g.get("search") or {}).get("truncated"):
            return f"preview_incomplete: recherche tronquée sur {label}"
    requested = int((from_recap.get("totals") or {}).get("games") or 0)
    got = len(from_recap.get("games") or [])
    if requested and got != requested:
        return f"preview_incomplete: {got}/{requested} jeux traités (aperçu interrompu)"
    return None


def _candidates_by_store(from_recap: dict) -> "list[dict[str, Any]]":
    """Group a by-urls dry-run's candidates by merchant STORE, deduped by
    candidate_fingerprint (a merchant can appear across several games; a re-import
    can also surface the same offer twice). Returns ordered
    ``[{merchant, store_id, candidates:[...]}, ...]`` — the unit of a safe submit."""
    order: list[str] = []
    groups: dict[str, dict[str, Any]] = {}
    for game in from_recap.get("games") or []:
        if not game.get("resolved") or game.get("error"):
            continue
        for per in game.get("merchants") or []:
            sid = str(per.get("store_id") or "")
            if not sid:
                continue
            g = groups.get(sid)
            if g is None:
                g = groups[sid] = {"merchant": per.get("merchant", ""),
                                   "store_id": sid, "candidates": [], "_seen": set()}
                order.append(sid)
            for c in per.get("candidates") or []:
                fp = candidate_fingerprint(c)
                if fp in g["_seen"]:
                    continue
                g["_seen"].add(fp)
                g["candidates"].append(c)
    out = []
    for sid in order:
        g = groups[sid]
        if g["candidates"]:
            out.append({"merchant": g["merchant"], "store_id": sid, "candidates": g["candidates"]})
    return out


def run_by_urls_submit(
    from_recap: dict, *, available: str,
    submit_merchant: Callable[[str, str, "list[dict[str, Any]]", Path], SubmitOutcome],
    make_sub_run: Callable[[str], Path],
    flush: Callable[[dict], None] = lambda r: None,
    should_stop: Callable[[], bool] | None = None,
) -> dict:
    """Submit a by-urls dry-run's match-validated candidates, grouped by merchant,
    each as a standard safe batch (R24). ``submit_merchant`` builds the validation
    triple and runs 05_submit for one store; ``make_sub_run`` mints its run dir. The
    first NON-CLEAN merchant HALTS the whole batch fail-closed (same discipline as
    run_sweep). Stops cooperatively only BETWEEN merchants (never mid-Create)."""

    # P2-3 (audit 2026-09-02): refuse an INCOMPLETE preview at the DETERMINISTIC core,
    # not only in the console handler. _candidates_by_store silently DROPS unresolved /
    # errored games and would submit the rest — partial coverage shipped without an
    # operator ever seeing the console's 409. Fail closed here too.
    incomplete = preview_incomplete_reason(from_recap)
    if incomplete is not None:
        recap = {"mode": "submit", "available": available, "aborted": incomplete,
                 "merchants": [], "totals": {"merchants": 0, "attempted": 0, "created": 0}}
        flush(recap)
        return recap

    groups = _candidates_by_store(from_recap)
    recap: dict[str, Any] = {
        "mode": "submit", "available": available, "aborted": None,
        "merchants": [],
        "totals": {"merchants": len(groups),
                   "attempted": sum(len(g["candidates"]) for g in groups),
                   "created": 0}}
    flush(recap)

    # [12] Fable re-audit 2026-09-06: PRE-FLIGHT the vetted-merchant allowlist BEFORE any
    # write. The by-urls submit path used to write to ANY (merchant, store) the preview
    # produced — it never re-checked the AUTO_MERCHANTS allowlist that Safe-Auto
    # (scripts/10) enforces, so a real auto-validated ADD could land on an unvetted
    # store. ANY off-allowlist group refuses the WHOLE batch fail-closed (all-or-nothing,
    # like scripts/10), before the first 05_submit ever spawns.
    for g in groups:
        reason = rejection_reason(g["merchant"], g["store_id"])
        if reason is not None:
            recap["aborted"] = (f"merchant_not_allowed:{g['merchant']} "
                                f"(store {g['store_id']}): {reason}")
            flush(recap)
            return recap

    for g in groups:
        if should_stop is not None and should_stop():
            recap["aborted"] = "operator_stop"
            flush(recap)
            break
        merchant, store_id, cands = g["merchant"], g["store_id"], g["candidates"]
        sub_run = make_sub_run(store_id)
        outcome = submit_merchant(merchant, store_id, cands, sub_run)
        entry = {"merchant": merchant, "store_id": store_id, "run": sub_run.name,
                 "attempted": len(cands), "created": outcome.created,
                 "offers": outcome.offers, "halted": outcome.halt_reason()}
        recap["merchants"].append(entry)
        recap["totals"]["created"] += outcome.created
        flush(recap)
        if not outcome.clean():
            # A broken/blocked submit halts the batch — never plow on to the next
            # merchant on a dropped session / unreadable feed (fail-closed).
            recap["aborted"] = f"submit_not_clean:{merchant}: {outcome.halt_reason()}"
            flush(recap)
            break

    return recap
