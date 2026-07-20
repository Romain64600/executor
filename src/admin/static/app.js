'use strict';

/* AKS Executor admin page — vanilla JS, relative URLs only (the /executor/
   prefix is stripped by nginx). All dynamic content goes through textContent
   (never innerHTML with data) and every POST carries the CSRF header. */

const $ = (sel) => document.querySelector(sel);

let META = null;
let CURRENT = null; // { runId, detail, validation, stamp }
let POLL_TIMER = null;
let LOG_OFFSET = 0;
let INVARIANTS_GREEN = false;
let DIRTY = false;   // éditions non enregistrées dans le tableau de validation
let TICKING = false; // garde de réentrance du rafraîchissement automatique
let LAST_TERMINAL = null; // { text, ok } — dernier run terminé, affiché en pied de page

const IDLE_REFRESH_MS = 10000;

// Marchands connus (storeId AKS) — juste un raccourci de saisie, "Autre" reste
// disponible pour un marchand qui n'y figure pas encore.
const MERCHANTS = [
  { name: 'Kinguin', storeId: '58' },
  { name: 'G2A', storeId: '38' },
  { name: 'Driffle', storeId: '127' },
  { name: 'Eneba', storeId: '19' },
  { name: 'GameSeal', storeId: '126' },
  { name: 'K4G', storeId: '92' },
  { name: 'Gameboost', storeId: '157' },
  { name: 'CJS-CDKeys', storeId: '30' },
  { name: 'Instant Gaming', storeId: '28' },
  { name: 'Gamivo', storeId: '51' },
  { name: 'Allyouplay', storeId: '17' },
  { name: 'Difmark', storeId: '167' },
];

// ---------------------------------------------------------------- helpers

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === 'text') node.textContent = value;
    else if (key === 'class') node.className = value;
    else if (key.startsWith('data-')) node.setAttribute(key, value);
    else node[key] = value;
  }
  for (const child of children) node.appendChild(child);
  return node;
}

async function api(path, options = {}) {
  const headers = { 'X-AKS-Admin': '1' };
  if (options.body) headers['Content-Type'] = 'application/json';
  const response = await fetch(path, { ...options, headers });
  const text = await response.text();
  let data;
  try { data = JSON.parse(text); } catch { data = { raw: text }; }
  if (!response.ok) {
    const err = (data && data.error) || { code: String(response.status), message: text };
    const error = new Error(err.message || 'erreur inconnue');
    error.code = err.code;
    error.detail = err.detail;
    throw error;
  }
  return data;
}

function showError(err) {
  const banner = $('#error');
  banner.textContent = err.code ? `[${err.code}] ${err.message}` : String(err.message || err);
  if (err.detail) banner.textContent += ' — ' + JSON.stringify(err.detail);
  banner.classList.remove('hidden');
}

function clearError() { $('#error').classList.add('hidden'); }

function showNotice(message) {
  const banner = $('#notice');
  banner.textContent = message;
  banner.classList.remove('hidden');
  setTimeout(() => banner.classList.add('hidden'), 6000);
}

// ---------------------------------------------------------------- theme

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  $('#theme-toggle').textContent = theme === 'dark' ? '☀️ Clair' : '🌙 Sombre';
  try { localStorage.setItem('aks-admin-theme', theme); } catch { /* stockage indisponible */ }
}

function initTheme() {
  let theme = 'dark'; // sombre par défaut
  try { theme = localStorage.getItem('aks-admin-theme') || 'dark'; } catch { /* idem */ }
  applyTheme(theme);
  $('#theme-toggle').addEventListener('click', () => {
    const current = document.documentElement.getAttribute('data-theme') || 'dark';
    applyTheme(current === 'dark' ? 'light' : 'dark');
  });
}

// ------------------------------------------------------ nouveau run (stage 1)

function initMerchantSelect() {
  const select = $('#new-merchant');
  for (const m of MERCHANTS) {
    select.appendChild(el('option', { value: m.name, text: `${m.name} (store ${m.storeId})` }));
  }
  select.addEventListener('change', () => {
    const custom = select.value === 'custom';
    $('#new-merchant-custom').classList.toggle('hidden', !custom);
    const known = MERCHANTS.find((m) => m.name === select.value);
    if (known) $('#new-store-id').value = known.storeId;
    else if (!custom) $('#new-store-id').value = '';
  });
}

