"""Le catalogue des pages AKS — ce qu'une page EST, gardé d'un balayage à l'autre.

Romain, 2026-09-21 : « on peut juste dire : c'est une page standard, une page DLC, une page
early access jusqu'à telle date ou sans date limite, une page console Xbox Series X, Xbox One,
PS4 ou PS5 … on peut créer une DB partagée sur nos VPS, non ? »

**Pourquoi.** La page AKS est DÉJÀ ouverte pour chaque offre qui arrive à la décision : c'est
elle qui fournit la carte d'éditions, la carte de régions, les plateformes officielles et les
onglets console. Cette lecture servait une fois puis était jetée. Le jour où « Diablo IV Lord
of Hatred » est entrée Standard sur une page qui vend {DLC, Deluxe, Ultimate}, l'information
qui manquait était sous la main et perdue depuis longtemps. Le catalogue la garde.

**Ce qu'il n'est pas.** Il ne décide jamais à la place d'une lecture fraîche : au moment
d'écrire une offre, la carte d'éditions relue reste l'autorité. Il sert à savoir sans rouvrir,
à auditer hors ligne, et à éviter une relecture (≈ 7 % des résolutions d'un balayage tombent
sur une page déjà lue dans le même run).

**Trois garde-fous, tenus par construction :**

1. **Jamais un échec en cache.** Une page « pas trouvée » qui serait créée la semaine suivante
   resterait invisible pour toujours — c'est exactement ce qui a coûté 434 offres distinctes au
   balayage GameSeal du 19/09. Seule une résolution RÉUSSIE entre ici.
2. **Une durée de vie.** Une page gagne des seaux avec le temps : « Early Access » devient
   « Standard » à la sortie. ``fresh_only`` filtre à la lecture ; rien n'est jamais effacé.
3. **Jamais une raison d'échouer.** Toute erreur (SSH coupé, base verrouillée, disque plein)
   est avalée : le catalogue est un accélérateur, comme le ``--catalog-cache`` du submit. Un
   balayage de 30 h ne s'arrête pas parce que l'autre machine a redémarré.

**Partage entre les deux VPS.** La base vit sur une machine ; l'autre y accède par le tunnel
SSH qui existe déjà (clé de déploiement), en **connexion persistante** (ControlMaster) et en
accès GROUPÉS — mesuré le 2026-09-21 : 48 ms l'aller-retour multiplexé (430 ms sans),
~107 ms pour 100 écritures, ~100 ms pour lire 100 slugs d'un coup, contre 145 à 226 s pour
matcher une page de 100 offres. Soit 0,1 % du temps d'un balayage.
"""

from __future__ import annotations

import json
import shlex
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = 1
DEFAULT_TTL_DAYS = 30
SSH_CONTROL_PERSIST = "300"

# Les natures de page, telles que Romain les a nommées. `console:<FAMILLE>` porte la famille
# (XBOX_SERIES, XBOX_ONE, PS4, PS5, SWITCH…) : « une page console Xbox Series X, une page
# console Xbox One, une page console PS4 ou PS5 ».
NATURE_STANDARD = "standard"
NATURE_DLC = "dlc"
NATURE_EARLY_ACCESS = "early_access"
NATURE_ACCOUNT = "account"
NATURE_UNKNOWN = "inconnue"

_CONSOLE_KINDS = {
    "ps4": "PS4", "ps5": "PS5", "xbox-one": "XBOX_ONE", "xbox-series": "XBOX_SERIES",
    "nintendo-switch": "SWITCH", "nintendo-switch-2": "SWITCH2",
}

