# Runbook navigateur — substrat Chromium/CDP du VPS (opérateur)

But : documenter le socle navigateur sur lequel tout l'exécuteur repose
(Chromium 149 headless, CDP, proxy socat, extension UA, services systemd),
pour qu'un opérateur puisse diagnostiquer une panne et reconstruire la VM de
zéro. Jusqu'ici cette connaissance n'existait que dans les mémoires de
session (constat d'audit DO5, 2026-07-17).

Tout ce qui suit a été **vérifié en live le 2026-07-17** sur le VPS cible
(`hostname` → `vps-9ee9f9cf`). Chaque fait cite la commande utilisée —
relancez-la en cas de doute, ce fichier peut vieillir.

Complément : l'installation de la page admin (nginx, htpasswd, certbot,
aks-admin) est détaillée dans `ops/INSTALL_ADMIN.md` ; ce runbook n'en reprend
que le strict nécessaire.

---

## 1. État actuel (vérifié 2026-07-17)

### 1.1 Chromium 149, gelé par apt hold

```
$ chromium --version
Chromium 149.0.7827.196 built on Debian GNU/Linux 12 (bookworm)

$ apt-mark showhold
chromium
chromium-common
chromium-sandbox

$ apt-cache policy chromium
  Installé : 149.0.7827.196-1~deb12u1
  Candidat : 150.0.7871.124-1~deb12u1   (bloqué par le hold)
```

**Pourquoi le hold.** Le paquet Debian 150 (bookworm-security) crashe en
SIGTRAP dans notre configuration headless/CDP — constaté en live, d'où le gel
à 149 sur les trois paquets. Ne **jamais** lever le hold « pour mettre à
jour » sans test : un Chromium qui SIGTRAP = plus aucun stage ne tourne.

**Contrainte couplée : le User-Agent.** L'invariant `required_user_agent`
(`src/aks_env.py:23-26`, `REQUIRED_USER_AGENT`) exige exactement
`... Chrome/149.0.0.0 Safari/537.36`, et `scripts/01_check_invariants.py` le
vérifie via CDP `/json/version`. Le hold apt et la constante UA vont donc
**ensemble** : passer à un Chromium 150+ (quand Debian livrera un paquet
sain) impose de mettre à jour `REQUIRED_USER_AGENT`, le flag `--user-agent`
de l'unité systemd (§1.2) et les tests, en une seule décision explicite —
jamais l'un sans l'autre.

### 1.2 aks-chromium.service — le Chromium supervisé

`systemctl cat aks-chromium` (unité : `/etc/systemd/system/aks-chromium.service`,
`enabled` + `active`) :

```ini
[Unit]
Description=AKS Chromium (headless CDP 9222, skill-canonical flags)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=debian
Group=debian
Environment=HOME=/home/debian
ExecStart=/usr/bin/chromium \
  --headless=new \
  --remote-debugging-port=9222 \
  --user-data-dir=/home/debian/.hermes/chromium-profile \
  --no-sandbox \
  --disable-dev-shm-usage \
  --disable-gpu \
  --disable-blink-features=AutomationControlled \
  --disable-features=IsolateOrigins,site-per-process \
  --window-size=1920,1080 \
  "--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36" \
  --lang=en-US,en \
  about:blank
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Points clés :

- CDP écoute en **loopback uniquement** (`ss -ltnp | grep 922` →
  `127.0.0.1:9222`, processus `chromium`). Jamais exposé à l'extérieur.
- Le profil vit dans **`/home/debian/.hermes/chromium-profile`** — c'est là
  que résident les cookies de session WordPress AKS (§1.7).
- Les flags sont « skill-canonical » : ne pas les modifier au cas par cas
  (UA, `--disable-blink-features=AutomationControlled`, `--window-size`…).
- `Restart=always` / `RestartSec=3` : systemd relance Chromium tout seul
  s'il meurt.

### 1.3 hermes-cdp-proxy.service — le pont socat 9223

`systemctl cat hermes-cdp-proxy` (`enabled` + `active`) :

```ini
[Unit]
Description=Hermes CDP bridge proxy
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/socat TCP-LISTEN:9223,bind=172.17.0.1,fork,reuseaddr TCP:127.0.0.1:9222
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
```

Vérifié en live : `ps aux | grep socat` montre le processus (root), et
`ss -ltnp | grep 922` montre l'écoute sur `172.17.0.1:9223`.

**Pourquoi 9223 et pas 9222.** Le code exécuteur doit utiliser l'endpoint
officiel `http://172.17.0.1:9223/json/version` — c'est
`OFFICIAL_CDP_ENDPOINT` dans `src/aks_env.py:21`, et
`validate_official_cdp_endpoint()` échoue-fermé sur tout autre endpoint. Le
9222 loopback est l'endpoint *hôte* ; le 9223 sur le bridge Docker est celui
que du code lancé depuis un conteneur peut atteindre, et c'est le seul
autorisé par les invariants (AGENTS.md, « Official endpoint for code running
from Docker bridge »). Le pare-feu restreint 9223 au réseau Docker (§1.8).