async function startExtract() {
  clearError();
  const select = $('#new-merchant');
  const merchant = select.value === 'custom'
    ? $('#new-merchant-custom').value.trim()
    : select.value;
  const storeId = $('#new-store-id').value.trim();
  const hint = $('#new-extract-hint');
  if (!merchant || !storeId) {
    hint.textContent = 'Marchand et store ID requis.';
    return;
  }
  hint.textContent = '';
  $('#start-extract').disabled = true;
  try {
    const result = await api('api/extract', {
      method: 'POST',
      body: JSON.stringify({ merchant, store_id: storeId }),
    });
    hint.textContent = `Extraction lancée : ${result.run_id}`;
    await loadRuns();
    await openRun(result.run_id);
  } catch (err) {
    showError(err);
  } finally {
    $('#start-extract').disabled = false;
  }
}

// ------------------------------------------------------ matching (stage 3)

async function startMatch() {
  if (!CURRENT) return;
  clearError();
  const maxRaw = $('#match-max').value.trim();
  const body = {};
  if (maxRaw) body.max_candidates = Number(maxRaw);
  $('#start-match').disabled = true;
  $('#match-state').textContent = '…';
  try {
    const result = await api(`api/runs/${encodeURIComponent(CURRENT.runId)}/match`, {
      method: 'POST',
      body: JSON.stringify(body),
    });
    $('#match-state').textContent = `matching lancé (pid ${result.pid}) — la table de validation se remplira à la fin`;
    // Reuse the run progress/poll machinery; renderFinal re-opens the run so
    // the report + candidates appear when the match completes.
    $('#progress').classList.remove('hidden');
    $('#progress-title').textContent = `Matching lancé (pid ${result.pid})`;
    $('#events').textContent = result.argv.join(' ') + '\n';
    $('#plan-summary').textContent = '';
    LOG_OFFSET = 0;
    startPolling();
  } catch (err) {
    showError(err);
    $('#match-state').textContent = '✘';
  } finally {
    $('#start-match').disabled = false;
  }
}

// ---------------------------------------------------------------- run list

async function loadRuns() {
  try {
    const { runs, busy } = await api('api/runs');
    updateBusyBadge(busy);
    const list = $('#runs');
    list.textContent = '';
    for (const run of runs) {
      const stages = run.stages || {};
      const badges = [];
      if (stages.matched) badges.push(`${stages.candidates_count ?? '?'} cand.`);
      if (stages.validated) badges.push(`validé (${stages.approved_count ?? 0})`);
      if (run.created_count) badges.push(`✔ ${run.created_count} ajoutée(s)`);
      else if (stages.submit && stages.submit.dry_run) badges.push('dry-run');
      const item = el('li', {}, [
        el('span', { class: 'run-id', text: run.run_id }),
        el('span', { class: 'run-info', text: [run.merchant || '?', ...badges].join(' · ') }),
      ]);
      item.addEventListener('click', () => openRun(run.run_id));
      if (CURRENT && CURRENT.runId === run.run_id) item.classList.add('selected');
      list.appendChild(item);
    }
  } catch (err) { showError(err); }
}

// ---------------------------------------------------------------- run panel

function detailStamp(detail) {
  // Empreinte de l'état serveur d'un run : sha des candidats + mtime/taille de
  // chaque artefact (dont admin_submit.json) + statuts — tout changement
  // (re-match, validation, submit, catalog) la fait bouger.
  return JSON.stringify([
    detail.candidates_sha256, detail.files, detail.stages,
    detail.created_count, detail.failed_count,
  ]);
}

async function openRun(runId) {
  clearError();
  stopPolling();
  $('#stale').classList.add('hidden');
  INVARIANTS_GREEN = false;
  try {
    const detail = await api(`api/runs/${encodeURIComponent(runId)}`);
    CURRENT = { runId, detail, validation: null, stamp: detailStamp(detail) };
    $('#run-panel').classList.remove('hidden');
    $('#run-title').textContent = runId;
    const stages = detail.stages || {};
    $('#run-meta').textContent =
      `${detail.merchant ?? '?'} — store ${detail.store_id ?? '?'}` +
      (detail.store_id_error ? ` — ⚠ ${detail.store_id_error}` : '') +
      ` — ${stages.candidates_count ?? 0} candidat(s), ${stages.approved_count ?? 0} approuvé(s)` +
      (detail.created_count ? `, ✔ ${detail.created_count} déjà ajoutée(s)` : '') +
      (detail.failed_count ? `, ✘ ${detail.failed_count} en échec` : '');
    await Promise.all([loadReport(runId), loadValidation(runId)]);
    renderSubmitPanel();
    await refreshStatus();
    await loadRuns();
  } catch (err) { showError(err); }
}