_CREATE = """
CREATE TABLE IF NOT EXISTS pages (
    slug               TEXT NOT NULL,
    page_kind          TEXT NOT NULL,
    url                TEXT NOT NULL,
    product_id         TEXT,
    aks_name           TEXT,
    nature             TEXT NOT NULL,
    early_access_until TEXT,
    editions           TEXT NOT NULL,
    regions            TEXT NOT NULL,
    official_platforms TEXT NOT NULL,
    console_pages      TEXT NOT NULL,
    page_platform      TEXT,
    read_at            TEXT NOT NULL,
    source             TEXT,
    PRIMARY KEY (slug, page_kind)
);
CREATE INDEX IF NOT EXISTS pages_nature ON pages (nature);
CREATE INDEX IF NOT EXISTS pages_read_at ON pages (read_at);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _edition_name(value: Any) -> str:
    if isinstance(value, Mapping):
        return str(value.get("name") or "").strip()
    return str(value or "").strip()


def page_nature(editions: Mapping[str, Any], page_kind: str = "cd-key") -> str:
    """La nature d'une page, déduite de ce qu'on lit DÉJÀ — aucune requête de plus.

    **Deux axes, deux colonnes.** La nature décrit le CONTENU (standard / DLC / accès
    anticipé) ; le GABARIT (page de clé, page de compte, page console Xbox Series X…) vit
    dans ``page_kind``. Les mélanger perdrait de l'information : la page compte de
    « Subnautica 2 » est À LA FOIS une page de compte Steam et une page d'accès anticipé — et
    c'est le second axe qui a fait entrer quatre offres Difmark en Standard le 21/09.
    ``describe()`` recompose la phrase de Romain à partir des deux.

    Une page « DLC » est une page dont le seul seau est le DLC — [R18] a la même exigence, et
    c'est lui qui décide du seau, jamais ce catalogue."""

    names = {eid: _edition_name(v).upper() for eid, v in (editions or {}).items()}
    if not names:
        return NATURE_UNKNOWN
    if len(names) == 1:
        sole_id, sole_name = next(iter(names.items()))
        if sole_id == "16" or sole_name == "DLC":
            return NATURE_DLC
        if "EARLY ACCESS" in sole_name:
            return NATURE_EARLY_ACCESS
    if "1" in names or "STANDARD" in names.values():
        return NATURE_STANDARD
    if any("EARLY ACCESS" in n for n in names.values()):
        return NATURE_EARLY_ACCESS
    if "16" in names or "DLC" in names.values():
        return NATURE_DLC
    return NATURE_UNKNOWN


def describe(record: Mapping[str, Any]) -> str:
    """La phrase de Romain : « une page DLC », « une page console Xbox Series X », « une page
    compte Steam, accès anticipé jusqu'à <date> »."""

    kind = str(record.get("page_kind") or "cd-key").lower()
    nature = str(record.get("nature") or NATURE_UNKNOWN)
    if kind in _CONSOLE_KINDS:
        base = "page console " + _CONSOLE_KINDS[kind].replace("_", " ").title()
    elif kind.endswith("-account") or kind == "account":
        base = "page compte " + kind.replace("-account", "").replace("-", " ").title()
    else:
        base = "page de clé"
    suite = {NATURE_STANDARD: "standard", NATURE_DLC: "DLC",
             NATURE_EARLY_ACCESS: "accès anticipé", NATURE_UNKNOWN: "nature inconnue"}.get(nature, nature)
    jusqu = record.get("early_access_until")
    if nature == NATURE_EARLY_ACCESS:
        suite += (" jusqu'au " + str(jusqu)) if jusqu else " (sans date de sortie connue)"
    return f"{base}, {suite}"


@dataclass(frozen=True)
class PageRecord:
    """Une page AKS telle qu'on l'a lue. `editions` / `regions` restent des cartes brutes :
    le catalogue n'interprète rien qu'il ne puisse rendre tel quel."""

    slug: str
    page_kind: str
    url: str
    product_id: str = ""
    aks_name: str = ""
    nature: str = NATURE_UNKNOWN
    early_access_until: str | None = None
    editions: dict[str, Any] | None = None
    regions: dict[str, Any] | None = None
    official_platforms: tuple[str, ...] = ()
    console_pages: dict[str, str] | None = None
    page_platform: str = ""
    read_at: str = ""
    source: str = ""

    @classmethod
    def from_resolution(cls, resolution: Any, *, page_kind: str = "cd-key",
                        source: str = "", early_access_until: str | None = None) -> "PageRecord":
        editions = dict(getattr(resolution, "editions", None) or {})
        return cls(
            slug=str(getattr(resolution, "slug", "") or ""),
            page_kind=page_kind or "cd-key",
            url=str(getattr(resolution, "url", "") or ""),
            product_id=str(getattr(resolution, "product_id", "") or ""),
            aks_name=str(getattr(resolution, "aks_name", "") or ""),
            nature=page_nature(editions, page_kind),
            early_access_until=early_access_until,
            editions=editions,
            regions=dict(getattr(resolution, "regions", None) or {}),
            official_platforms=tuple(getattr(resolution, "official_platforms", ()) or ()),
            console_pages=dict(getattr(resolution, "console_pages", None) or {}),
            page_platform=str(getattr(resolution, "page_platform", "") or ""),
            read_at=_now(),
            source=source,
        )

    def as_row(self) -> tuple:
        return (self.slug, self.page_kind, self.url, self.product_id, self.aks_name,
                self.nature, self.early_access_until,
                json.dumps(self.editions or {}, ensure_ascii=False),
                json.dumps(self.regions or {}, ensure_ascii=False),
                json.dumps(list(self.official_platforms), ensure_ascii=False),
                json.dumps(self.console_pages or {}, ensure_ascii=False),
                self.page_platform, self.read_at or _now(), self.source)


