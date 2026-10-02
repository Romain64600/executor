# Maintenance des VPS — mise à jour, redémarrage, relance (2026-09-30)

Romain : « on va pouvoir travailler sur un script de restart, que tu feras passer sur les VPS
esclaves puis le tien », puis « go pour la v2 » après la revue de son premier jet (bash, tmux
save / `apt full-upgrade` / `tmux kill-server` / reboot / restore). Ce qui a changé et pourquoi :

| Premier jet | Risque | v2 |
|---|---|---|
| Aucune vérification des balayages | un redémarrage en plein clic laisse une offre dans un état inconnu ; rien ne relance le groupe | l'admin est interrogé ; un balayage `data_entry_auto` de l'admin est arrêté par « Arrêter » **à un moment sûr seulement** (entre deux pages, lecture, matching, pause — jamais pendant la saisie : la grâce d'arrêt est fixe, 75 s / 120 s), on attend qu'il n'ait plus d'enfant, on note de quoi le relancer (lu dans le recap final, ajouts de la console compris) ; tout autre run, ou pas de moment sûr en 45 min → maintenance **reportée** |
| `apt full-upgrade` nu | `needrestart` peut redémarrer `aks-admin` (et tuer ses balayages) même sans redémarrage ; une invite de fichier de config bloque ou écrase nginx / ufw | `NEEDRESTART_MODE=l`, `NEEDRESTART_SUSPEND=1`, `--force-confdef --force-confold`, `DPkg::Lock::Timeout=600` (unattended-upgrades) |
| `tmux kill-server` | tue les sessions de travail (dont celle de Claude) sans rien apporter | jamais |
| Étape E (`$?` après ssh) | inversée : attend un redémarrage qui n'a pas lieu, restaure tmux deux fois ; saute l'attente après un vrai redémarrage (ssh → 255) | code 42 explicite, retour prouvé par un NOUVEAU `boot_id` |
| `until ssh …` | boucle infinie si le VPS ne revient pas | 15 min pour revenir, 25 min pour finir, sinon arrêt du pilote + Discord |
| Rien au retour | invariants, session AKS, balayage : rien n'est vérifié ni relancé | services, admin, invariants **faisant foi**, session AKS prouvée — puis relance ; sinon aucune relance et message Discord |

**Revue adverse avant premier usage (30/09, 3 lecteurs + 9 vérificateurs) — 8 constats confirmés,
tous corrigés et épinglés par un test qui rougit sans son correctif :** arrêt demandé seulement à
un moment sûr (P0) ; redémarrage décidé APRÈS apt sur un état relu — un run relancé entre-temps
l'empêche, un redémarrage devenu nécessaire est vu (P0) ; relance lue dans le recap final (les
marchands ajoutés par la console ne sont pas dans le lancement) ; une panne après l'arrêt n'est
jamais muette (code 7, `last_result.json`, Discord) et arrête le pilote au lieu d'être prise pour
« script absent » (127) ; le pilote ne tire plus le code lui-même — l'agent le tire APRÈS l'arrêt
(`--pull`), jamais sous un run ; un Chromium non bloqué en version reporte la maintenance ; une
connexion ssh coupée n'interrompt pas l'agent (SIGHUP ignoré), et le pilote attend jusqu'à 5 h.

**Premier passage réel — ancienne VM, 2026-09-30 14:26 UTC.** Arrêt de la boucle A à un moment
sûr, 9 paquets, redémarrage (requis par Debian) : la machine est revenue en 1 min, mais **sans
DNS** — `/etc/resolv.conf` y pointe vers `/run/resolvconf/resolv.conf`, et `resolvconf.service`
était DÉSACTIVÉ : /run étant vidé au démarrage, plus aucun nom ne se résolvait. Les invariants
ont vu AKS injoignable, rien n'a été relancé (comportement voulu). Réparé (`resolvconf -u`,
`systemctl enable resolvconf`), fin reprise, boucle A relancée par l'admin
(`20260930-143231-auto`). **Garde ajoutée** : un redémarrage n'est plus autorisé si le service
qui régénère `resolv.conf` (resolvconf, ou systemd-resolved) n'est pas activé (`dns_boot_ok`).

**Ré-audit de Romain (01/10, sur `2272e92`) — 5 défauts confirmés, corrigés le 02/10 :**
(P1) le matching n'est plus un « moment sûr » — il précède la saisie et peut basculer entre la
lecture et l'arrêt ; si l'étape bascule quand même, le motif de l'arrêt le signale (« ATTENTION »)
— seuls probe / extract / pause restent ; (P1) le contrôle d'avant redémarrage et le redémarrage
se font SOUS le verrou du navigateur, gardé jusqu'à l'extinction (`systemctl reboot` immédiat) :
un run qui tient le navigateur empêche le redémarrage, un run lancé après ne peut plus rien
écrire ; le pilote reconnaît le redémarrage à la ligne « rebooting », même si ssh se coupe avant
le code 42 ; (P2) une boucle relancée garde les marchands ajoutés depuis la console (`planned`
de la passe + file `targets_queue.json`, moins les refusés) ; (P2) des processus d'`aks-admin`
illisibles interdisent le redémarrage ; (P2) le garde DNS refuse `enabled-runtime` (activation
temporaire) et n'accepte `static` que si le service tourne.