async function loadReport(runId) {
  const response = await fetch(`api/runs/${encodeURIComponent(runId)}/report`);
  $('#report').textContent = response.ok
    ? await response.text()
    : 'report.txt absent pour ce run.';
}

async function loadValidation(runId) {
  const payload = await api(`api/runs/${encodeURIComponent(runId)}/validation`).catch((err) => {
    if (err.code === 'no_candidates') return null;
    throw err;
  });
  CURRENT.validation = payload;
  const tbody = $('#candidates tbody');
  tbody.textContent = '';
  $('#catalog-hint').classList.toggle('hidden', !payload || payload.catalog.present);
  if (!payload) {
    $('#validation-box').classList.add('hidden');
    return;
  }
  $('#validation-box').classList.remove('hidden');
  const approvedSet = new Set(payload.approved_fingerprints || []);
  const catalog = payload.catalog;
  const history = payload.submit_history || {};
  if (payload.validation && payload.validation.validated_by) {
    $('#validated-by').value = payload.validation.validated_by;
  }
  let createdCount = 0;
  let failedCount = 0;
  payload.candidates.forEach((candidate, index) => {
    const fingerprint = fp(candidate);
    const outcome = history[String(candidate.offer.offer_id)] || null;
    const isCreated = Boolean(outcome && outcome.status === 'created');
    const isFailed = Boolean(outcome && outcome.status === 'failed');
    if (isCreated) createdCount += 1;
    if (isFailed) failedCount += 1;

    const row = el('tr', { 'data-fingerprint': fingerprint });
    if (isCreated) row.classList.add('created');
    if (isFailed) row.classList.add('failed');
    row.appendChild(el('td', {}, [
      el('input', {
        type: 'checkbox',
        class: 'approve',
        checked: !isCreated && approvedSet.has(fingerprint),
        disabled: isCreated,
        title: isCreated ? 'Déjà ajoutée sur AKS — ré-ajout bloqué' : '',
      }),
    ]));
    row.appendChild(el('td', { text: String(index + 1) }));

    const statusCell = el('td', { class: 'status-cell' });
    if (isCreated) {
      statusCell.appendChild(el('span', {
        class: 'status status-created',
        text: '✔ ajoutée',
        title: `Créée sur AKS${outcome.at ? ' le ' + outcome.at : ''} — ${outcome.post_save || ''}`,
      }));
      if (outcome.at) statusCell.appendChild(el('div', { class: 'status-detail', text: outcome.at }));
    } else if (isFailed) {
      statusCell.appendChild(el('span', {
        class: 'status status-failed',
        text: '✘ échec',
        title: outcome.blocker || 'échec précédent',
      }));
      statusCell.appendChild(el('div', {
        class: 'status-detail',
        text: (outcome.blocker || '').slice(0, 90),
      }));
    } else {
      statusCell.appendChild(el('span', { class: 'status status-pending', text: '⏳ en attente' }));
    }
    row.appendChild(statusCell);

    const offerCell = el('td', {}, [
      el('div', { class: 'title', text: candidate.offer.name }),
      el('a', { href: candidate.offer.url, target: '_blank', rel: 'noreferrer', text: candidate.offer.url }),
    ]);
    if (candidate.operator_override) {
      offerCell.appendChild(el('div', {
        class: 'override-tag',
        text: `modifié par ${candidate.operator_override.by} le ${candidate.operator_override.at}`,
      }));
    }
    row.appendChild(offerCell);
    row.appendChild(el('td', {}, [
      el('div', { class: 'title', text: `${candidate.aks_product_id} — ${candidate.aks_name}` }),
      el('a', { href: candidate.aks_url, target: '_blank', rel: 'noreferrer', text: candidate.aks_url }),
    ]));
    row.appendChild(el('td', {}, [
      select('platform', META.platforms.map((p) => ({ key: p, text: META.platform_labels[p] || p })),
        candidate.platform, !isCreated),
    ]));
    row.appendChild(el('td', {}, [
      select('region', catalog.regions, candidate.region.id, catalog.present && !isCreated,
        `${candidate.region.label} (${candidate.region.id})`),
    ]));
    row.appendChild(el('td', {}, [
      select('edition', catalog.editions, candidate.edition.id, catalog.present && !isCreated,
        `${candidate.edition.label} (${candidate.edition.id})`),
    ]));

    const actionCell = el('td', { class: 'action-cell' });
    if (!isCreated) {
      const trash = el('button', {
        type: 'button',
        class: 'trash',
        text: '🗑',
        title: 'Marquer comme erreur — sera supprimée du run à l\'enregistrement (au lieu d\'être soumise)',
      });
      trash.addEventListener('click', () => {
        const marked = row.classList.toggle('to-delete');
        const approve = row.querySelector('.approve');
        approve.checked = false;
        approve.disabled = marked;
        for (const kind of ['platform', 'region', 'edition']) {
          const sel = row.querySelector(`select.${kind}`);
          sel.disabled = marked || (kind !== 'platform' && !catalog.present);
        }
        trash.textContent = marked ? '↩' : '🗑';
        trash.title = marked
          ? 'Annuler la suppression'
          : 'Marquer comme erreur — sera supprimée du run à l\'enregistrement (au lieu d\'être soumise)';
        DIRTY = true;
      });
      actionCell.appendChild(trash);
    }
    row.appendChild(actionCell);
    tbody.appendChild(row);
  });

  const pendingCount = payload.candidates.length - createdCount - failedCount;
  const summary = $('#status-summary');
  summary.classList.toggle('hidden', createdCount + failedCount === 0);
  summary.textContent =
    `✔ ${createdCount} déjà ajoutée(s) (verrouillées — ré-ajout bloqué côté serveur) · ` +
    `✘ ${failedCount} en échec (ré-approuvables) · ⏳ ${pendingCount} en attente`;
  DIRTY = false; // le tableau vient d'être rendu depuis l'état serveur
}

