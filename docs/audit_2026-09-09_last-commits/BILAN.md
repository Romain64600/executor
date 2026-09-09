# BILAN — revue adversariale des commits 184b2b8 → e7586f6 (2026-09-09, 16h45 ; mis à jour après le critique)

Mandat : « regarde mes 3 derniers commits, ne code pas » — revue **lecture seule**, aucun
fichier suivi modifié. Périmètre étendu aux 5 commits du 2026-09-08 (keep-alive HTTP + pacing
0,15 s + cap `--max-pages 30` + strip ™ ; fix fail-open 54f1f88 ; cap redirects 9ddf185 ;
HANDOFF.md 0394dfc + §7 commandes e7586f6 = HEAD).

Méthode : 5 chasseurs (parité, sécurité, matcher, ops, tests) + spot-check HANDOFF §7 →
dédoublonnage (45 → 42) → **3 vérificateurs adversariaux indépendants par finding**
(reproduction, relecture, matérialité ; réfuter par défaut ; gardé = majorité) → critique de
complétude (rendu 16h53 : 3 findings, tous confirmés). Détail par finding
avec votes : `REVIEW.md` ; état machine : `state.json`.

| | |
|---|---|
| Findings tranchés | 45 (38 confirmés, 7 réfutés, 0 indécis) — dont 3 du critique de complétude (Location non-ASCII, throttling 429, `06_move` du HANDOFF §7) |
| Critiques | 0 |
| Majors | 2 (1 sécurité OPEN, 1 ops CLOSED) |
| Mineurs matériels (unanimes ou OPEN) | 11 |
| Vrais mais immatériels (2-1, matérialité réfutée) | 22 |
| Points vérifiés corrects | 59 |

## 1. Verdict global

