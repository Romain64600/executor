"""Price check — the first-price monitor's reports, read and decided from the admin page.

The price-check monitor (its own repository, systemd unit ``price-check``, runs as root)
checks the first prices of every edition (top-offers) of every AllKeyShop page it follows. After every pass it writes
``reports.json`` into a shared directory (``/var/lib/price-check``, root:debian, mode 2775):
every SUSPECT, À VÉRIFIER or NON VÉRIFIABLE offer with its AllKeyShop URL, its merchant URL
and its reason (Romain, 2026-10-01: « ce rapport interactif de price check devrait être dans
l'admin »).

The admin READS that file as is and APPENDS the operator's decisions to ``decisions.jsonl``
in the same directory, one JSON line per decision; the monitor re-reads it before each pass
and the last line per offer wins. Nothing else is written: no page is opened, no AKS offer
is touched, no message is sent. Standard library only.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_DIR = Path("/var/lib/price-check")
REPORTS_FILE = "reports.json"
DECISIONS_FILE = "decisions.jsonl"
# The decisions the monitor understands (price_check.DECISIONS). reports.json carries them;
# this copy only serves an export written before it did.
DEFAULT_DECISIONS = {
    "vrai": "Vrai positif : alerter",
    "faux": "Faux positif : ne pas alerter",
    "a_discuter": "À discuter",
}
MAX_NOTE = 1000
STATUS_FILE = "status.json"          # written by the monitor: state of each page mode
COMPETITORS_FILE = "competitors.json"  # written by the monitor every 30 min: competitors' prices for the top pages
REQUEST_FILE = "run-%s.request"      # written by the admin: run this mode now
RUN_MODES = ("top-games", "homepage")  # Romain, 02/10/2026: « Price check top », « Price check homepage »
OFFER_ID = re.compile(r"^[0-9]{1,20}$")
_APPEND_LOCK = threading.Lock()  # one line at a time from this process (ThreadingHTTPServer)


class PriceCheckError(Exception):
    """A refused read or decision. ``code`` machine-readable, ``message`` verbatim."""

    def __init__(self, code: str, message: str, *, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _read_export(directory: Path) -> tuple[dict[str, Any], float]:
    """reports.json and its mtime — fail-closed: a missing or broken export is an error
    the page shows, never an empty list that would read as « nothing to check »."""

    path = directory / REPORTS_FILE
    try:
        raw = path.read_bytes()
        mtime = path.stat().st_mtime
    except FileNotFoundError as exc:
        raise PriceCheckError(
            "no_reports",
            f"{path} absent — le moniteur price-check n'a encore rien exporté "
            "(PRICE_CHECK_REPORTS_DIR dans son .env)",
            http_status=404) from exc
    except OSError as exc:
        raise PriceCheckError("reports_unreadable", f"{path} illisible : {exc}",
                              http_status=500) from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise PriceCheckError("bad_reports", f"{path} n'est pas un JSON valide : {exc}",
                              http_status=500) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("reports"), list):
        raise PriceCheckError("bad_reports", f"{path} : liste « reports » absente",
                              http_status=500)
    return payload, mtime


def _decision_labels(payload: dict[str, Any]) -> dict[str, str]:
    labels = payload.get("decisions")
    if isinstance(labels, dict) and labels and all(
            isinstance(k, str) and isinstance(v, str) for k, v in labels.items()):
        return labels
    return dict(DEFAULT_DECISIONS)


def read_decisions(directory: Path, allowed) -> dict[str, list[dict[str, Any]]]:
    """Every decision per offer, in file order (the last one stands). A line the monitor
    would ignore (unreadable JSON, unknown decision, bad offer id) is ignored here too, so
    the page never shows a decision the monitor does not apply."""

    history: dict[str, list[dict[str, Any]]] = {}
    path = directory / DECISIONS_FILE
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    item = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(item, dict):
                    continue
                offer = str(item.get("offer", ""))
                decision = item.get("decision")
                if OFFER_ID.match(offer) and isinstance(decision, str) and decision in allowed:
                    history.setdefault(offer, []).append(
                        {k: item.get(k) for k in ("decision", "note", "by", "at")})
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise PriceCheckError("decisions_unreadable", f"{path} illisible : {exc}",
                              http_status=500) from exc
    return history


def load_reports(directory: Path, *, now=time.time) -> dict[str, Any]:
    """The export, with each report's decision taken from decisions.jsonl when it is newer
    than the monitor's copy (the monitor only re-reads the file at its next pass, up to
    15 minutes later: the page must show a decision the moment it is recorded)."""

    payload, mtime = _read_export(directory)
    labels = _decision_labels(payload)
    history = read_decisions(directory, labels)
    reports = []
    for report in payload["reports"]:
        if not isinstance(report, dict):
            continue
        item = dict(report)
        past = history.get(str(item.get("offer", "")), [])
        if past:
            item["decision"] = past[-1]
        item["history"] = past
        # `seen` (epoch) = the start of the last pass where the offer was still the first
        # price. Measured against the export time, a long lag means it no longer leads.
        seen = item.get("seen")
        if isinstance(seen, (int, float)) and not isinstance(seen, bool):
            item["seen_at"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(seen))
            item["seen_lag_seconds"] = max(0, int(mtime - seen))
        reports.append(item)
    return {
        "dir": str(directory),
        "generated_at": payload.get("generated_at"),
        "age_seconds": max(0, int(now() - mtime)),
        "decisions": labels,
        "reports": reports,
    }


def record_decision(directory: Path, offer: Any, decision: Any, note: Any, *, by: str,
                    clock=_now_iso) -> dict[str, Any]:
    """Append one decision to decisions.jsonl, after checking it against the CURRENT export:
    a known offer, a decision the monitor understands, a short text note."""

    offer = str(offer if offer is not None else "").strip()
    if not OFFER_ID.match(offer):
        raise PriceCheckError("bad_offer", "offre invalide : un identifiant numérique est attendu")
    payload, _ = _read_export(directory)
    labels = _decision_labels(payload)
    if not isinstance(decision, str) or decision not in labels:
        raise PriceCheckError(
            "bad_decision", f"décision inconnue : {decision!r} (attendu : {', '.join(labels)})")
    if not any(isinstance(r, dict) and str(r.get("offer", "")) == offer
               for r in payload["reports"]):
        raise PriceCheckError(
            "unknown_offer", f"l'offre {offer} n'est pas dans {REPORTS_FILE}", http_status=404)
    if note is None:
        note = ""
    if not isinstance(note, str):
        raise PriceCheckError("bad_note", "la note doit être un texte")
    note = note.strip()
    if len(note) > MAX_NOTE:
        raise PriceCheckError("bad_note",
                              f"note trop longue ({len(note)} caractères, {MAX_NOTE} au plus)")
    entry = {"offer": offer, "decision": decision, "note": note, "by": by, "at": clock()}
    line = (json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8")
    path = directory / DECISIONS_FILE
    with _APPEND_LOCK:
        try:
            fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o664)
        except OSError as exc:
            raise PriceCheckError("decisions_unwritable", f"{path} : écriture impossible : {exc}",
                                  http_status=500) from exc
        try:
            view = memoryview(line)
            while view:
                view = view[os.write(fd, view):]
            os.fsync(fd)
        finally:
            os.close(fd)
    return entry


def pending_requests(directory: Path) -> dict[str, Any]:
    """The run requests not yet consumed by the monitor, per mode (None when none; {} when unreadable)."""

    out: dict[str, Any] = {}
    for mode in RUN_MODES:
        path = directory / (REQUEST_FILE % mode)
        try:
            out[mode] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        except (OSError, ValueError):
            out[mode] = {}
    return out


def read_status(directory: Path, *, now=time.time) -> dict[str, Any]:
    """status.json, written by the monitor every few seconds and at each step of a pass. Never an
    error: without it the page still shows the reports, and says the monitor's state is unknown."""

    path = directory / STATUS_FILE
    base = {"available": False, "modes": {}, "pending": pending_requests(directory)}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        age = max(0, int(now() - path.stat().st_mtime))
    except (OSError, ValueError):
        return base
    if not isinstance(payload, dict) or not isinstance(payload.get("modes"), dict):
        return base
    base.update(available=True, age_seconds=age, offers=payload.get("offers"),
                updated_at=payload.get("updated_at"), modes=payload["modes"])
    return base


