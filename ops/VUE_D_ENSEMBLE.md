# Vue d'ensemble des VPS — l'onglet `/overview` (2026-09-30)

Romain : « Est-ce que tu penses qu'il serait bien, dans l'admin, d'avoir un onglet pour monitor
les logs des trois VPS en direct sur la même page ? », puis « Qu'on puisse voir si les serveurs
sont up, le type de tâche actuel, etc. », puis « Go pour l'onglet vue d'ensemble ».

L'onglet **Vue d'ensemble** (`https://<VPS>/executor/overview`, alias `/vue-d-ensemble`) montre
une carte par machine, rafraîchie toutes les 15 s (« mis à jour il y a N s ») :

* un badge **UP / DOWN** — DOWN quand la machine ne répond pas, que son admin ne répond pas, ou
  qu'un service clé (`aks-admin`, `aks-chromium`, `hermes-cdp-proxy`, `nginx`) est arrêté, ou que
  sa photo est d'un autre format / mal formée (machine sur un autre commit) ; le motif est écrit
  sous le badge. Un service **absent** de la machine n'est pas une panne ;
* la **tâche en cours** en clair : « Balayage groupe A en boucle — passe 3, GOG page 12, saisie
  depuis 14:03 UTC », « Balayage groupe B en boucle — passe 2 finie, pause jusqu'à 15:35 UTC »,
  « Saisie par page — aperçu… », « Tri des listes — canary (écriture) », « Maintenance de cette
  machine en cours… », « Rien en cours » (avec le dernier balayage et pourquoi il s'est arrêté ;
  « … le dernier balayage s'est interrompu sans fin propre » quand son processus a disparu —
  admin redémarré, OOM, SIGKILL —, avec une alerte rouge : à relancer depuis la console),
  « Tâche inconnue » quand l'admin répond sans dire quel run tourne ;
* les offres créées (total de la boucle, passe en cours, page en cours), l'heure de lancement,
  la version du code (un avertissement quand les machines ne sont pas sur le même commit),
  l'uptime, la charge, le disque, la mémoire, la dernière maintenance ;
* les **alertes** en rouge : marchand arrêté, boucle arrêtée et pourquoi, balayage interrompu
  sans fin propre (processus disparu), offres à l'état
  INCONNU, session AKS perdue (« not logged in »), redémarrage requis par Debian, dernière
  maintenance en échec, disque plein à plus de 90 % ;
* les **20 derniers événements** du journal du run en cours (lancement + page en cours), les plus
  récents d'abord, filtrés (ni instantané du garde, ni attentes de rendu ; une seule ligne de
  progression) et sans secret ;
* le lien **« Ouvrir la console »** de la machine.

**Lecture seule, de bout en bout.** La page ne fait que des `GET api/overview` ; aucune route
d'écriture, aucune action relayée. Pour agir sur une machine (arrêter, relancer, transférer les
cookies), on ouvre SA console.

## Comment c'est lu

| Machine | Comment | Code |
|---|---|---|
| celle qui sert la page | en processus, avec le `busy()` de son admin | `src/admin/overview.py` → `src/vps_snapshot.py` |
| les autres | `ssh` avec une **clé dédiée**, bridée côté distant par une **commande forcée** | `scripts/20_vps_snapshot.py` (une ligne JSON) |

La ligne ssh de l'admin **ne porte aucune commande** ; c'est la commande forcée de la clé qui
s'exécute, et elle ne sait faire qu'une chose — imprimer la photo :

```
ssh -i <clé> -T -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new \
    -o IdentitiesOnly=yes debian@<IP>
```

`IdentitiesOnly=yes` : seule la clé dédiée est présentée — jamais une autre clé de `debian` qui
ouvrirait un shell. Toutes les machines sont lues en parallèle, **10 s au plus** chacune (au-delà :
DOWN « délai de 10 s dépassé ») ; le résultat est gardé **10 s** côté serveur, donc plusieurs
onglets ouverts ne multiplient pas les connexions.

