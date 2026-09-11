"""Per-merchant feed status report (Romain 2026-09-11: "un document par marchand pour
expliquer l'état du feed : le dernier passage, ce qu'on a ajouté d'offres et pourquoi on n'a
pas ajouté ce qui reste").

Pure functions over the run artefacts already on disk (``runs/<sweep>/recap.json``, the
per-page ``skipped.json`` / ``submit_plan.json`` / ``candidates.json``, by-urls submit runs).
No network, no browser, no secrets: offer names, merchant URLs, AKS page URLs and skip
reasons only. The Markdown is French (Romain's language) and deterministic for a given
runs directory, so it can be regenerated after every pass and committed under
``docs/feeds/<MERCHANT>.md``.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# --- skip-reason taxonomy -------------------------------------------------------------
# (category label, why it is not entered, what would unlock it). Order = display order.
_CATEGORIES: list[tuple[str, str, str, str]] = [
    # key, label, why, lever
    ("console", "Consoles (Xbox / PlayStation / Switch)",
     "l'outil AKS feed ne sait pas saisir une clé multi-plateforme (une ligne = une offre, "
     "consommée à la création) ; chantier mis en attente (2026-09-11)",
     "modification de l'outil AKS feed, puis classifieur console (EXECUTOR_RULES §4.3)"),
    ("no_page", "Sans page produit AKS",
     "aucune page AKS trouvée sous les slugs devinés (et la recherche AKS était en panne "
     "pendant le passage)",
     "créer la page produit sur AKS, ou retour de la recherche AKS (reprise automatique)"),
    ("dlc_no_own_page", "DLC sans page AKS propre",
     "le titre annonce un DLC mais AKS n'a pas de page pour ce DLC : la devinette retombe "
     "sur la page du jeu de base, jamais saisie (R43)",
     "créer la page du DLC sur AKS"),
    ("bundle", "Bundles / packs multi-jeux", "règle : on ne saisit jamais de bundle", "décision Romain"),
    ("currency", "Monnaie in-game (points, coins, gems…)", "règle : jeux uniquement, pas de monnaie", "décision Romain"),
    ("prepaid", "Cartes prépayées / gift cards / wallets", "hors périmètre (prepaids)", "décision Romain"),
    ("pass", "Passes in-game (Battle Pass, Game Pass…)", "ce ne sont pas des jeux ; seuls Season / Expansion Pass sont saisis", "—"),
    ("subscription", "Abonnements", "hors périmètre pour l'instant", "à apprendre (type « subscription » AKS)"),
    ("microsoft", "Microsoft Store", "plateforme Microsoft sans correspondance de région AKS", "à apprendre"),
    ("region", "Régions verrouillées interdites", "région non vendue (RoW, LATAM, RU, TR…)", "décision Romain"),
    ("variant", "Édition / variante absente de la page AKS",
     "le titre marchand porte des mots (édition, sous-titre) que la page AKS ne connaît pas → autre produit, doute → skip (R16)",
     "ajouter l'édition sur la page AKS, ou vérifier à la main"),
    ("wrong_page", "Page AKS trouvée mais nom différent", "la page atteinte n'est pas ce produit (R01), fail-safe", "vérifier à la main"),
    ("platform", "Plateforme non vérifiable", "pas de plateforme dans le titre et la page AKS ne confirme pas un éditeur direct (R20)", "vérifier à la main"),
    ("software", "Logiciels", "édition / région logicielle non résolue sur la page AKS (R31)", "vérifier à la main"),
    ("stub_page", "Page AKS sans carte d'éditions", "page AKS vide (stub), édition invérifiable (R19)", "compléter la page sur AKS"),
    ("rockstar", "Rockstar sans région", "plateforme Rockstar sans bucket de région AKS", "à apprendre"),
    ("transient", "Sonde AKS non fiable (transitoire)", "AKS a répondu en erreur ou timeout pendant le passage", "reprise automatique au passage suivant"),
    ("region_ambiguous", "Région ambiguë (mot de région dans le nom du produit)", "R44 : doute → skip", "vérifier à la main"),
    ("qualifier", "Remaster / HD / édition anniversaire sans page dédiée", "qualificatif absent du nom AKS (R01b)", "créer la page dédiée sur AKS"),
    ("other", "Autres", "voir le motif exact", "—"),
]
_CATEGORY_INDEX = {k: i for i, (k, *_rest) in enumerate(_CATEGORIES)}


def categorize_reason(reason: str) -> str:
    """Map a raw skip reason (matcher wording) to a taxonomy key."""

    r = (reason or "").strip()
    low = r.lower()
    if low == "console":
        return "console"
    if low.startswith("no aks") and "product page found" in low:
        return "no_page"
    if "(r43)" in low or low == "dlc in title":
        return "dlc_no_own_page"
    if low.startswith("possible multi-game bundle"):
        return "bundle"
    if low.startswith("skip category:"):
        cat = low.split(":", 1)[1].strip()
        if "bundle" in cat or "dlc collection" in cat:
            return "bundle"
        if any(t in cat for t in ("gift card", "wallet", "cash card", "shark card", "voucher", "prepaid", "top up", "eshop")):
            return "prepaid"
        if any(t in cat for t in ("points", "coins", "gems", "diamonds", "credits", "currency", "orb", "vc", "gem")):
            return "currency"
        if "subscription" in cat or "membership" in cat:
            return "subscription"
        if "microsoft" in cat:
            return "microsoft"
        if "pass" in cat:
            return "pass"
        if "skin" in cat or "random" in cat or "soundtrack" in cat or "artbook" in cat:
            return "other"
        return "other"
    if low.startswith("forbidden region") or low.startswith("country gift"):
        return "region"
    if low.startswith("different/expanded product") or low.startswith("edition '") or low.startswith("edition \""):
        return "variant"
    if low.startswith("name mismatch"):
        return "wrong_page"
    if low.startswith("no platform in title") or "official platforms exclude" in low:
        return "platform"
    if low.startswith("software") or "software" in low:
        return "software"
    if "no editions map" in low:
        return "stub_page"
    if "rockstar" in low:
        return "rockstar"
    if low.startswith("aks probe unreliable") or "unreadable" in low or "markup drifted" in low:
        return "transient"
    if "(r44)" in low:
        return "region_ambiguous"
    if low.startswith("dangerous qualifier"):
        return "qualifier"
    return "other"


# --- data model -----------------------------------------------------------------------
@dataclass
class PassSummary:
    run_id: str
    started_at: str
    finished_at: str
    pages: list[dict[str, Any]]
    halted: str | None
    coverage: str | None
    offers_seen: int
    candidates: int
    created: int
    not_created: list[tuple[str, str]] = field(default_factory=list)   # (title, reason)
    created_offers: list[tuple[str, str, str, str]] = field(default_factory=list)  # (title, aks_url, edition, region)
    skipped: list[tuple[str, str, str]] = field(default_factory=list)  # (title, url, reason)


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _merchant_slug(merchant: str) -> str:
    """The page-run slug scripts/10 uses: "Instant Gaming" → "instant-gaming"."""

    return re.sub(r"[^a-z0-9]+", "-", merchant.lower()).strip("-") or "merchant"


def _page_run_dirs(runs_dir: Path, sweep_id: str, merchant_slug: str, store_id: str) -> list[Path]:
    prefix = f"{sweep_id}-{merchant_slug}-s{store_id}-p"
    out = [p for p in runs_dir.iterdir() if p.is_dir() and p.name.startswith(prefix)]
    return sorted(out, key=lambda p: int(p.name.rsplit("-p", 1)[1]) if p.name.rsplit("-p", 1)[1].isdigit() else 0)


def find_sweeps(runs_dir: Path, merchant: str) -> list[tuple[str, dict[str, Any]]]:
    """(sweep_id, recap) for every ``*-auto`` sweep whose recap targets ``merchant``,
    oldest first."""

    out: list[tuple[str, dict[str, Any]]] = []
    for p in sorted(runs_dir.iterdir()):
        if not p.is_dir() or not p.name.endswith("-auto"):
            continue
        recap = _load(p / "recap.json")
        if not isinstance(recap, dict):
            continue
        if any(str(t.get("merchant", "")).upper() == merchant.upper() for t in recap.get("targets", [])):
            out.append((p.name, recap))
    return out


def summarize_pass(runs_dir: Path, sweep_id: str, recap: dict[str, Any], merchant: str, store_id: str) -> PassSummary:
    target = next(t for t in recap.get("targets", []) if str(t.get("merchant", "")).upper() == merchant.upper())
    rc = target.get("recap", {})
    pages = rc.get("pages", [])
    ps = PassSummary(
        run_id=sweep_id, started_at=str(recap.get("started_at") or ""),
        finished_at=str(recap.get("finished_at") or recap.get("updated_at") or ""),
        pages=pages, halted=rc.get("halted") or recap.get("halted"), coverage=rc.get("coverage"),
        offers_seen=sum(int(p.get("offers") or 0) for p in pages),
        candidates=sum(int(p.get("candidates") or 0) for p in pages),
        created=int(rc.get("total_created") or 0),
    )
    merchant_slug = _merchant_slug(merchant)
    for pdir in _page_run_dirs(runs_dir, sweep_id, merchant_slug, str(store_id)):
        plan = _load(pdir / "submit_plan.json") or {}
        for e in plan.get("plan", []) if isinstance(plan, dict) else []:
            title = str(e.get("merchant_title") or "")
            if e.get("submitted"):
                ps.created_offers.append((title, str(e.get("aks_url") or ""), str(e.get("edition_text") or e.get("edition_id") or ""),
                                          str(e.get("region_text") or e.get("region_id") or "")))
            else:
                ps.not_created.append((title, str(e.get("blocker") or e.get("post_save") or "")))
        skipped = _load(pdir / "skipped.json") or []
        for s in skipped if isinstance(skipped, list) else []:
            o = s.get("offer") or {}
            ps.skipped.append((str(o.get("name") or ""), str(o.get("url") or ""), str(s.get("reason") or "")))
    return ps


def created_by_day(runs_dir: Path, merchant: str, store_id: str) -> tuple[dict[str, int], Counter, Counter, int]:
    """All offers created for the merchant (every sweep page run + by-urls submit runs):
    per day, per edition, per region, total."""

    merchant_slug = _merchant_slug(merchant)
    by_day: dict[str, int] = defaultdict(int)
    editions: Counter = Counter()
    regions: Counter = Counter()
    total = 0
    for p in sorted(runs_dir.iterdir()):
        if not p.is_dir():
            continue
        n = p.name
        is_page_run = f"-{merchant_slug}-s{store_id}-p" in n
        is_by_urls = n.endswith(f"-by-urls-submit-s{store_id}")
        if not (is_page_run or is_by_urls):
            continue
        plan = _load(p / "submit_plan.json")
        if not isinstance(plan, dict):
            continue
        for e in plan.get("plan", []):
            if e.get("submitted"):
                total += 1
                by_day[n[:8]] += 1
                editions[str(e.get("edition_text") or e.get("edition_id") or "?")] += 1
                regions[str(e.get("region_text") or e.get("region_id") or "?")] += 1
    return dict(sorted(by_day.items())), editions, regions, total


# --- rendering ------------------------------------------------------------------------
def _fmt_ts(ts: str) -> str:
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return ts or "?"


def _duration(a: str, b: str) -> str:
    try:
        d = datetime.strptime(b, "%Y-%m-%dT%H:%M:%SZ") - datetime.strptime(a, "%Y-%m-%dT%H:%M:%SZ")
        m = int(d.total_seconds() // 60)
        return f"{m // 60} h {m % 60:02d}" if m >= 60 else f"{m} min"
    except ValueError:
        return "?"


def _md_escape(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def render_markdown(merchant: str, store_id: str, sweeps: list[PassSummary],
                    by_day: dict[str, int], editions: Counter, regions: Counter, total: int,
                    *, generated_at: str, max_examples: int = 3, max_created_list: int = 300,
                    max_table_rows: int = 10) -> str:
    last = sweeps[-1] if sweeps else None
    L: list[str] = []
    L.append(f"# État du feed — {merchant} (store {store_id})")
    L.append("")
    L.append(f"_Généré le {generated_at} par `scripts/14_feed_status.py` à partir des runs sur disque ; "
             "régénérer après chaque passage._")
    L.append("")
    L.append("## Dernier passage")
    L.append("")
    if last is None:
        L.append("Aucun passage safe-auto enregistré pour ce marchand.")
    else:
        L.append(f"- **Run** `{last.run_id}` — du {_fmt_ts(last.started_at)} au {_fmt_ts(last.finished_at)} "
                 f"({_duration(last.started_at, last.finished_at)})")
        L.append(f"- **Pages parcourues** : {len(last.pages)} — {last.offers_seen} offres vues, "
                 f"{last.candidates} candidats, **{last.created} créées**")
        halt = f"halte : `{last.halted}`" if last.halted else "aucune halte"
        cov = f", couverture : `{last.coverage}`" if last.coverage else ""
        L.append(f"- **Issue** : {halt}{cov}")
        if last.not_created:
            L.append(f"- **Non créées ({len(last.not_created)})**, laissées dans le feed pour le passage suivant :")
            for title, reason in last.not_created:
                L.append(f"  - {_md_escape(title)} — {_md_escape(reason[:120])}")
        else:
            L.append("- **Non créées** : aucune (toutes les tentatives ont abouti)")
    L.append("")
    L.append("## Offres ajoutées (cumul, tous passages)")
    L.append("")
    L.append(f"**Total : {total} offres créées** (sweeps safe-auto + saisies par URLs).")
    L.append("")
    L.append("| Jour | Créées |")
    L.append("|---|---|")
    for day, n in by_day.items():
        L.append(f"| {day[:4]}-{day[4:6]}-{day[6:]} | {n} |")
    L.append("")
    for title, counter in (("Édition saisie", editions), ("Région saisie", regions)):
        if not counter:
            continue
        L.append(f"| {title} | Offres |")
        L.append("|---|---|")
        top = counter.most_common(max_table_rows)
        for k, n in top:
            L.append(f"| {_md_escape(k)} | {n} |")
        rest = sum(counter.values()) - sum(n for _k, n in top)
        if rest:
            L.append(f"| … {len(counter) - len(top)} autres | {rest} |")
        L.append("")
    L.append("Historique des passages :")
    L.append("")
    L.append("| Run | Début | Pages | Offres vues | Candidats | Créées | Halte |")
    L.append("|---|---|---|---|---|---|---|")
    for s in sweeps:
        L.append(f"| `{s.run_id}` | {_fmt_ts(s.started_at)} | {len(s.pages)} | {s.offers_seen} | {s.candidates} | {s.created} | {s.halted or '—'} |")
    L.append("")
    if last is not None and last.created_offers:
        L.append(f"### Offres créées au dernier passage ({len(last.created_offers)})")
        L.append("")
        for title, aks_url, edition, region in last.created_offers[:max_created_list]:
            slug = re.sub(r"^.*/blog/(?:buy-)?", "", aks_url).rstrip("/")
            L.append(f"- {_md_escape(title)} → `{slug}` ({_md_escape(edition)}, {_md_escape(region)})")
        if len(last.created_offers) > max_created_list:
            L.append(f"- … et {len(last.created_offers) - max_created_list} autres (voir `runs/{last.run_id}/recap.json`)")
        L.append("")
    L.append("## Ce qui reste dans le feed et pourquoi")
    L.append("")
    if last is None or not last.skipped:
        L.append("Rien d'écarté au dernier passage.")
    else:
        cats: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
        for title, url, reason in last.skipped:
            cats[categorize_reason(reason)].append((title, url, reason))
        L.append(f"{len(last.skipped)} offres écartées au dernier passage, par famille :")
        L.append("")
        L.append("| Famille | Offres | Pourquoi ce n'est pas saisi | Levier |")
        L.append("|---|---|---|---|")
        for key, label, why, lever in _CATEGORIES:
            if cats.get(key):
                L.append(f"| {label} | {len(cats[key])} | {why} | {lever} |")
        L.append("")
        for key, label, why, lever in _CATEGORIES:
            items = cats.get(key)
            if not items:
                continue
            L.append(f"### {label} ({len(items)})")
            L.append("")
            sub = Counter(re.sub(r"\s*[:(—].*", "", r).strip() or r for _t, _u, r in items)
            if len(sub) > 1:
                L.append("Motifs exacts : " + ", ".join(f"{_md_escape(k)} ({n})" for k, n in sub.most_common(6)) + ".")
                L.append("")
            for title, url, reason in items[:max_examples]:
                L.append(f"- {_md_escape(title)} — `{_md_escape(reason[:110])}`")
            if len(items) > max_examples:
                L.append(f"- … {len(items) - max_examples} autres")
            L.append("")
    return "\n".join(L).rstrip("\n") + "\n"


def build_report(runs_dir: Path, merchant: str, store_id: str, *, generated_at: str | None = None) -> str:
    sweeps_raw = find_sweeps(runs_dir, merchant)
    sweeps = [summarize_pass(runs_dir, sid, recap, merchant, store_id) for sid, recap in sweeps_raw]
    by_day, editions, regions, total = created_by_day(runs_dir, merchant, store_id)
    ts = generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return render_markdown(merchant, store_id, sweeps, by_day, editions, regions, total, generated_at=ts)