def read_competitors(directory: Path, *, now=time.time) -> dict[str, Any]:
    """competitors.json (Romain, 2026-10-06 : « un widget par concurrent » sur l'onglet Price check, pour les tops) :
    the AllKeyShop first price of each top page next to each competitor's best displayed price. Never an error:
    without it the page says the monitor has not compared yet."""

    path = directory / COMPETITORS_FILE
    base = {"available": False, "sites": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        age = max(0, int(now() - path.stat().st_mtime))
    except (OSError, ValueError):
        return base
    if not isinstance(payload, dict) or not isinstance(payload.get("sites"), list):
        return base
    sites = [s for s in payload["sites"] if isinstance(s, dict)]
    # the fees / errors typed by the operators (competitor-fees.jsonl), on their row, per seller: keys and accounts apart
    lines = read_fee_lines(directory)
    for site in sites:
        for kind, key in (("key", "rows"), ("account", "accounts")):
            for row in site.get(key) or []:
                if isinstance(row, dict):
                    fees = row_fees(lines.get((site.get("id"), row.get("page_url"), kind), []), row_offers(row))
                    if fees:
                        row["fees"] = fees
    base.update(available=True, age_seconds=age, generated_at=payload.get("generated_at"), every=payload.get("every"),
                scope=payload.get("scope"), sites=sites)
    return base


def request_run(directory: Path, mode: Any, *, by: str, clock=_now_iso) -> dict[str, Any]:
    """Ask the monitor to run one page mode now: one request file per mode, created exclusively
    (two operators clicking at once make one request), consumed by the monitor within seconds."""

    if not isinstance(mode, str) or mode not in RUN_MODES:
        raise PriceCheckError("bad_mode", f"mode inconnu : {mode!r} (attendu : {', '.join(RUN_MODES)})")
    path = directory / (REQUEST_FILE % mode)
    entry = {"mode": mode, "by": by, "at": clock()}
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o664)
    except FileExistsError as exc:
        raise PriceCheckError(
            "already_requested",
            "un passage est déjà demandé pour ce mode — le moniteur le lit dans les secondes qui viennent",
            http_status=409) from exc
    except OSError as exc:
        raise PriceCheckError("request_unwritable", f"{path} : écriture impossible : {exc}",
                              http_status=500) from exc
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False))
    return entry