La photo (`scripts/20_vps_snapshot.py`, lecture seule, jamais une exception) prend < 3 s
d'ordinaire : l'admin est jugé joignable sur `/api/meta` (réponse constante, 2,5 s), et
`/api/sort/runs` — qui parcourt tout `runs/` pour dire quel run tourne — part en même temps avec
**6 s** ; s'il se tait, la photo retombe sur le marqueur `state/active_run.json` (« Tâche
inconnue » sans marqueur), sans mettre la machine DOWN. 6 s au pire, dans les 10 s du ssh. Voir
[`docs/DATA_CONTRACTS.md`](../docs/DATA_CONTRACTS.md) « La photo d'une machine ». À la main, sur
n'importe quelle machine : `python3 scripts/20_vps_snapshot.py --pretty`.

## Installation (une fois) — depuis la machine qui affiche la page

Sans configuration, la page ne montre que la machine qui la sert. Pour voir les trois VPS depuis
la console de `vmi3565249` (217.76.57.126) :

**0. Le code** doit être déployé sur les TROIS machines (le script `scripts/20_vps_snapshot.py`
est la commande forcée : absent, la machine s'affiche DOWN « can't open file »). Déploiement
habituel, entre deux balayages : `sudo -u debian -H git -C /home/debian/executor pull --ff-only`
puis, si aucun run ne tourne, `sudo systemctl restart aks-admin` sur la machine qui affiche.

**1. La clé dédiée**, générée **sous `debian`** (le service `aks-admin` tourne sous `debian` ;
`accept-new` écrit dans `/home/debian/.ssh/known_hosts`) :

```bash
sudo -u debian -H ssh-keygen -t ed25519 -N '' -C 'aks-overview@vmi3565249' \
     -f /home/debian/.ssh/aks_overview_ed25519
sudo -u debian -H cat /home/debian/.ssh/aks_overview_ed25519.pub
```

**2. Sur CHAQUE machine distante** (51.38.37.254 et 169.58.5.63), UNE ligne ajoutée à
`/home/debian/.ssh/authorized_keys` — la clé publique ci-dessus, précédée de ses options :

```
command="python3 /home/debian/executor/scripts/20_vps_snapshot.py",restrict,no-pty,no-port-forwarding,from="217.76.57.126" ssh-ed25519 AAAA…(clé publique)… aks-overview@vmi3565249
```

* `command=` : quoi que demande le client, c'est la photo qui s'exécute (et rien d'autre) ;
* `restrict` : ni pty, ni redirection de port / d'agent / X11, ni `~/.ssh/rc` (`no-pty` et
  `no-port-forwarding` le redisent explicitement) ;
* `from="217.76.57.126"` : la clé n'est acceptée que depuis la machine qui affiche. Les cibles
  sont des adresses IPv4, la connexion part donc de l'IPv4 de `vmi3565249` ; si une machine
  distante est un jour jointe par un nom qui résout en IPv6, ajouter l'IPv6 source à la liste
  (`from="217.76.57.126,<ipv6>"`) — sinon la clé est refusée (DOWN « Permission denied »).

**3. La configuration** : `/home/debian/executor/state/overview_hosts.json` (jamais commité —
`state/`), propriétaire `debian` :

```json
{
  "ssh_key": "/home/debian/.ssh/aks_overview_ed25519",
  "hosts": [
    {"name": "cette-vm", "label": "vmi3565249 · production, groupe B", "ssh": null,
     "console_url": "https://217.76.57.126.sslip.io/executor/"},
    {"name": "ancienne-vm", "label": "vps-9ee9f9cf · production, groupe A", "ssh": "debian@51.38.37.254",
     "console_url": "https://51.38.37.254.sslip.io/executor/"},
    {"name": "secours", "label": "vmi3615170 · secours (price check partagé)", "ssh": "debian@169.58.5.63",
     "console_url": "https://169.58.5.63.sslip.io/executor/"}
  ]
}
```

