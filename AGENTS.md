# AKS Controlled Executor — Codex instructions

## Mission

You are Codex CLI working as a builder, not as a free-form executor.

Your job is to build a deterministic AKS controlled executor.

You may:
- write scripts;
- write tests;
- audit logs;
- improve docs;
- run read-only diagnostics;
- propose implementation plans.

You must not:
- manually submit AKS offers through ad-hoc browser actions;
- improvise browser workflows;
- bypass validation;
- use Browserbase;
- use Playwright fallback;
- launch VPN;
- self-trigger or automate the session re-auth (AKS is social-login only now,
  so re-auth is COOKIE TRANSFER — `docs/LOGIN_SPEC.md`,
  `src/admin/login_manager.py` — driven only by Romain's explicit submit in
  the console; a `NotLoggedInError` from another stage stays a fail-closed STOP,
  never a re-auth trigger).

## Known infrastructure

Host Chrome CDP:
http://127.0.0.1:9222/json/version

Docker bridge CDP proxy:
http://172.17.0.1:9223/json/version

Official endpoint for code running from Docker bridge:
http://172.17.0.1:9223/json/version

Required User-Agent:
Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36

AKS direct URL:
https://www.allkeyshop.com/blog/

## Forbidden

- Browserbase
- browser_navigate for AKS execution
- Playwright fallback
- VPN fallback when AKS direct works
- /root/start-chromium.sh
- random 0.0.0.x CDP checks
- submitting without explicit validation file
- submitting without modal context verification
- fire-and-forget submission
- using old candidates from memory
- using previous feed state
- self-triggering the session re-auth (cookie transfer, `docs/LOGIN_SPEC.md` —
  Romain's explicit submit in the console only)
- changing process after Romain says "go"

## Required architecture

The deterministic, per-stage rules (extractor, matcher, submitter, post-save
verification, reporting) derived from the `aks-data-entry` skill are specified in
`docs/EXECUTOR_RULES.md`. Read and follow it when implementing any stage; it is
the authoritative bridge between the skill and this code.

Build in stages:

1. Environment audit script.
2. Read-only feed extractor.
3. Read-only matcher.
4. Candidate report generator.
5. Validation file generator.
6. Submitter locked behind validation.
7. Post-save verifier.
8. JSONL logs for every action.
9. Dry-run mode by default.

Session re-auth (`docs/LOGIN_SPEC.md`, `src/admin/login_manager.py`): AKS
disabled password login (social/OAuth only), so re-auth is COOKIE TRANSFER —
Romain completes the social login in his own browser and pastes the WP session
cookies into the console, which injects them (official CDP only) and proves the
session. The one flow that touches session secrets: cookie VALUES are never
logged/echoed/stored, injection is restricted to `allkeyshop.com`, Romain's
explicit submit only. Never self-triggered: a `NotLoggedInError` from another
stage stays a fail-closed STOP + error report.

## Fail-closed behavior

If anything is uncertain:
- stop;
- write an error report;
- do not fallback to another browser;
- do not continue to next candidate;
- do not submit.

## Submission constraints

The submitter must only process candidates from a validation JSON file.

For each candidate:
- refresh current merchant feed;
- locate exact current row;
- verify title, URL, merchant/store (price is a routing signal, never a
  blocker after URL/store confirm; page is recomputed by the current scan —
  EXECUTOR_RULES §6);
- open modal from that row;
- verify modal context;
- fill visible region/edition controls;
- click official visible submit button;
- refresh feed;
- verify post-save state: success = the offer disappeared from the refreshed
  feed, same available mode as the run.

No degraded mode.

## Coding preferences

- Python 3.
- Minimal dependencies.
- No new production dependency without asking Romain.
- Scripts must be CLI-friendly.
- Outputs should be JSON or JSONL where practical.
- Human reports go in Markdown.
- Never store passwords, 2FA codes, or session cookies.
- Never commit secrets.

## Reviewed decisions — do NOT re-tighten (an audit will re-flag these)

These are deliberate, Romain-reviewed calls. An adversarial audit re-derives them as
"findings" every time; leave them AS-IS unless Romain explicitly changes his mind.

- **Software region catch-all (`resolve_software_region`, Fable finding [7], DECLINED
  2026-09-07).** When an AKS software page has a SINGLE region and it is a
  GLOBAL/PUBLISHER-type bucket, a merchant offer is filed under it even when the offer's
  own region label looks US/EU-locked. Rationale: software licences are global and the
  merchant region label is usually noise (R31, 2026-08-11 — locked by
  `test_region_lone_country_is_not_forced`). Romain reviewed the audit finding that wanted
  to fail-close this and said "laisse [7] tel quel, ne durcis pas". A GLOBAL offer under a
  lone COUNTRY region still skips (unchanged); only the lone GLOBAL/PUBLISHER catch-all is
  kept. Do not add a US/EU-locked refusal here.

- **R25 duplicate guard REMOVED — do NOT re-add (Romain 2026-09-08).** The matcher used
  to skip a candidate whose merchant already had a price on the AKS page for the resolved
  region/edition ("`<merchant>` already lists a price … (R25)", added 2026-07-15 vs stale
  matched batches). Romain's ruling: **a PENDING offer is TO BE ADDED, period** — we do
  not check "already on AKS". The old guard matched by `merchantName`, so an AKS auto-sync
  / other-channel price (page merchant id ≠ feed `store_id`) false-skipped genuinely new
  offers; staleness is now covered by the stable pending feed + submit-time prove-gone. An
  audit will "find" the missing duplicate guard — leave it removed (EXECUTOR_RULES §6
  "Duplicate guard [R25] — RETIRED").

- **R18 "DLC bucket on the page ⇒ edition DLC(16)" for MARKERLESS titles — KEPT (Romain
  2026-09-11).** The R43 adversarial review showed live base-game pages carrying bucket 16
  (Stray Blade, Aliens Dark Descent, Dragon Quest III HD-2D Remake were entered DLC(16) on
  2026-09-10) and no deterministic page-level nature signal exists. Romain's ruling: "des
  fois, les titres n'ont pas de marqueur et sont des DLC" — the bucket keeps deciding, the
  three entries are not corrected. An audit will "find" this as a wrong-edition risk — leave
  R18 as is. (Titles that DO carry a DLC / Season Pass marker are governed by R43's stricter
  own-page + unnamed-DLC rules — those are not the same decision.)

- **Console targets = merchant-declared platforms only (R45 P1, Romain 2026-09-14) — do NOT
  add a sibling page (PS4 for a lone PS5 key, Xbox One for a lone Series key).** Romain's
  ruling: « clé PS5 seule = page PS5 seulement, pareil pour Xbox Series, PS4, Xbox One, Switch
  et Switch 2 ». The console branch (`_console_plan`, EXECUTOR_RULES §4.12 P1) files a key on
  the AKS page of every platform the merchant DECLARES and AKS has — a lone declared platform
  → that page only; a cross-gen declaration ("PS4 / PS5", "Xbox One / Series X|S") → both
  pages; the PC page only as a page-verified Xbox Play Anywhere target (P2). An audit will
  "find" the missing PS4 / Xbox One sibling ("the game exists on that page too") — there is
  no "page alone" policy and no switch for it; leave it out.

- **Kinguin "(valid until <Month> <Year>)" keys are ENTERED (Romain 2026-09-14).** Romain's
  ruling: « Kinguin valid until juin 2027 on rentre ». The note is an activation deadline,
  not a product word: `kinguin.guard_name` strips it — and only it — from the title the
  R01 / R16 / R01b guards and `detect_edition` read (`MerchantConfig.guard_name`, R32e),
  `resolve_name` peels it for the slug, `console_noise` carries it for console rows; the row
  is entered like any Kinguin title (implicit GLOBAL unless a code says otherwise). Before:
  79 rows / batch skipped "different/expanded product — extra words: ['VALID', 'UNTIL', …]".
  An audit will "find" a merchant note laundered past the name gate — it is not: every other
  word of the title is still compared with the AKS name, and only the "(valid until
  <Month>[,] <Year>)" spelling is stripped (any other form stays in the guard). Leave it
  entered; do not re-add the extra-words skip. Review fix (2026-09-14, same evening): the
  strip is anchored to the title END (158 / 158 corpus rows are trailing) — a mid-title
  note stays in the guard; do not widen the strip to the middle of a title.