# ---- Console Claude et onglet Romain (Romain, 2026-10-06) -------------------------------------------------------------
# « une console pour pouvoir en discuter en temps réel depuis l'admin, sur ce même onglet Price check » ; « Rémy, Garance
# et moi pourrons avoir accès » (+ Lionel, « les mêmes droits ») ; « pour les modifications sur le code, il faudra passer
# par moi » ; « il faudra jamais oublier de me reporter les questions en cours » ; « un onglet Romain où il y a toutes les
# questions en cours, que tout le monde peut consulter, mais il n'y a que moi qui peux agir dessus ». The admin runs
# nothing: it drops a request file into the shared directory; the console service (price-check-console, root) reads it,
# runs Claude Code and writes console.json and questions.json, which the admin reads back.

CONSOLE_FILE = "console.json"        # written by the console service: the conversation
QUESTIONS_FILE = "questions.json"    # written by the console service: Romain's questions, open or settled
CONSOLE_REQUEST = "console-%d-%s.request"  # written by the admin: one message / harvest / settled question
CONSOLE_KINDS = ("message", "harvest", "close", "new-session")
CONSOLE_OWNER = os.environ.get("PRICE_CHECK_CONSOLE_OWNER", "romain")
CONSOLE_TEAM = tuple(u.strip() for u in os.environ.get("PRICE_CHECK_CONSOLE_TEAM", "remy,garance,lionel").split(",")
                     if u.strip())
MAX_CONSOLE_TEXT = 4000
MAX_ANSWER = 2000
QUESTION_ID = re.compile(r"^Q[0-9]{1,6}$")
FEES_FILE = "competitor-fees.jsonl"  # written by the admin: fee / error seen in a competitor's cart
MAX_FEE = 1000.0
FEE_KINDS = ("key", "account")


def console_role(user: str | None) -> str:
    """owner (Romain: acts), team (Rémy, Garance, Lionel: questions and answers), viewer (everyone else: the Romain tab)."""

    if user and user == CONSOLE_OWNER:
        return "owner"
    return "team" if user in CONSOLE_TEAM else "viewer"