| Champ | Sens |
|---|---|
| `ssh_key` | chemin ABSOLU de la clé privée dédiée (lisible par `debian`) |
| `hosts[].name` | nom affiché, unique (lettres, chiffres, `.` `_` `-`) |
| `hosts[].label` | sous-titre libre (≤ 80 caractères) |
| `hosts[].ssh` | `utilisateur@hôte` ; **`null` = cette machine** (lue en processus, au plus une ; absente, elle est ajoutée en tête) |
| `hosts[].key` | (facultatif) une autre clé pour cette machine |
| `hosts[].console_url` | lien « Ouvrir la console » — `http(s)://` seulement (sinon pas de lien) |

L'ordre des cartes est celui du fichier. Une entrée invalide (cible ssh qui commence par `-`,
clé relative ou absente, nom en double…) s'affiche **DOWN avec son motif** et aucun ssh ne part.
Le fichier est relu à chaque calcul (toutes les 10 s au plus) : pas de redémarrage de l'admin.

**4. Vérifier**, depuis `vmi3565249` :

```bash
# la photo de la machine distante, telle que l'admin la lira
sudo -u debian -H ssh -i /home/debian/.ssh/aks_overview_ed25519 -T -o BatchMode=yes \
     -o IdentitiesOnly=yes debian@51.38.37.254 | python3 -m json.tool | head -40
# une commande demandée est IGNORÉE : c'est encore la photo qui sort
sudo -u debian -H ssh -i /home/debian/.ssh/aks_overview_ed25519 -T -o BatchMode=yes \
     -o IdentitiesOnly=yes debian@51.38.37.254 id
```

Puis ouvrir `https://217.76.57.126.sslip.io/executor/overview`.

Les autres consoles peuvent faire de même (leur propre clé, leur propre fichier) ; sans fichier,
chacune ne montre qu'elle-même.

## Ce qui n'est jamais montré

Aucun secret : les événements passent par `src.run_log.redact` (clés `cookie`, `value`, `token`,
`authorization`, …) puis par un filtre de texte (URL de webhook Discord / Slack, cookies
`wordpress_*`, en-têtes d'autorisation) — sur la machine lue ET, à nouveau, sur celle qui relaie.
Le chemin de la clé ssh ne part pas dans la réponse. Les textes sont tronqués.

## Pannes courantes

| La carte dit | Cause probable |
|---|---|
| DOWN « délai de 10 s dépassé » | machine éteinte, réseau, ou photo bloquée |
| DOWN « ssh : … Permission denied » | ligne `authorized_keys` absente ou `from=` qui ne correspond pas |
| DOWN « ssh : … Host key verification failed » | la machine a changé de clé d'hôte : vérifier, puis `ssh-keygen -R <IP>` sous `debian` |
| DOWN « aucune réponse … can't open file » | code pas encore déployé sur la machine distante |
| DOWN « clé ssh absente » | `ssh_key` ne pointe pas sur un fichier lisible par `debian` |
| DOWN « admin injoignable » | `aks-admin` arrêté ou qui ne répond pas sur 127.0.0.1:8650 (`/api/meta`) |
| DOWN « photo au format N inconnu » | la machine n'est pas sur le même commit que celle qui affiche : déployer |
| DOWN « photo mal formée : … » | idem (une autre version du code), ou une photo abîmée — lancer le script à la main sur la machine |
| « Tâche inconnue » | l'admin répond mais n'a pas listé ses runs en 6 s (machine très chargée) et aucun marqueur : un tri ou une lecture peut tourner — voir sa console |
| « … interrompu sans fin propre » | le balayage a perdu son processus (admin redémarré, OOM, SIGKILL) : relancer depuis la console |
| DOWN « service aks-chromium failed » | le navigateur de saisie est tombé : `systemctl status aks-chromium` |