function fp(candidate) {
  return `${candidate.offer.offer_id}|${candidate.aks_product_id}|${candidate.region.id}|${candidate.edition.id}`;
}

function select(kind, options, currentKey, enabled, currentLabel) {
  const node = el('select', { class: kind, disabled: !enabled });
  const keys = new Set(options.map((o) => String(o.key)));
  if (!keys.has(String(currentKey))) {
    node.appendChild(el('option', {
      value: String(currentKey),
      text: currentLabel || String(currentKey),
      selected: true,
    }));
  }
  for (const option of options) {
    node.appendChild(el('option', {
      value: option.key,
      text: option.text,
      selected: String(currentKey) === String(option.key),
    }));
  }
  node.setAttribute('data-original', String(currentKey));
  return node;
}

// ---------------------------------------------------------------- validation save

function checkAll() {
  for (const box of document.querySelectorAll('#candidates tbody .approve')) {
    if (!box.disabled) box.checked = true;
  }
  DIRTY = true;
}

async function saveValidation() {
  clearError();
  const payload = CURRENT.validation;
  if (!payload) return;
  const decisions = [];
  for (const row of document.querySelectorAll('#candidates tbody tr')) {
    const fingerprint = row.getAttribute('data-fingerprint');
    if (row.classList.contains('to-delete')) {
      decisions.push({ fingerprint, delete: true });
      continue;
    }
    const decision = {
      fingerprint,
      approve: row.querySelector('.approve').checked,
    };
    const override = {};
    for (const kind of ['platform', 'region', 'edition']) {
      const sel = row.querySelector(`select.${kind}`);
      if (sel && !sel.disabled && sel.value !== sel.getAttribute('data-original')) {
        override[kind === 'platform' ? 'platform' : `${kind}_id`] = sel.value;
      }
    }
    if (Object.keys(override).length) decision.override = override;
    decisions.push(decision);
  }
  try {
    $('#validation-state').textContent = 'enregistrement…';
    const result = await api(`api/runs/${encodeURIComponent(CURRENT.runId)}/validation`, {
      method: 'POST',
      body: JSON.stringify({
        candidates_sha256: payload.candidates_sha256,
        validated_by: $('#validated-by').value.trim(),
        decisions,
      }),
    });
    $('#validation-state').textContent =
      `✔ ${result.approved_count} approuvé(s)` +
      (result.overrides.length ? `, ${result.overrides.length} override(s)` : '') +
      ((result.deleted || []).length ? `, 🗑 ${result.deleted.length} supprimée(s)` : '');
    showNotice('Validation enregistrée — triple candidates/validation/approved régénéré.');
    await openRun(CURRENT.runId);
  } catch (err) {
    $('#validation-state').textContent = '✘ refusé';
    showError(err);
  }
}