def _read_json(path: Path, key: str, *, now=time.time) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        age = max(0, int(now() - path.stat().st_mtime))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get(key), list):
        return None
    payload["age_seconds"] = age
    return payload


def pending_console(directory: Path) -> list[dict[str, Any]]:
    """The requests not yet answered by the console service, oldest first (taken = being answered)."""

    out = []
    for suffix in (".work", ".request"):
        for path in sorted(directory.glob("console-*" + suffix)):
            try:
                request = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(request, dict):
                out.append({"user": request.get("user"), "kind": request.get("kind"), "at": request.get("at"),
                            "taken": suffix == ".work"})
    return out


def read_console(directory: Path, *, now=time.time) -> dict[str, Any]:
    """console.json and the requests waiting for an answer. Never an error: without the service, the page says so."""

    base: dict[str, Any] = {"available": False, "messages": [], "busy": None, "pending": pending_console(directory)}
    payload = _read_json(directory / CONSOLE_FILE, "messages", now=now)
    if payload is None:
        return base
    busy = payload.get("busy")
    base.update(available=True, age_seconds=payload["age_seconds"], updated_at=payload.get("updated_at"),
                busy=busy if isinstance(busy, dict) else None,
                messages=[m for m in payload["messages"] if isinstance(m, dict)][-300:])
    return base


def read_questions(directory: Path, *, now=time.time) -> dict[str, Any]:
    """questions.json: Romain's questions, open and settled. Never an error."""

    payload = _read_json(directory / QUESTIONS_FILE, "questions", now=now)
    if payload is None:
        return {"available": False, "questions": []}
    return {"available": True, "age_seconds": payload["age_seconds"], "updated_at": payload.get("updated_at"),
            "questions": [q for q in payload["questions"] if isinstance(q, dict)]}


def request_console(directory: Path, kind: Any, *, by: str, text: Any = None, question: Any = None, note: Any = None,
                    clock=_now_iso) -> dict[str, Any]:
    """One request for the console service, signed with the Basic identity: a message (Romain and the team), the harvest
    of the decisions, a settled question, a new session (Romain only)."""

    role = console_role(by)
    if role == "viewer":
        raise PriceCheckError("console_forbidden",
                              "la console est réservée à Romain, Rémy, Garance et Lionel", http_status=403)
    if not isinstance(kind, str) or kind not in CONSOLE_KINDS:
        raise PriceCheckError("bad_kind", f"demande inconnue : {kind!r}")
    if kind != "message" and role != "owner":
        raise PriceCheckError("owner_only", "seul Romain peut le faire : récolte, question réglée, nouvelle session",
                              http_status=403)
    entry: dict[str, Any] = {"kind": kind, "user": by, "at": clock()}
    if kind == "message":
        if not isinstance(text, str) or not text.strip():
            raise PriceCheckError("bad_text", "message vide")
        text = text.strip()
        if len(text) > MAX_CONSOLE_TEXT:
            raise PriceCheckError("bad_text", f"message trop long ({len(text)} caractères, {MAX_CONSOLE_TEXT} au plus)")
        entry["text"] = text
    if kind == "close":
        if not isinstance(question, str) or not QUESTION_ID.match(question):
            raise PriceCheckError("bad_question", "question invalide : Q suivi d'un numéro attendu")
        if note is None:
            note = ""
        if not isinstance(note, str) or len(note.strip()) > MAX_ANSWER:
            raise PriceCheckError("bad_note", f"réponse invalide ({MAX_ANSWER} caractères au plus)")
        known = {q.get("id"): q for q in read_questions(directory)["questions"]}
        if known.get(question, {}).get("status") != "open":
            raise PriceCheckError("unknown_question", f"pas de question en cours {question}", http_status=404)
        entry.update(question=question, note=note.strip())
    path = directory / (CONSOLE_REQUEST % (time.time_ns() // 1_000_000, os.urandom(3).hex()))
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o664)
    except OSError as exc:
        raise PriceCheckError("request_unwritable", f"{path} : écriture impossible : {exc}", http_status=500) from exc
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False))
    return entry


def read_fee_lines(directory: Path) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    """competitor-fees.jsonl, per competitor, page and kind (key or account), in the order typed."""

    out: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    try:
        lines = (directory / FEES_FILE).read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and entry.get("site") and entry.get("page_url"):
            out.setdefault((entry["site"], entry["page_url"], entry.get("kind") or "key"), []).append(entry)
    return out