_COLUMNS = ("slug", "page_kind", "url", "product_id", "aks_name", "nature",
            "early_access_until", "editions", "regions", "official_platforms",
            "console_pages", "page_platform", "read_at", "source")


def _row_to_dict(row: Iterable[Any]) -> dict[str, Any]:
    d = dict(zip(_COLUMNS, row))
    for champ in ("editions", "regions", "official_platforms", "console_pages"):
        try:
            d[champ] = json.loads(d[champ]) if d[champ] else ({} if champ != "official_platforms" else [])
        except (TypeError, ValueError):
            d[champ] = {} if champ != "official_platforms" else []
    return d


class PageCatalog:
    """Le catalogue, local ou à l'autre bout d'un tunnel SSH.

    Local : ``PageCatalog("/home/debian/executor/state/page_catalog.db")``.
    Distant : ``PageCatalog(path, ssh="debian@51.38.37.254", ssh_key="~/.ssh/aks_executor_deploy")``
    — la connexion est multiplexée (ControlMaster) et les accès sont GROUPÉS ; un accès par
    offre coûterait 48 ms au lieu de 1 ms, ce qui reste petit mais n'a aucune raison d'être.

    Toute méthode échoue en silence (retour vide / False) : ce catalogue n'arrête jamais rien.
    """

    def __init__(self, path: str | Path, *, ssh: str = "", ssh_key: str = "",
                 ttl_days: int = DEFAULT_TTL_DAYS, source: str = "") -> None:
        self.path = str(path)
        self.ssh = ssh
        self.ssh_key = ssh_key
        self.ttl_days = int(ttl_days)
        self.source = source
        self.last_error: str = ""
        # DISJONCTEUR (mesuré le 2026-09-21) : un hôte injoignable coûtait 120 s par lot —
        # le SSH attend son délai de connexion, et le lot suivant recommence. Deux échecs
        # consécutifs coupent le catalogue pour la durée du processus : un balayage ne
        # ralentit pas parce que l'autre machine est tombée. Il se rallume au run suivant.
        self._failures = 0
        self.disabled = False

    # ── transport ────────────────────────────────────────────────────────────────────
    def _local(self, fn):
        conn = None
        try:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.path, timeout=10)
            # WAL : les deux VPS peuvent balayer en même temps sans se bloquer ; busy_timeout
            # laisse une écriture concurrente finir au lieu de lever « database is locked ».
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=10000")
            conn.executescript(_CREATE)
            out = fn(conn)
            conn.commit()
            return out
        except Exception as exc:                      # noqa: BLE001 — jamais fatal
            self.last_error = f"{type(exc).__name__}: {exc}"
            return None
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:                     # noqa: BLE001
                    pass

    def _remote(self, script: str, payload: str = "") -> str | None:
        """Exécute un script python à l'autre bout, en UN aller-retour."""

        if self.disabled:
            return None
        cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ControlMaster=auto",
               "-o", "ConnectTimeout=5", "-o", "ServerAliveInterval=5",
               "-o", f"ControlPath={Path.home()}/.ssh/cm/%r@%h:%p",
               "-o", f"ControlPersist={SSH_CONTROL_PERSIST}"]
        if self.ssh_key:
            cmd += ["-i", str(Path(self.ssh_key).expanduser())]
        cmd += [self.ssh, "python3 -"]
        try:
            Path(Path.home() / ".ssh" / "cm").mkdir(parents=True, exist_ok=True)
        except Exception:                             # noqa: BLE001
            pass
        try:
            res = subprocess.run(cmd, input=script + "\n" + payload, capture_output=True,
                                 text=True, timeout=20)
            if res.returncode != 0:
                self._note_failure((res.stderr or "").strip()[:200])
                return None
            self._failures = 0
            return res.stdout
        except Exception as exc:                      # noqa: BLE001
            self._note_failure(f"{type(exc).__name__}: {exc}")
            return None

    def _note_failure(self, message: str) -> None:
        self.last_error = message
        self._failures += 1
        if self._failures >= 2:
            self.disabled = True
            self.last_error = f"catalogue coupé après 2 échecs ({message})"

    def _remote_header(self) -> str:
        return (
            "import json, sqlite3, sys, pathlib\n"
            f"p = {self.path!r}\n"
            "pathlib.Path(p).parent.mkdir(parents=True, exist_ok=True)\n"
            "c = sqlite3.connect(p, timeout=10)\n"
            "c.execute('PRAGMA journal_mode=WAL')\n"
            "c.execute('PRAGMA busy_timeout=10000')\n"
            f"c.executescript({_CREATE!r})\n"
        )

    # ── API ──────────────────────────────────────────────────────────────────────────
    def put_many(self, records: Iterable[PageRecord]) -> int:
        """Écrit un LOT (une page de feed, typiquement). Rend le nombre écrit, 0 si échec."""

        rows = [r.as_row() for r in records if r and r.slug and r.url]
        if not rows:
            return 0
        sql = ("INSERT OR REPLACE INTO pages (" + ",".join(_COLUMNS) + ") VALUES ("
               + ",".join("?" * len(_COLUMNS)) + ")")
        if not self.ssh:
            out = self._local(lambda conn: conn.executemany(sql, rows))
            return len(rows) if out is not None else 0
        script = self._remote_header() + (
            f"rows = json.loads(sys.stdin.read())\n"
            f"c.executemany({sql!r}, [tuple(r) for r in rows])\n"
            "c.commit()\nprint(len(rows))\n"
        )
        # le payload passe par stdin APRÈS le script : `python3 -` lit tout, donc on
        # sépare script et données par une ligne vide et on relit le reste.
        out = self._remote_script_with_payload(script, json.dumps(rows, ensure_ascii=False))
        try:
            return int((out or "0").strip().splitlines()[-1])
        except (ValueError, IndexError):
            return 0

    def _remote_script_with_payload(self, script: str, payload: str) -> str | None:
        """`python3 -` consomme stdin en entier : on écrit donc le payload DANS le script."""

        inlined = script.replace("json.loads(sys.stdin.read())", f"json.loads({payload!r})")
        return self._remote(inlined)

    def get_many(self, keys: Iterable[tuple[str, str]], *, fresh_only: bool = True
                 ) -> dict[tuple[str, str], dict[str, Any]]:
        """Lit un LOT de (slug, page_kind). ``fresh_only`` écarte ce qui a dépassé la durée
        de vie — une page gagne des seaux avec le temps, un vieux relevé n'est plus une
        réponse. Rien n'est effacé pour autant : l'historique reste lisible."""

        pairs = [(str(s), str(k or "cd-key")) for s, k in keys if s]
        if not pairs:
            return {}
        limite = (datetime.now(timezone.utc) - timedelta(days=self.ttl_days)
                  ).strftime("%Y-%m-%dT%H:%M:%SZ") if fresh_only else "0"
        marks = ",".join(["(?,?)"] * len(pairs))
        sql = ("SELECT " + ",".join(_COLUMNS) + " FROM pages WHERE (slug, page_kind) IN ("
               + marks + ") AND read_at >= ?")
        args = [v for pair in pairs for v in pair] + [limite]
        if not self.ssh:
            rows = self._local(lambda conn: conn.execute(sql, args).fetchall())
        else:
            script = self._remote_header() + (
                f"rows = c.execute({sql!r}, json.loads({json.dumps(args)!r})).fetchall()\n"
                "print(json.dumps([list(r) for r in rows], ensure_ascii=False))\n"
            )
            out = self._remote(script)
            try:
                rows = json.loads((out or "[]").strip().splitlines()[-1])
            except (ValueError, IndexError):
                rows = None
        if not rows:
            return {}
        return {(r[0], r[1]): _row_to_dict(r) for r in rows}

    def get(self, slug: str, page_kind: str = "cd-key", *, fresh_only: bool = True
            ) -> dict[str, Any] | None:
        return self.get_many([(slug, page_kind)], fresh_only=fresh_only).get(
            (str(slug), str(page_kind or "cd-key")))

    def by_nature(self, nature: str, *, limit: int = 30) -> list[dict[str, Any]]:
        """Les pages d'une nature donnée — « montre-moi les pages en accès anticipé »."""

        sql = ("SELECT " + ",".join(_COLUMNS) + " FROM pages WHERE nature = ? "
               "ORDER BY read_at DESC LIMIT ?")
        args = [str(nature), int(limit)]
        if not self.ssh:
            rows = self._local(lambda conn: conn.execute(sql, args).fetchall())
        else:
            script = self._remote_header() + (
                f"rows = c.execute({sql!r}, json.loads({json.dumps(args)!r})).fetchall()\n"
                "print(json.dumps([list(r) for r in rows], ensure_ascii=False))\n")
            out = self._remote(script)
            try:
                rows = json.loads((out or "[]").strip().splitlines()[-1])
            except (ValueError, IndexError):
                rows = None
        return [_row_to_dict(r) for r in (rows or [])]

    def stats(self) -> dict[str, Any]:
        """De quoi répondre « combien de pages DLC / accès anticipé / console connaît-on ? »."""

        sql = "SELECT nature, COUNT(*), MIN(read_at), MAX(read_at) FROM pages GROUP BY nature"
        if not self.ssh:
            rows = self._local(lambda conn: conn.execute(sql).fetchall())
        else:
            script = self._remote_header() + (
                f"print(json.dumps([list(r) for r in c.execute({sql!r}).fetchall()]))\n")
            out = self._remote(script)
            try:
                rows = json.loads((out or "[]").strip().splitlines()[-1])
            except (ValueError, IndexError):
                rows = None
        rows = rows or []
        return {"par_nature": {r[0]: r[1] for r in rows},
                "total": sum(r[1] for r in rows),
                "plus_ancienne": min((r[2] for r in rows), default=None),
                "plus_recente": max((r[3] for r in rows), default=None)}