// ---------------------------------------------------------------- submit

function selectedMode() {
  return document.querySelector('input[name="mode"]:checked').value;
}

function renderSubmitPanel() {
  const detail = CURRENT.detail;
  const approved = detail.stages.approved_count || 0;
  $('#submit-target').textContent =
    `Cible : ${detail.merchant ?? '?'} (store ${detail.store_id ?? '?'}) — ${approved} offre(s) approuvée(s)`;
  updateSubmitButton();
}

function updateSubmitButton() {
  const approved = (CURRENT && CURRENT.detail.stages.approved_count) || 0;
  const button = $('#real-submit');
  button.disabled = !(approved > 0 && INVARIANTS_GREEN);
  $('#submit-hint').textContent = button.disabled
    ? 'Requis : validation enregistrée + invariants verts.'
    : '';
}

async function checkInvariants() {
  clearError();
  $('#invariants-state').textContent = 'vérification…';
  try {
    const { exit_code, report } = await api('api/invariants/check', { method: 'POST', body: '{}' });
    INVARIANTS_GREEN = Boolean(report.ok && report.authoritative);
    $('#invariants-state').textContent = INVARIANTS_GREEN
      ? '✔ invariants verts (authoritative)'
      : `✘ exit ${exit_code} — ok=${report.ok} authoritative=${report.authoritative}`;
    if (!INVARIANTS_GREEN && report.checks) {
      const failing = report.checks.filter((c) => !c.ok).map((c) => c.name).join(', ');
      if (failing) $('#invariants-state').textContent += ` (échecs : ${failing})`;
    }
  } catch (err) {
    INVARIANTS_GREEN = false;
    $('#invariants-state').textContent = '✘ vérification impossible';
    showError(err);
  }
  updateSubmitButton();
}

function maxPagesValue() {
  // Shared by submit/dry-run/catalog — defaults (empty) to the script's own
  // 40. Raise it for a large feed (Difmark, 382 pages, 2026-07-17): the
  // default cap made the feed-index scan abort "coverage unproven" even
  // though the feed itself was healthy.
  return $('#max-pages').value.trim();
}

function argvPreview(dryRun) {
  const detail = CURRENT.detail;
  const limit = $('#limit').value.trim();
  const maxPages = maxPagesValue();
  const parts = [
    'python3', 'scripts/05_submit.py',
    `runs/${CURRENT.runId}/approved.json`,
    '--merchant', detail.merchant,
    '--store-id', detail.store_id,
    '--mode', selectedMode(),
  ];
  if (!dryRun) parts.push('--submit');
  if (limit) parts.push('--limit', limit);
  if (maxPages) parts.push('--max-pages', maxPages);
  return parts.join(' ');
}