def row_offers(row: dict[str, Any]) -> list[dict[str, Any]]:
    """The competitor's offers on a row, the cheapest of each seller (an export without them: its best offer alone)."""

    competitor = row.get("competitor") if isinstance(row.get("competitor"), dict) else {}
    offers = [o for o in competitor.get("offers") or [] if isinstance(o, dict) and o.get("seller")]
    if offers:
        return offers
    return [{"price": competitor.get("price"), "seller": competitor.get("seller")}] if competitor.get("seller") else []


def row_fees(entries: list[dict[str, Any]], offers: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The fee / error of each seller of a row, the last word winning; a cleared one (value None) removed. An entry typed
    before the sellers (2026-10-06 19:10, Romain's +20 € on Instant Gaming at 33,69 €) is found by its offer price."""

    fees: dict[str, dict[str, Any]] = {}
    for entry in entries:
        seller = entry.get("seller")
        if seller is None:
            seller = next((o.get("seller") for o in offers if o.get("price") == entry.get("price")), None)
            if seller is None:
                continue
        if isinstance(entry.get("value"), (int, float)):
            fees[seller] = dict(entry, seller=seller)
        else:
            fees.pop(seller, None)
    return fees


def record_fee(directory: Path, site: Any, page_url: Any, kind: Any, value: Any, *, by: str, seller: Any = None,
               clock=_now_iso) -> dict[str, Any]:
    """Romain, 2026-10-06 : « dans le prix concurrent, on puisse rajouter un fee à la main […] l'opérateur ira mettre
    l'offre dans son panier, voir s'il a des fees […] ça servira juste au monitoring » ; « on peut l'appeler fee ou error,
    parce que si le prix du concurrent peut être inégal, on peut lui ajouter plus ou moins d'euros » ; « pourquoi Instant
    Gaming reste premier prix alors que j'y ai rajouté 20 € ? » : the fee belongs to one SELLER of the competitor, and the
    next offer takes the place. One line per entry in competitor-fees.jsonl, checked against the current
    competitors.json; an empty value clears it."""

    kind = kind or "key"
    if kind not in FEE_KINDS:
        raise PriceCheckError("bad_kind", f"genre inconnu : {kind!r} (attendu : clé ou compte)")
    sites = {s.get("id"): s for s in read_competitors(directory)["sites"]}
    rows = (sites.get(site) or {}).get("rows" if kind == "key" else "accounts") or []
    row = next((r for r in rows if isinstance(r, dict) and r.get("page_url") == page_url and r.get("competitor")), None)
    if row is None:
        raise PriceCheckError("unknown_row", "ce prix n'est plus dans le relevé des concurrents : rafraîchir la page",
                              http_status=404)
    offer = next((o for o in row_offers(row) if isinstance(seller, str) and o.get("seller") == seller), None)
    if offer is None:
        raise PriceCheckError("unknown_seller", "ce marchand n'est plus dans les offres du concurrent : rafraîchir la page",
                              http_status=404)
    if value is None or (isinstance(value, str) and not value.strip()):
        amount = None
    else:
        try:
            amount = round(float(str(value).strip().replace(",", ".").replace("€", "").replace(" ", "")), 2)
        except ValueError as exc:
            raise PriceCheckError("bad_fee", "montant invalide : un nombre d'euros, + ou − (« 1,50 », « -0,80 »)") from exc
        if not -MAX_FEE <= amount <= MAX_FEE or amount != amount:
            raise PriceCheckError("bad_fee", f"montant invalide : entre -{MAX_FEE:.0f} et {MAX_FEE:.0f} €")
    entry = {"site": site, "page_url": page_url, "kind": kind, "product": row.get("product"), "seller": seller,
             "price": offer.get("price"), "value": amount, "by": by, "at": clock()}
    line = (json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8")
    path = directory / FEES_FILE
    with _APPEND_LOCK:
        try:
            fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o664)
        except OSError as exc:
            raise PriceCheckError("fees_unwritable", f"{path} : écriture impossible : {exc}", http_status=500) from exc
        try:
            view = memoryview(line)
            while view:
                view = view[os.write(fd, view):]
            os.fsync(fd)
        finally:
            os.close(fd)
    return entry