class CatalogRecorder:
    """Le seau qui se remplit pendant un match, vidé UNE fois par page de feed.

    Enveloppe le résolveur du matcher sans rien lui demander : `03_match` lui passe
    ``recorder.wrap(resolve_aks)`` au lieu de ``resolve_aks``. Le matcher ne connaît pas le
    catalogue, ne l'importe pas, et ses tests n'en voient rien.

    N'enregistre QUE les résolutions réussies : un échec n'entre jamais dans le catalogue
    (garde-fou n°1)."""

    def __init__(self, catalog: PageCatalog | None, *, source: str = "") -> None:
        self.catalog = catalog
        self.source = source
        self._seen: dict[tuple[str, str], PageRecord] = {}

    def wrap(self, resolver):
        def _resolver(name, **kwargs):
            resolution = resolver(name, **kwargs)
            self.note(resolution, page_kind=str(kwargs.get("page_kind") or "cd-key"))
            return resolution
        return _resolver

    def wrap_url(self, resolver):
        def _resolver(url, **kwargs):
            resolution = resolver(url, **kwargs)
            self.note(resolution, page_kind=str(kwargs.get("page_kind") or "cd-key"))
            return resolution
        return _resolver

    def note(self, resolution: Any, *, page_kind: str = "cd-key") -> None:
        if resolution is None or not getattr(resolution, "slug", ""):
            return          # garde-fou n°1 : jamais un échec en cache
        record = PageRecord.from_resolution(resolution, page_kind=page_kind, source=self.source)
        self._seen[(record.slug, record.page_kind)] = record

    def flush(self) -> int:
        """Écrit le lot et vide le seau. Jamais une exception vers l'appelant."""

        if not self.catalog or not self._seen:
            self._seen.clear()
            return 0
        try:
            n = self.catalog.put_many(self._seen.values())
        except Exception:                             # noqa: BLE001
            n = 0
        self._seen.clear()
        return n

    @property
    def pending(self) -> int:
        return len(self._seen)