Dépendance : `bind=172.17.0.1` exige que l'interface `docker0` existe —
d'où `After=docker.service`. Sans Docker installé, socat ne peut pas binder.

### 1.4 Extension UA-Switcher — `AKS/Staff` sur les domaines AKS seulement

Politique Chromium gérée, vérifiée via
`ls /etc/chromium/policies/managed/` → un seul fichier,
**`aks-ua-switcher.json`**, qui fait deux choses :

1. `ExtensionInstallForcelist` : installation forcée de l'extension
   UA-Switcher (id `bhchdcejhohfmigjafbampogmaanbfkg`) depuis
   `clients2.google.com` — donc l'installation initiale exige un accès
   réseau au premier démarrage de Chromium ;
2. `3rdparty.extensions.<id>.json` : la configuration de l'extension en
   *managed storage*, sérialisée en chaîne JSON. Mode `custom` : UA
   `AKS/Staff` appliqué **uniquement** sur la liste de domaines AKS
   (`www.allkeyshop.com`, `www.goclecd.fr`, `www.keyforsteam.de`,
   `api.allkeyshop.com`, etc.) ; partout ailleurs, l'UA reste le
   `Chrome/149.0.0.0` de l'unité.

La configuration interne (le contenu de la clé `json`) est archivée dans le
dépôt : **`docs/ua-switcher-aks-staff.json`**. Pour reconstruire le fichier
de politique, ré-emballer ce JSON (sérialisé en chaîne) dans la structure
`ExtensionInstallForcelist` + `3rdparty` ci-dessus.

Le même principe est appliqué côté code : `AKS_STAFF_UA = "AKS/Staff"` dans
`src/aks_env.py:31`, et `http_get()` (`src/aks_env.py:317-321`) **refuse**
d'envoyer cet UA vers un hôte non-allkeyshop.com (audit #4, 2026-07-08).
Aucun autre hôte ne doit jamais voir un UA staff/crawler.

### 1.5 aks-admin + nginx — la page opérateur `/executor/`

`systemctl cat aks-admin` (`enabled` + `active`) :

```ini
[Unit]
Description=AKS Executor admin page (validation + submit)
After=network.target

[Service]
User=debian
Group=debian
WorkingDirectory=/home/debian/executor
ExecStart=/usr/bin/python3 /home/debian/executor/scripts/07_admin_server.py --host 127.0.0.1 --port 8650
Restart=always
RestartSec=3
# KillMode=control-group (default): stopping/restarting the service also kills
# a running 05_submit.py child, so supervision is never silently lost
# (fail-closed). An in-flight submit is bounded to at most one unverified
# offer, flagged "interrupted" for manual feed inspection at next startup.
NoNewPrivileges=yes
ProtectSystem=full

[Install]
WantedBy=multi-user.target
```

Copie de référence dans le dépôt : `ops/aks-admin.service`.

Devant, nginx (`/etc/nginx/sites-enabled/51.38.37.254.sslip.io.conf`, copie
dépôt : `ops/nginx-51.38.37.254.sslip.io.conf`) :

- vhost `51.38.37.254.sslip.io`, TLS Let's Encrypt géré par certbot
  (renouvellement automatique via `certbot.timer`), port 80 → 301 HTTPS ;
- `location /executor/` : basic auth (« AKS Executor »,
  `auth_basic_user_file /etc/nginx/.htpasswd_executor` — vérifié :
  `root:www-data`, mode 640), puis `proxy_pass http://127.0.0.1:8650/`
  (le slash final retire le préfixe `/executor/`) ;
- `proxy_read_timeout 200s` (le check invariants peut être long).

L'app Python refuse tout bind non-loopback sans `--allow-external` :
l'authentification vit dans nginx **seulement**. Installation complète et
rotation du mot de passe : `ops/INSTALL_ADMIN.md`.

### 1.6 Le marqueur FC2 — `/etc/aks-executor.target`

Vérifié : `ls -la /etc/aks-executor.target` → `-rw-r--r-- root root`,
contenu = `vps-9ee9f9cf` (le hostname de cette machine).