async function startRun(body) {
  const result = await api(`api/runs/${encodeURIComponent(CURRENT.runId)}/submit`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
  $('#progress').classList.remove('hidden');
  $('#progress-title').textContent =
    `${body.dry_run ? 'Dry-run' : 'Submit'} lancé (pid ${result.pid})`;
  $('#events').textContent = result.argv.join(' ') + '\n';
  $('#plan-summary').textContent = '';
  LOG_OFFSET = 0;
  startPolling();
}

async function dryRun() {
  clearError();
  const limit = $('#limit').value.trim();
  const maxPages = maxPagesValue();
  try {
    await startRun({
      mode: selectedMode(),
      limit: limit ? Number(limit) : null,
      dry_run: true,
      max_pages: maxPages ? Number(maxPages) : null,
    });
  } catch (err) { showError(err); }
}

// AS1 (audit 2026-07-17) : le sha du lot affiché au moment où le dialogue GO
// s'ouvre — renvoyé avec le submit réel pour que le serveur refuse si une
// validation concurrente a régénéré approved.json entre-temps.
let CONFIRM_SHA = null;

function openConfirmDialog() {
  $('#confirm-argv').textContent = argvPreview(false);
  const approved = CURRENT.detail.stages.approved_count || 0;
  const mode = selectedMode();
  const batch = mode === 'safe' ? approved : Math.min(approved, META.canary_limit);
  $('#confirm-count').textContent =
    `Mode ${mode} : jusqu'à ${batch} offre(s) sur ${approved} approuvée(s).`;
  CONFIRM_SHA = CURRENT.validation ? CURRENT.validation.approved_sha256 : null;
  $('#confirm-input').value = '';
  $('#confirm-go').disabled = true;
  $('#confirm-dialog').showModal();
}

async function confirmedSubmit() {
  $('#confirm-dialog').close();
  clearError();
  const limit = $('#limit').value.trim();
  const maxPages = maxPagesValue();
  try {
    await startRun({
      mode: selectedMode(),
      limit: limit ? Number(limit) : null,
      dry_run: false,
      confirm: 'GO',
      approved_sha256: CONFIRM_SHA,
      by: $('#validated-by').value.trim() || undefined,
      max_pages: maxPages ? Number(maxPages) : null,
    });
  } catch (err) { showError(err); }
}

async function fetchCatalog() {
  clearError();
  const maxPages = maxPagesValue();
  try {
    const result = await api(`api/runs/${encodeURIComponent(CURRENT.runId)}/catalog`, {
      method: 'POST',
      body: JSON.stringify({ max_pages: maxPages ? Number(maxPages) : null }),
    });
    $('#progress').classList.remove('hidden');
    $('#progress-title').textContent = `Récupération du catalogue (pid ${result.pid})`;
    $('#events').textContent = '';
    $('#plan-summary').textContent = '';
    LOG_OFFSET = 0;
    startPolling();
  } catch (err) { showError(err); }
}

// ---------------------------------------------------------------- polling

function stopPolling() {
  if (POLL_TIMER) { clearTimeout(POLL_TIMER); POLL_TIMER = null; }
}

function startPolling() {
  stopPolling();
  POLL_TIMER = setTimeout(pollStatus, 1000);
}

function eventLine(event) {
  if (event.event === 'submit_offer') {
    return event.success
      ? `✔ ${event.offer_id} — ${event.post_save}`
      : `✘ ${event.offer_id} — ${event.blocker}`;
  }
  if (event.event === 'feed_indexed') return `feed indexé : ${event.offers} offres`;
  if (event.event === 'feed_sweep') return `sweep ${event.sweep} : ${event.distinct} offres distinctes`;
  if (event.event === 'run_stopped') return `⛔ run arrêté : ${event.reason || ''}`;
  if (event.event === 'skip') return `— skip ${event.offer_id} : ${event.reason}`;
  if (event.event === 'admin_submit_finished') return `terminé (exit ${event.exit_code}, ${event.state})`;
  return null;
}

async function pollStatus() {
  if (!CURRENT) return;
  try {
    const status = await api(
      `api/runs/${encodeURIComponent(CURRENT.runId)}/submit/status?offset=${LOG_OFFSET}`
    );
    LOG_OFFSET = status.offset;
    updateBusyBadge(status.busy);
    const box = $('#events');
    for (const event of status.events || []) {
      // Matching progression: a single live counter in the title, not 45
      // appended lines (2026-07-20).
      if (event.event === 'match_progress') {
        $('#progress-title').textContent =
          `Matching : ${event.done}/${event.total} — ${event.candidates} candidat(s), ${event.skipped} écarté(s)`;
        continue;
      }
      const line = eventLine(event);
      if (line) {
        box.textContent += `${event.ts}  ${line}\n`;
        box.scrollTop = box.scrollHeight;
      }
    }
    if (status.state === 'running') {
      POLL_TIMER = setTimeout(pollStatus, 2000);
      return;
    }
    if (status.state !== 'idle') renderFinal(status);
  } catch (err) {
    showError(err);
  }
}

// Rendu pur (pas de gestion du polling ni de re-fetch) — partagé par
// renderFinal (fin naturelle d'un polling) et refreshStatus (ouverture d'un
// run déjà terminé), pour que les deux affichent la même chose sans
// dépendre l'un de l'autre.
function renderStatusSummary(status) {
  const summary = $('#plan-summary');
  summary.textContent = '';
  $('#progress').classList.remove('hidden');
  $('#progress-title').textContent =
    `${status.kind || 'run'} — ${status.state} (exit ${status.exit_code})`;
  const plan = status.submit_plan;
  let footerHeader = null;
  if (plan && !plan.error) {
    const header = plan.created === null
      ? `DRY-RUN — ${(plan.plan || []).length} offre(s) planifiée(s)`
      : `créées : ${plan.created} / tentatives : ${plan.write_attempts}` +
        (plan.aborted ? ` — ABORTED: ${plan.aborted}` : '') +
        (plan.stopped ? ` — STOPPED: ${plan.stopped}` : '');
    footerHeader = header;
    summary.appendChild(el('p', { class: 'plan-header', text: header }));
    const list = el('ul', { class: 'plan-list' });
    for (const entry of plan.plan || []) {
      const state = entry.submitted
        ? `✔ ${entry.post_save || 'soumis'}`
        : entry.blocker
          ? `✘ ${entry.blocker}`
          : entry.would_submit ? '→ serait soumis' : entry.ready ? 'prêt' : 'non prêt';
      list.appendChild(el('li', {
        text: `${entry.offer_id} — ${entry.merchant_title || ''} — ${state}`,
      }));
    }
    summary.appendChild(list);
  }
  if (status.state === 'failed' && status.stdout_tail) {
    summary.appendChild(el('pre', { class: 'stdout', text: status.stdout_tail.slice(-4000) }));
  }
  const ok = status.state === 'done' && !(plan && (plan.aborted || plan.error));
  LAST_TERMINAL = {
    text: `${ok ? '✔' : '✘'} ${status.kind || 'run'} sur ${CURRENT.runId} — ${status.state}` +
      (footerHeader ? ` — ${footerHeader}` : ''),
    ok,
  };
  updateStatusFooter(null);
}

function renderFinal(status) {
  stopPolling();
  renderStatusSummary(status);
  // refresh everything after a terminal state (catalog file, approved, plan…)
  openRun(CURRENT.runId);
}

async function refreshStatus() {
  // Toujours repartir d'un panneau vide : sans ça, un run dont la dernière
  // action est déjà terminée (ex. une extraction fraîche, ou un submit fini
  // il y a longtemps) hérite silencieusement du journal/plan du run
  // précédemment ouvert — vécu en direct (2026-07-16, Romain) : ouvrir un
  // run Kinguin flambant neuf affichait encore le plan de soumission d'Eneba.
  stopPolling();
  $('#progress').classList.add('hidden');
  $('#events').textContent = '';
  $('#plan-summary').textContent = '';
  const status = await api(
    `api/runs/${encodeURIComponent(CURRENT.runId)}/submit/status?offset=0`
  ).catch(() => null);
  if (!status) return;
  LOG_OFFSET = status.offset;
  updateBusyBadge(status.busy);
  if (status.state === 'running') {
    $('#progress').classList.remove('hidden');
    $('#progress-title').textContent = `${status.kind} en cours (pid ${status.pid})`;
    startPolling();
  } else if (status.state && status.state !== 'idle') {
    renderStatusSummary(status);
    if (status.state === 'interrupted' || status.state === 'orphaned') {
      showError(new Error(status.note || 'run interrompu — inspecter le feed et submit_plan.json'));
    }
  }
}

function updateBusyBadge(busy) {
  const badge = $('#busy');
  if (busy) {
    badge.textContent = `⏳ ${busy.kind} en cours sur ${busy.run_id}`;
    badge.classList.remove('hidden');
  } else {
    badge.classList.add('hidden');
  }
  updateStatusFooter(busy);
}

/* Pied de page persistant (visible en scrollant, contrairement au badge de
   l'en-tête) : priorité au run actif, sinon le résumé du dernier run terminé
   (posé par renderFinal), sinon "Inactif". Répond directement au besoin de
   voir la fin d'un ajout d'offres validées sans rester les yeux sur la page. */
function updateStatusFooter(busy) {
  const footer = $('#status-footer');
  if (busy) {
    footer.textContent = `⏳ ${busy.kind} en cours sur ${busy.run_id}`;
    footer.className = 'busy';
    return;
  }
  if (LAST_TERMINAL) {
    footer.textContent = LAST_TERMINAL.text;
    footer.className = LAST_TERMINAL.ok ? 'done-ok' : 'done-bad';
    return;
  }
  footer.textContent = 'Inactif';
  footer.className = 'idle';
}

// ------------------------------------------------- rafraîchissement auto

/* Toutes les 10 s (onglet visible) : la liste des runs se recharge, et le run
   ouvert est comparé à son empreinte serveur. S'il a changé : rechargement
   silencieux — sauf éditions non enregistrées (bandeau "Recharger" à la place,
   jamais d'écrasement). Un submit lancé hors page (CLI) est aussi visible :
   ses événements JSONL s'affichent au fil de l'eau. */
async function idleTick() {
  if (TICKING || document.hidden) return;
  TICKING = true;
  try {
    await loadRuns();
    if (!CURRENT || POLL_TIMER || $('#confirm-dialog').open) return;
    const detail = await api(`api/runs/${encodeURIComponent(CURRENT.runId)}`);
    const stamp = detailStamp(detail);
    if (stamp !== CURRENT.stamp) {
      if (DIRTY) {
        $('#stale').classList.remove('hidden');
      } else {
        await openRun(CURRENT.runId);
      }
      return;
    }
    // état inchangé sur disque : streamer l'éventuelle activité du log
    // (ex. submit lancé en CLI — il n'écrit ses artefacts qu'à la fin)
    const status = await api(
      `api/runs/${encodeURIComponent(CURRENT.runId)}/submit/status?offset=${LOG_OFFSET}`
    );
    LOG_OFFSET = status.offset;
    if (status.state === 'running' && !POLL_TIMER) {
      $('#progress').classList.remove('hidden');
      $('#progress-title').textContent = `${status.kind} en cours (pid ${status.pid})`;
      startPolling();
      return;
    }
    const lines = (status.events || [])
      .map((event) => ({ ts: event.ts, line: eventLine(event) }))
      .filter((entry) => entry.line);
    if (lines.length) {
      $('#progress').classList.remove('hidden');
      if (!$('#progress-title').textContent) {
        $('#progress-title').textContent = 'activité détectée (log du run)';
      }
      const box = $('#events');
      for (const entry of lines) box.textContent += `${entry.ts}  ${entry.line}\n`;
      box.scrollTop = box.scrollHeight;
    }
  } catch { /* réseau/serveur indisponible : nouvel essai au tick suivant */ }
  finally { TICKING = false; }
}

// ---------------------------------------------------------------- init

async function init() {
  initTheme();
  try {
    META = await api('api/meta');
  } catch (err) {
    showError(err);
    return;
  }
  initMerchantSelect();
  $('#start-extract').addEventListener('click', startExtract);
  $('#start-match').addEventListener('click', startMatch);
  $('#refresh-runs').addEventListener('click', loadRuns);
  $('#check-all').addEventListener('click', checkAll);
  $('#save-validation').addEventListener('click', saveValidation);
  $('#check-invariants').addEventListener('click', checkInvariants);
  $('#dry-run').addEventListener('click', dryRun);
  $('#real-submit').addEventListener('click', openConfirmDialog);
  $('#fetch-catalog').addEventListener('click', fetchCatalog);
  $('#confirm-cancel').addEventListener('click', () => $('#confirm-dialog').close());
  $('#confirm-go').addEventListener('click', confirmedSubmit);
  $('#confirm-input').addEventListener('input', (event) => {
    $('#confirm-go').disabled = event.target.value.trim() !== 'GO';
  });
  // suivi des éditions non enregistrées (protège contre l'auto-rechargement)
  $('#candidates').addEventListener('change', () => { DIRTY = true; });
  $('#validated-by').addEventListener('input', () => { DIRTY = true; });
  $('#stale-reload').addEventListener('click', () => openRun(CURRENT.runId));
  setInterval(idleTick, IDLE_REFRESH_MS);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) idleTick(); });
  await loadRuns();
}

init();
