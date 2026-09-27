"""Notifications sortantes — un message Discord quand la boucle s'arrête (2026-09-27).

Romain : « En cas d'arrêt de la boucle, tu penses que l'ancien VPS avec Hermes peut envoyer un
message sur Discord ? ». Plus simple et sans dépendre d'Hermes : un **webhook Discord** du
salon, appelé par l'exécuteur lui-même, depuis N'IMPORTE quel VPS.

* L'URL du webhook est un SECRET : variable d'environnement ``AKS_DISCORD_WEBHOOK``, ou la
  ligne ``AKS_DISCORD_WEBHOOK=…`` du fichier ``.env`` à la racine du clone (jamais commité —
  `.gitignore`). Elle n'est jamais journalisée ni affichée : seule sa PRÉSENCE l'est.
* Bibliothèque standard seule (``urllib``), 10 s de délai, un POST ``{"content": texte}``.
* ``notify`` NE LÈVE JAMAIS et ne retarde jamais le balayage : un échec rend
  ``{"sent": False, "reason": "<ClasseDErreur>"}`` — l'appelant journalise ``notify_failed``
  avec la classe d'erreur seulement. Sans webhook, c'est un no-op (``reason: "no_webhook"``).
* Le fichier ``.env`` est relu par CHAQUE processus de balayage à son démarrage : ajouter la
  ligne suffit, sans redémarrer l'admin (les balayages lancés depuis la console sont des
  processus neufs à chaque lancement).
"""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping

ROOT = Path(__file__).resolve().parents[1]
ENV_VAR = "AKS_DISCORD_WEBHOOK"
TIMEOUT_S = 10.0
MAX_CONTENT = 1900          # Discord refuse au-delà de 2 000 caractères
USER_AGENT = "AKS-Executor-notify/1.0"


def read_dotenv(path: Path) -> dict[str, str]:
    """Les paires ``CLE=valeur`` d'un fichier ``.env`` (lignes vides et ``#`` ignorées, ``export``
    toléré, guillemets simples ou doubles retirés). Fichier absent ou illisible = {}."""

    out: dict[str, str] = {}
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        return out
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            out[key] = value
    return out


def webhook_url(*, root: Path = ROOT, environ: Mapping[str, str] | None = None) -> str | None:
    """L'URL du webhook : l'environnement d'abord, puis ``<root>/.env``. None = pas configuré.
    Seules les URL ``https://`` sont acceptées (un secret ne part jamais en clair)."""

    env = os.environ if environ is None else environ
    value = str(env.get(ENV_VAR) or "").strip()
    if not value:
        value = read_dotenv(Path(root) / ".env").get(ENV_VAR, "").strip()
    if not value.lower().startswith("https://"):
        return None
    return value


def configured(*, root: Path = ROOT, environ: Mapping[str, str] | None = None) -> bool:
    return webhook_url(root=root, environ=environ) is not None


def notify(event: str, text: str, *, root: Path = ROOT,
           environ: Mapping[str, str] | None = None,
           urlopen: Callable[..., Any] = urllib.request.urlopen) -> dict[str, Any]:
    """Envoie ``text`` sur le webhook. Rend ``{"event", "sent", "reason"}`` — jamais une
    exception, jamais l'URL."""

    url = webhook_url(root=root, environ=environ)
    if url is None:
        return {"event": event, "sent": False, "reason": "no_webhook"}
    body = json.dumps({"content": str(text)[:MAX_CONTENT]}).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=TIMEOUT_S) as resp:      # noqa: SIM115 — context manager
            status = int(getattr(resp, "status", 200) or 200)
    except Exception as exc:                                # noqa: BLE001 — jamais une halte
        return {"event": event, "sent": False, "reason": type(exc).__name__}
    if status >= 400:
        return {"event": event, "sent": False, "reason": f"HTTP {status}"}
    return {"event": event, "sent": True, "reason": "ok"}