C'est ce marqueur qui rend les invariants **authoritative** sur cette
machine (FC2, audit 2026-07-17 — `src/aks_env.py:182-214`).
`marker_authorizes()` exige, échec-fermé : fichier présent **ET** possédé
par root sans écriture groupe/monde **ET** contenu strictement égal au
hostname courant. Un marqueur copié sur une autre machine ne transfère
aucune autorité, et il n'existe **aucune** variable d'environnement pour
forcer `authoritative:true` (seul le forçage OFF via `AKS_TARGET=dev` /
`sandbox` / `local` existe).

Installation (une fois, en root) :

```sh
sudo sh -c 'hostname > /etc/aks-executor.target'
sudo chmod 644 /etc/aks-executor.target
```

### 1.7 La session WordPress AKS (login)

- Les cookies de session WP vivent **dans le profil Chromium**
  (`/home/debian/.hermes/chromium-profile`, cf. `--user-data-dir` §1.2).
  Ils sont sur disque : un restart de `aks-chromium` **ne déconnecte pas**.
- Perdre le profil (VM reconstruite, répertoire effacé) = session perdue →
  Stage 0b login (`scripts/00b_login.py`, `docs/LOGIN_SPEC.md`),
  **uniquement sur go explicite de Romain**, une seule tentative
  mot de passe et une seule tentative 2FA.
- Les identifiants viennent de l'environnement seulement :
  `AKS_WP_USER` / `AKS_WP_PASSWORD`, typiquement via un `.env` à la racine
  du dépôt, `chmod 600`, gitignoré, jamais commité. Vérifié 2026-07-17 :
  **aucun `.env` présent sur le disque** — c'est l'état normal hors
  fenêtre de login ; on le crée au moment du login et on peut le supprimer
  après.
- Un `NotLoggedInError` dans n'importe quel autre stage = STOP échec-fermé +
  rapport d'erreur. Jamais de re-login auto-déclenché.

### 1.8 Pare-feu (ufw)

`sudo ufw status` (extrait pertinent, vérifié 2026-07-17) :

```
22/tcp                          ALLOW  Anywhere
Nginx Full                      ALLOW  Anywhere
172.17.0.1 9223/tcp on docker0  ALLOW  172.17.0.0/16   # Hermes CDP bridge proxy
```

Ni 9222 ni 8650 n'ont de règle ALLOW : ils n'écoutent qu'en loopback. Le
9223 n'est joignable que depuis le réseau Docker interne. Aucun port CDP
n'est exposé à Internet — à préserver tel quel lors d'une reconstruction.

---

## 2. Procédures de récupération

### 2.1 Navigateur planté / bloqué (wedged)

Symptômes : `CdpCommandError` dans un run, `curl -s
http://127.0.0.1:9222/json/version` qui ne répond pas ou plus de processus
`chromium` dans `ss -ltnp`.

Diagnostic (lecture seule) :

```sh
systemctl status aks-chromium --no-pager
curl -s http://127.0.0.1:9222/json/version    # hôte
curl -s http://172.17.0.1:9223/json/version   # bridge (officiel)
journalctl -u aks-chromium -n 50 --no-pager
```

Remède :

```sh
sudo systemctl restart aks-chromium
```

**Impact — et c'est voulu** : tout run en cours avorte échec-fermé via
`CdpCommandError` (`src/cdp_session.py:153` — un socket mort lève
l'exception et le run s'arrête, **pas de reconnexion silencieuse**, SC8).
C'est le comportement attendu : on ne « rattrape » pas un run à cheval sur
deux navigateurs. On relance proprement le stage (extract → match → report)
après le restart. Si un **submit** était en cours, ne pas relancer
aveuglément : lire `submit_plan.json` et le log JSONL du run, inspecter le
feed (au plus une offre non vérifiée), puis reprise idempotente standard
sur le même `approved.json`.

Après restart, vérifier :

1. `curl -s http://127.0.0.1:9222/json/version` → répond, champ
   `User-Agent` = `... Chrome/149.0.0.0 ...` ;
2. `curl -s http://172.17.0.1:9223/json/version` → même réponse via le pont ;
3. la session WP est intacte (cookies sur disque, §1.7) — un
   `NotLoggedInError` au prochain stage signalerait le contraire : STOP,
   rapport, attendre le go de Romain pour le Stage 0b.

### 2.2 Pont socat mort (9222 répond mais pas 9223)

```sh
systemctl status hermes-cdp-proxy --no-pager
sudo systemctl restart hermes-cdp-proxy
curl -s http://172.17.0.1:9223/json/version
```

Ne **pas** contourner en pointant le code sur 9222 : l'invariant
`official_cdp_endpoint` refuse tout autre endpoint, à raison.

### 2.3 Page admin en panne