# Les clés SSH essayées, dans l'ordre, pour une base DISTANTE. La première est dédiée au
# catalogue (créée le 2026-09-21 sur l'ancien VPS, autorisée chez le nouveau avec
# `restrict,command="/usr/bin/python3 -"` : la commande est FORCÉE, ce qui ferme l'usage
# général de cette clé — vérifié, un `rm -rf` envoyé par ce canal n'est pas exécuté). La
# seconde est la clé de déploiement historique, pour le sens nouveau → ancien.
SSH_KEY_CANDIDATES = ("~/.ssh/id_ed25519_catalog", "~/.ssh/aks_executor_deploy")


def _first_existing_key() -> str:
    for candidate in SSH_KEY_CANDIDATES:
        if Path(candidate).expanduser().is_file():
            return candidate
    return ""


def catalog_from_spec(spec: str, *, source: str = "", ttl_days: int = DEFAULT_TTL_DAYS
                      ) -> PageCatalog | None:
    """``"/chemin/page_catalog.db"`` → base locale ;
    ``"debian@51.38.37.254:/chemin/page_catalog.db"`` → base distante par SSH ;
    ``""`` → None (aucun catalogue, comportement d'avant)."""

    spec = (spec or "").strip()
    if not spec:
        return None
    if "@" in spec.split(":", 1)[0] and ":" in spec:
        host, path = spec.split(":", 1)
        return PageCatalog(path, ssh=host, ssh_key=_first_existing_key(),
                           source=source, ttl_days=ttl_days)
    return PageCatalog(spec, source=source, ttl_days=ttl_days)