- **Le correctif fail-open 54f1f88 tient.** Matrice locale des deux backends (127.0.0.1) : en mode
  no-redirect (gate d'invariants, 03_match) un 3xx same-domain ressort en `HTTPError(3xx)` sur
  les deux, 1 requête, jamais suivi. Aucune divergence « vers le vert » sur la gate. Le plafond
  `max_redirects=10` = urllib. Cookies rejetés entre appels. Résolution toujours série. Le cap
  `--max-pages` ne fuit pas dans 05_submit (prove-gone plein feed). Suite : **1322 tests OK**.
- **Deux majors, aucun critique.** (a) Le garde host-lock du staff-UA est **contournable par un
  `\` dans l'autorité de l'URL** — divergence de parseur entre `urlsplit` (garde) et `urllib3`
  (connexion), **introduite par le backend keep-alive** ; (b) le défaut `--max-pages 30` fait de
  tout feed > 30 pages une **halte fail-closed du lot** (exit 2, marchands suivants jamais
  balayés, run « ARRÊTÉ » dans la console).
- **HANDOFF §7 (e7586f6) contient 3 commandes qui ne marchent pas** et une ligne d'écriture
  non marquée WRITE/GO.
- Le reste : dette de tests sur le nouveau seam (le dispatcher et le fallback urllib ne
  s'exécutent **jamais** dans la suite), et de la doc à réaligner.

## 2. Majors

### [major/OPEN] Garde host-lock staff-UA : `urlsplit` vs `urllib3.parse_url` — `src/aks_env.py:400` (+ :471, scripts/11:102)
`_allkeyshop_host()` prend `urlsplit(url).hostname` (le scanner s'arrête sur `/?#`) : pour
`https://evil.tld\@www.allkeyshop.com/x` il répond `www.allkeyshop.com` → garde OK. `requests`
passe la même chaîne à `urllib3.parse_url`, dont l'autorité s'arrête au `\` → connexion à
`evil.tld` avec `User-agent: AKS/Staff`, corps 200 de l'attaquant parsé comme page AKS. Le
fallback urllib échoue fermé (DNS) sur la même entrée. **Reproduit à HEAD avec le garde réel,
non patché**, 3 fois (2 serveurs locaux). Atteignable via un `Location:` hostile/MITM sur une
résolution staff en mode follow, ou une URL collée dans scripts/11 `--urls`. Matérialité jugée
faible (précondition hostile ; la gate est en no-redirect donc non concernée), mais c'est LE
seul invariant que le host-lock protège. Piste : refuser tout `\` / userinfo dans le netloc,
ou vérifier `urllib3.util.parse_url(url).host == urlsplit(url).hostname` avant chaque
`_SESSION.request` ; test de régression.

### [major/CLOSED] Défaut `--max-pages 30` = halte fail-closed de lot — `scripts/10_data_entry_auto.py:296`
`run_sweep` pose `halted='coverage_incomplete_max_pages'` dès que le feed dépasse le cap ;
scripts/10 traite toute halte ≠ `operator_stop` comme fail-closed (`break` :406-408, exit 2 :423) ;
la console mappe rc≠0 → « failed ». Reproduit avec le VRAI `run_sweep` : `--targets
Kinguin:58,Eneba:19` sans `--max-pages`, feed Kinguin 60 pages → pages 30→1 traitées, **Eneba
jamais balayé, exit 2**. Mécanisme pré-existant, mais 184b2b8 (200 → 30) le fait tirer sur le
cas nominal que le commit vise (~65+ pages). Aucune écriture fautive. Piste : sortir
`coverage_incomplete_*` de la règle break/exit-2 (champ recap séparé), ou défaut = feed entier.
Corollaire confirmé : le placeholder « (tout le feed) » de `/auto` (`auto.html:77`) ment — champ
vide = 30 pages.

## 3. Mineurs matériels (3 lentilles unanimes, ou direction OPEN)

- **HANDOFF §7 safe-auto sans marqueur WRITE/GO** (`docs/HANDOFF.md:143`, OPEN, unanime) : la
  seule commande d'écriture du §7 sans « WRITE — sur GO » ; scripts/10 appelle 05 en
  `--mode safe --submit` sans validation humaine ; `--dry-run` existe et n'est pas montré.
- **`Eneba:70`** (`:143` + docstring scripts/10:17, unanime) : l'allowlist dit 19 → exit 2.
- **Script 11 forme positionnelle** (`:150`, unanime) : `--run-id` requis + `--urls/--urls-file`.
- **Étape de validation absente** (`:132`, 2-1) : `04_validate.py check` / `run_executor.sh check`
  produit `approved.json` ; 05 refuse un approved.json non vérifié.
- **Dispatcher `_http_open` et fallback `_http_open_urllib` exécutés 0 fois par la suite**
  (`src/aks_env.py:449`, OPEN, unanime) : mutation « inverser 2 positionnels du dispatcher » →
  la gate tournerait en follow sans host-lock (exactement le fail-open de 54f1f88) et **60/60
  tests restent verts**. Piste : 1 test par backend contre un `http.server` 127.0.0.1 réel.
- **Politique cookie de la Session non testée** (`:338`, OPEN, unanime) : la seule ligne qui
  garantit la résolution stateless n'est assertée nulle part.
- **Boucle host-locked non testée** (`:392`, OPEN 2-1) : 3 mutants (perte de `current = nxt`,
  `while True`, `urljoin(url,…)`) passent la suite entière.
- **CI rouge** (`.github/workflows/ci.yml:19`, unanime) : Python 3.10 sans `pip install` → les 3
  tests qui importent `requests` en dur passent en ERROR à chaque push depuis 184b2b8.
- **`trust_env` laissé actif** (`:333`, OPEN 2-1) : une entrée `default` dans `~/.netrc` de root
  injecterait `Authorization: Basic` sur toutes les sondes (staff vers AKS, plain vers
  difmark/IG). Reproduit localement ; précondition improbable ; piste `trust_env=False` +
  `proxies.update(getproxies())`.
- **Boucle host-locked suit 9 hops, urllib 10** (`:392`, CLOSED 2-1) : divergence sur une chaîne
  d'exactement 10 hops (pathologique), sens fermé ; `range(11)` ou reformuler « miroir exact ».

## 4. Vrais mais immatériels (2-1, matérialité réfutée) — lot doc/hygiène

Parité : statut None vs 3xx à l'épuisement des redirects (scripts/11 seul à distinguer) ; cookie
intra-chaîne plain-UA ; wire-shape (Accept-Encoding gzip, `User-agent`) ≠ « identical behavior » ;
308 non suivi par urllib 3.10 (README dit 3.10+, VPS = 3.11) ; URLError du plafond doublement
enrobé. Ops/doc : `SweepConfig.max_pages=400` mort ; `CONTRIBUTING.md:19` « stdlib only » ;
requirements.txt/aks_env « rate inchangé » vs pacing ÷2 (~138 → ~255-330 req/min) et ban 08-28
attribué différemment dans invariants.py ; HANDOFF pointeur mort « Archi A », ref commit
9ddf185, « 04 report » ; by-urls sans pacing inter-URL (pré-existant) ; HANDOFF §7 `--mode
learning` sans « sur GO », 08/09 omis, « 4 cœurs », sorties de 03. Keep-alive : race socket
fermé → ok=False (fermé) ; gzip corrompu → None (fermé) ; ValueError urllib sur IPv6 invalide
(pré-existant). Matcher : test `Halo®Deluxe` vacuous (passe sur l'ancien code) ; EXECUTOR_RULES
§4.1 ne mentionne pas le strip pré-NFKC ; commentaire ℅/℀ inexact ; `# pragma: no cover` sans
outil coverage ; CHANGELOG « 9 findings » dont 5 introuvables ; CONTRIBUTING:65 exemple de patch
`urlopen` périmé.

## 5. Réfutés (7)

- `pip install` sous PEP 668 : `python3-requests` est déjà une dépendance de certbot
  (INSTALL_ADMIN) → /usr/bin/python3 l'a ; fallback urllib de même contrat de toute façon.
- `created_ok = "gone" in ps.lower()` (scripts/10:172) : 05 n'écrit jamais « NOT gone » (wording
  `gone from feed …` / `STILL …`) ; pré-existant ; recap seulement.
- Matcher ᵀᴹ/Ⓡ non couverts, № → « No » perdu, collocation plateforme avec symbole : vrais
  mécaniquement, sens fermé (skip R01), choix délibéré et testé (`Game № 5`).
- « Single patchable IO seam » : docstring toujours exacte (tout passe par `_http_open`).
- `Location: javascript:` : la gate est en no-follow → identique sur les deux backends.

## 6. Reprise

Tout est sur disque (dossier non commité) : `REVIEW.md` (détail + votes), `state.json`,
`continue_from_state.js` (ne relance que le critique), `RESUME.md` (procédure). Rien à refaire.

## 7. Suite donnée (même jour)

Sur GO de Romain, les 38 findings confirmés ont été corrigés (voir `docs/CHANGELOG.md`,
entrée 2026-09-09) puis re-vérifiés par une seconde revue adversariale des correctifs (137
agents : 40 remarques mineures intégrées, 4 réfutées).