`sudo systemctl restart aks-admin` — mais **jamais pendant un submit** : le
cgroup tue le fils `05_submit.py` (commentaire de l'unité, §1.5). Le run
serait marqué `interrupted` au redémarrage et l'UI demanderait une
inspection manuelle du feed. Détails : `ops/INSTALL_ADMIN.md`.

### 2.4 Chromium en boucle de crash après un upgrade

Si `journalctl -u aks-chromium` montre des SIGTRAP en boucle après une mise
à jour de paquet : le hold a probablement sauté et Debian a installé 150.
Revenir à 149 (`apt-cache policy chromium` pour voir les versions
disponibles ; sinon https://snapshot.debian.org), puis remettre le hold
(§3, étape 2).

---

## 3. Checklist reconstruction VM (de zéro)

Dans l'ordre. Prérequis : Debian 12 (bookworm), accès sudo, le dépôt cloné
dans `/home/debian/executor`, Docker installé (l'interface `docker0` est
requise par le pont socat, §1.3).

1. **Chromium 149** :
   ```sh
   sudo apt install chromium=149.0.7827.196-1~deb12u1 \
                    chromium-common=149.0.7827.196-1~deb12u1 \
                    chromium-sandbox=149.0.7827.196-1~deb12u1
   ```
   Si 149 a disparu de l'archive, le récupérer via
   https://snapshot.debian.org. Ne pas installer 150 (SIGTRAP, §1.1).
2. **Hold** :
   ```sh
   sudo apt-mark hold chromium chromium-common chromium-sandbox
   ```
3. **Politique UA-Switcher** : créer
   `/etc/chromium/policies/managed/aks-ua-switcher.json` avec
   `ExtensionInstallForcelist` (id `bhchdcejhohfmigjafbampogmaanbfkg`) et la
   config `3rdparty` dont la clé `json` est le contenu de
   `docs/ua-switcher-aks-staff.json` sérialisé en chaîne (§1.4).
   L'installation forcée de l'extension a besoin du réseau au premier
   lancement de Chromium.
4. **Unité aks-chromium** : recopier le texte du §1.2 dans
   `/etc/systemd/system/aks-chromium.service`, puis :
   ```sh
   sudo systemctl daemon-reload
   sudo systemctl enable --now aks-chromium
   curl -s http://127.0.0.1:9222/json/version   # doit répondre, UA Chrome/149.0.0.0
   ```
   Le profil `/home/debian/.hermes/chromium-profile` est créé au premier
   démarrage (il sera vierge : pas encore de session WP).
5. **Pont socat** :
   ```sh
   sudo apt install socat
   ```
   puis recopier le texte du §1.3 dans
   `/etc/systemd/system/hermes-cdp-proxy.service`, `daemon-reload`,
   `enable --now`, et vérifier
   `curl -s http://172.17.0.1:9223/json/version`.
6. **Pare-feu** : reproduire le §1.8 —
   ```sh
   sudo ufw allow OpenSSH
   sudo ufw allow "Nginx Full"
   sudo ufw allow in on docker0 from 172.17.0.0/16 to 172.17.0.1 port 9223 proto tcp comment "Hermes CDP bridge proxy"
   sudo ufw enable
   ```
   Ne rien ouvrir pour 9222 ni 8650.
7. **nginx + basic auth + TLS + aks-admin** : suivre `ops/INSTALL_ADMIN.md`
   dans l'ordre (htpasswd → vhost depuis
   `ops/nginx-51.38.37.254.sslip.io.conf` → certbot → unité depuis
   `ops/aks-admin.service`).
8. **Marqueur FC2** (root, sur la machine cible uniquement) :
   ```sh
   sudo sh -c 'hostname > /etc/aks-executor.target'
   sudo chmod 644 /etc/aks-executor.target
   ```
9. **Invariants** — le portail avant toute écriture :
   ```sh
   cd /home/debian/executor && python3 scripts/01_check_invariants.py
   ```
   Attendu : `ok: true` **et** `authoritative: true`. Tant que ce n'est pas
   vert sur le VPS, tout reste en lecture seule (CLAUDE.md).
10. **Login Stage 0b** — profil vierge = pas de session WP. Sur go explicite
    de Romain uniquement : créer `.env` (`chmod 600`, gitignoré) avec
    `AKS_WP_USER` / `AKS_WP_PASSWORD`, puis :
    ```sh
    set -a; source .env; set +a; python3 scripts/00b_login.py
    ```
    Une tentative mot de passe, une tentative 2FA, jamais de boucle
    (`docs/LOGIN_SPEC.md`).
11. **Tests** : `python3 -m unittest discover -s tests` — la suite doit être verte avant de
    reprendre l'exploitation.