## Les deux scripts

* **`scripts/18_vps_maintenance.py`** — sur CHAQUE VPS, sous `debian` (sudo sans mot de passe) :
  `status` (lecture seule), `run [--dry-run] [--reboot auto|never] [--allow-hermes]`, `postboot`.
  État dans `state/maintenance/` (`relaunch.json`, `pending.json`, `last_result.json`, journaux
  apt). Codes : 0 fait · 42 redémarrage programmé · 3 reporté (run en cours non relançable, pas
  de moment sûr, ou arrêt non abouti — rien d'autre n'est fait) · 4 apt en échec · 5 contrôles en
  échec (rien relancé) · 6 relance refusée · 7 panne après l'arrêt (rien relancé, Discord ; le
  corps de relance reste dans `state/maintenance/relaunch.json`).
* **`scripts/19_restart_vps.py`** — le pilote, depuis la VM de production `vmi3565249` : un VPS
  après l'autre, `secours` → `ancienne-vm` → `cette-vm` (toujours la dernière), **à blanc par
  défaut**. Il s'arrête au premier VPS qui ne revient pas au vert (codes 4, 5, 6, ou pas de retour)
  et ne touche pas au suivant ; un VPS « reporté » (code 3) ne l'arrête pas.
* **`ops/aks-maint-postboot.service`** — installé et activé par `run` juste avant un redémarrage ;
  au démarrage, il ne part que si `state/maintenance/pending.json` existe, fait les contrôles et la
  relance, écrit `last_result.json`, prévient Discord et retire `pending.json` (une tentative par
  maintenance). C'est lui qui finit le travail sur la machine qui pilote, puisque le pilote meurt
  avec elle.

## Usage

```bash
# depuis vmi3565249, en root (clé ~/.ssh/aks_executor_deploy) — le clone de dev ou le live
python3 scripts/19_restart_vps.py                         # à blanc : état + plan de chaque VPS
python3 scripts/19_restart_vps.py --skip secours          # à blanc, sans le VPS de secours
python3 scripts/19_restart_vps.py --apply --only ancienne-vm
python3 scripts/19_restart_vps.py --apply                 # tout, dans l'ordre
python3 scripts/19_restart_vps.py --apply --only secours --reboot-secours   # redémarrage autorisé
```

**Suivre depuis la console** : l'onglet « Vue d'ensemble » (`/overview`, [`VUE_D_ENSEMBLE.md`](VUE_D_ENSEMBLE.md))
dit pour chaque VPS « Maintenance … en cours » (processus `18 … run|postboot`, `19 --apply`, ou
`pending.json`), « redémarrage requis par Debian » et le code de la dernière maintenance.

En `--apply`, l'agent de chaque VPS tire le code (`git pull --ff-only`) APRÈS avoir arrêté le
balayage — jamais sous un run. Un VPS où le script n'est pas encore déployé est « reporté » (127).
**Lancer le pilote dans tmux** : il peut durer plusieurs heures.

## Règles

* **Le VPS de secours n'est jamais redémarré par défaut** (`reboot: never`) : il porte aussi le
  projet price check (compte `hermes`). `--reboot-secours` l'autorise, et le script refuse encore
  si `hermes` a des processus, sauf `--allow-hermes`. Rien ne touche aux sessions ni aux
  processus de `hermes`.
* **Seuls les balayages `data_entry_auto` lancés par l'admin sont arrêtés et relancés.** Un
  balayage simple repart au marchand qui était en cours (depuis sa page la plus haute) avec ceux
  qui suivent ; une boucle repart entière, en boucle. Une saisie par page, un tri, un run lancé au
  terminal : maintenance reportée.
* **La relance est une écriture** : elle n'a lieu que sur preuve (services actifs, admin qui
  répond, `01_check_invariants.py` vert et faisant foi, tableau de bord wp-admin prouvé). Une
  session AKS perdue au redémarrage = transfert de cookies par Romain, jamais par le code.
* **Chromium reste bloqué** (`apt-mark hold chromium chromium-common chromium-sandbox`) : son
  User-Agent est un invariant ; `status` le vérifie (`chromium_held`).
* **Jamais pendant une urgence sur une machine** : `--only` / `--skip` choisissent les VPS.
