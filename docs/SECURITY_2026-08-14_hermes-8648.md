# Incident sécurité — port 8648 (Hermes Web UI) exposé — 2026-08-14

Statut : **CLOS — aucune preuve d'intrusion, exposition corrigée.**
Rédigé par l'exécuteur (audit read-only + remédiation), à la demande de Romain.

Ce document est un enregistrement d'ops. Aucun secret (token, mot de passe,
cookie) n'y figure — par principe du projet (AGENTS.md : « Never store passwords,
2FA codes, or session cookies »).

## 1. Contexte

Romain a demandé (dans l'ordre) : (a) vérifier si le serveur avait été piraté ;
(b) sécuriser en urgence le port **8648** trouvé ouvert ; (c) déterminer s'il y a
eu des intrusions par ce port et ce qui aurait pu être récupéré. Serveur :
`51.38.37.254` (Debian, host des services AKS Executor + de l'infra agent Hermes).

## 2. Audit système (read-only) — aucun signe de compromission

| Vérification | Résultat |
|---|---|
| Logins réussis (`last`) | Uniquement `debian` (légitime). Zéro root, zéro compte inconnu. |
| Échecs SSH (`lastb`) | Bruit de bots de scan classique (`admin`/`test`/`facai`…), **tous échoués** et **impossibles** : `PasswordAuthentication no` (SSH par clé uniquement). |
| Connexion « établie » depuis une IP de bot | Poignée de main sur le port 22 vouée à l'échec — pas une session. |
| Ports/process en écoute | Tous identifiés/légitimes : nginx (80/443), sshd (22), Hermes ×3 (agent gateway/web-ui/cdp-proxy), LiteLLM (8000), admin executor (8650), chromium CDP (9222/9223). |
| Fichiers sensibles (`passwd`, `sudoers`, `authorized_keys`, `sshd_config`) | **Aucune modification récente** (dates : juin/mai/2023/2025). |
| Cron / systemd timers | Standard Debian + services du projet uniquement. Aucune persistance suspecte. |
| Modifs `/etc` (< 45 j) | Toutes expliquées : renouvellement TLS certbot, updates apt, config du projet (nginx executor, services systemd, policy chromium UA). |
| Utilisateurs | Attendus uniquement : `debian` (1000), `agent` (1001, Hermes), `root`. Une seule clé SSH (`hermes-agent@docker`). |
| Modules noyau | Aucun LKM de type rootkit. |
| Défenses | UFW actif (deny incoming par défaut) + AppArmor chargé. |

## 3. L'exposition 8648 (Hermes Web UI)

- **Constat** : UFW autorisait `8648/tcp ALLOW IN Anywhere` (v4 + v6). Le service
  (`hermes-web-ui`, node, bind `0.0.0.0`) sert une SPA. La page `/` se charge
  **sans challenge d'auth** (HTTP 200).
- **Facteur atténuant décisif** : **tous les endpoints `/api/*` renvoient HTTP 401**
  sans token bearer. L'auth est activée côté service (token). Un attaquant externe
  n'obtenait donc que la **coquille de login** — **aucune donnée** (sessions,
  agents, config, messages) ni contrôle d'agent sans identifiants valides.
- **Fenêtre d'exposition** : bornée au plus par l'âge du service (~depuis le
  9 juil. 2026). Date exacte d'ajout de la règle UFW inconnue.

### Ce qui était en jeu (pire cas)
Si le token avait fuité **ou** via un bypass d'auth : le plan de contrôle Hermes —
sessions, conversations d'agent, config, potentiellement le pilotage de l'agent.
Sérieux, mais **token-gated**.

### Le token a-t-il fuité ?
Le token d'auth était écrit **en clair dans des fichiers world-readable**
(`~/.hermes-web-ui/server.log` + backups de `config.yaml`). Cette exposition exige
un **accès disque local** (`debian`/`agent`/`root`), **pas atteignable via le port
8648**. L'audit §2 n'a trouvé aucun accès local non autorisé.

## 4. Y a-t-il eu des intrusions ? — angle mort forensique

- Le web-ui **ne journalise aucune requête HTTP** sur la fenêtre d'exposition
  (journald = lignes de démarrage seules ; `server.log` figé avant le redémarrage
  du 9 juil.). **Impossible d'énumérer les IPs** ayant touché 8648.
- UFW « low » ne loggue que le **refusé** ; 8648 étant **autorisé**, le trafic
  accepté n'a pas été loggé → pas de trace côté pare-feu non plus.
- **Absence de logs ≠ preuve d'absence d'accès.** Mais : aucune trace d'accès
  réussi ni d'artefact de compromission (§2).

### Verdict
**Aucune preuve d'intrusion, et rien n'était récupérable sans identifiants**
(API 401). Le seul bémol honnête : sans access-log, pas de liste définitive de
connexions.

## 5. Remédiation appliquée (2026-08-14)

1. **8648 fermé à Internet** : `ufw delete allow 8648/tcp` (v4 + v6). Vérifié :
   plus aucune règle ALLOW 8648 → bloqué par le deny-incoming par défaut. Le
   service reste vivant en `127.0.0.1:8648` (accessible par **tunnel SSH** :
   `ssh -L 8648:localhost:8648 debian@51.38.37.254`).
2. **Secrets verrouillés en `600`** (owner-only) : `~/.hermes/auth.json`,
   `config.yaml`, `~/.hermes-web-ui/server.log`, backups de config.
3. **Durcissement large** : `chmod 600` sur **573 fichiers world-readable** de
   `~/.hermes` (state `.json`, logs, code). **Inoffensif** — tous les process
   Hermes tournent sous `debian`, propriétaire, qui garde lecture/écriture ;
   aucun process sous un autre utilisateur. Réversible (liste conservée).
   Décision Romain 2026-08-14 : **on garde le durcissement**.

## 6. Recommandations restantes (action Romain)

1. **Rotate le token Hermes** — il a côtoyé un port ouvert dans des fichiers
   world-readable (risque faible, hygiène). À faire via l'outillage Hermes ; NON
   fait par l'exécuteur (risque de couper l'UI/les comms de l'agent).
2. **Activer un access-log HTTP** sur le web-ui pour supprimer l'angle mort
   forensique.
3. **Accès distant à l'UI Hermes** : passer par un tunnel SSH plutôt qu'un port
   public (cf. §5.1).

## 7. Note de méthode

Toutes les investigations ont été **read-only** ; les seules écritures sont la
remédiation §5 (règles pare-feu + permissions de fichiers). Aucune valeur de
secret n'a été journalisée, échangée ou stockée. Conforme au principe fail-closed
et « never store/echo secrets » du projet.