- **K4G "Steam Altergift" = Steam GIFT, ENTERED (Romain 2026-09-14).** Romain's ruling:
  « Steam Altergift = Steam Gift on rentre sous gift tous les altergifts ».
  `k4g.gift_delivery` answers True for the whole word ALTERGIFT (`MerchantConfig.gift_delivery`,
  R32e) and `detect_region` layers the Steam GIFT bucket on the base region — GIFT (25) for
  no region / Global, GIFT EU (259) for Europe, GIFT US (2577) and GIFT UK (2572) for those
  bases; forbidden regions (North America, Americas) keep their precheck skip.
  **Corrected 2026-09-16 (`[R50]`, Romain: « si ça existe le fichier marchand ne devrait pas
  affirmer le contraire, fix la config marchand »):** this decision used to state that a US /
  UK base "has no Steam gift bucket" and therefore failed closed. That premise was FALSE —
  the live region dropdown has carried Steam Gift US (2577) and Steam Gift UK (2572) all
  along, and they are now mapped, so those rows ENTER under their own bucket. The safety
  property is untouched: a locked gift never widens to the platform-global gift (25). An
  audit will re-derive the old "no gift_us/gift_uk" sentence from the git history — it is
  obsolete, do not restore it. "Altergift" is never a product word (`k4g.guard_name` /
  `resolve_name` drop it). The explicit "skip category: ALTERGIFT" precheck of the same
  morning (open question `OPEN_QUESTION_ALTERGIFT`, "no confirmed bucket") is removed — an
  audit will "find" an unconfirmed gift bucket and want the skip back; do not re-add it.
  Review fixes on that ruling (2026-09-14, same evening — also reviewed, fail-closed):
  (1) the slug must AGREE (`-altergift-` / `-alter-gift-`, 217 / 218 rows) — a `-cd-key`
  slug against an Altergift title (offer 101030313 "Trine 5 …", the one such row), a slug
  with no delivery segment, or the mirror conflict is a `precheck` skip ("K4G delivery
  conflict …"), never GIFT (25) and never GLOBAL (2): an audit will "find" a missed gift —
  leave it refused, the row itself contradicts both classes; (2) « Steam Altergift = Steam
  Gift » is Steam-ONLY — a non-Steam Altergift is "… outside the Steam collocation" (never
  Battle.net GIFT 570 / 567); (3) « tous les altergifts » covers Kinguin's own "Altergift"
  delivery (`kinguin.gift_delivery`, same gates) — an audit will "find" that as scope creep
  over a K4G ruling; it is Romain's wording, leave it.

