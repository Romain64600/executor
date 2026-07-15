'use strict';

/* AKS Executor admin page — vanilla JS, relative URLs only (the /executor/
   prefix is stripped by nginx). All dynamic content goes through textContent
   (never innerHTML with data) and every POST carries the CSRF header. */

const $ = (sel) => document.querySelector(sel);

let META = null;
let CURRENT = null; // { runId, detail, validation }
let POLL_TIMER = null;
let LOG_OFFSET = 0;
let INVARIANTS_GREEN = false;

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

// ---------------------------------------------------------------- run list

async function loadRuns() {
  clearError();
  try {
    const { runs } = await api('api/runs');
    const list = $('#runs');
    list.textContent = '';
    for (const run of runs) {
      const stages = run.stages || {};
      const badges = [];
      if (stages.matched) badges.push(`${stages.candidates_count ?? '?'} cand.`);
      if (stages.validated) badges.push(`validé (${stages.approved_count ?? 0})`);
      if (stages.submit) badges.push(stages.submit.dry_run ? 'dry-run' : `soumis: ${stages.submit.created}`);
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

async function openRun(runId) {
  clearError();
  stopPolling();
  INVARIANTS_GREEN = false;
  try {
    const detail = await api(`api/runs/${encodeURIComponent(runId)}`);
    CURRENT = { runId, detail, validation: null };
    $('#run-panel').classList.remove('hidden');
    $('#run-title').textContent = runId;
    const stages = detail.stages || {};
    $('#run-meta').textContent =
      `${detail.merchant ?? '?'} — store ${detail.store_id ?? '?'}` +
      (detail.store_id_error ? ` — ⚠ ${detail.store_id_error}` : '') +
      ` — ${stages.candidates_count ?? 0} candidat(s), ${stages.approved_count ?? 0} approuvé(s)`;
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
  if (payload.validation && payload.validation.validated_by) {
    $('#validated-by').value = payload.validation.validated_by;
  }
  payload.candidates.forEach((candidate, index) => {
    const fingerprint = fp(candidate);
    const row = el('tr', { 'data-fingerprint': fingerprint });
    row.appendChild(el('td', {}, [
      el('input', { type: 'checkbox', class: 'approve', checked: approvedSet.has(fingerprint) }),
    ]));
    row.appendChild(el('td', { text: String(index + 1) }));
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
        candidate.platform, true),
    ]));
    row.appendChild(el('td', {}, [
      select('region', catalog.regions, candidate.region.id, catalog.present,
        `${candidate.region.label} (${candidate.region.id})`),
    ]));
    row.appendChild(el('td', {}, [
      select('edition', catalog.editions, candidate.edition.id, catalog.present,
        `${candidate.edition.label} (${candidate.edition.id})`),
    ]));
    tbody.appendChild(row);
  });
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

async function saveValidation() {
  clearError();
  const payload = CURRENT.validation;
  if (!payload) return;
  const decisions = [];
  for (const row of document.querySelectorAll('#candidates tbody tr')) {
    const decision = {
      fingerprint: row.getAttribute('data-fingerprint'),
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
      (result.overrides.length ? `, ${result.overrides.length} override(s)` : '');
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

function argvPreview(dryRun) {
  const detail = CURRENT.detail;
  const limit = $('#limit').value.trim();
  const parts = [
    'python3', 'scripts/05_submit.py',
    `runs/${CURRENT.runId}/approved.json`,
    '--merchant', detail.merchant,
    '--store-id', detail.store_id,
    '--mode', selectedMode(),
  ];
  if (!dryRun) parts.push('--submit');
  if (limit) parts.push('--limit', limit);
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
  try {
    await startRun({
      mode: selectedMode(),
      limit: limit ? Number(limit) : null,
      dry_run: true,
    });
  } catch (err) { showError(err); }
}

function openConfirmDialog() {
  $('#confirm-argv').textContent = argvPreview(false);
  const approved = CURRENT.detail.stages.approved_count || 0;
  const mode = selectedMode();
  const batch = mode === 'safe' ? approved : Math.min(approved, META.canary_limit);
  $('#confirm-count').textContent =
    `Mode ${mode} : jusqu'à ${batch} offre(s) sur ${approved} approuvée(s).`;
  $('#confirm-input').value = '';
  $('#confirm-go').disabled = true;
  $('#confirm-dialog').showModal();
}

async function confirmedSubmit() {
  $('#confirm-dialog').close();
  clearError();
  const limit = $('#limit').value.trim();
  try {
    await startRun({
      mode: selectedMode(),
      limit: limit ? Number(limit) : null,
      dry_run: false,
      confirm: 'GO',
      by: $('#validated-by').value.trim() || undefined,
    });
  } catch (err) { showError(err); }
}

async function fetchCatalog() {
  clearError();
  try {
    const result = await api(`api/runs/${encodeURIComponent(CURRENT.runId)}/catalog`, {
      method: 'POST',
      body: '{}',
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

function renderFinal(status) {
  stopPolling();
  const summary = $('#plan-summary');
  summary.textContent = '';
  $('#progress').classList.remove('hidden');
  $('#progress-title').textContent =
    `${status.kind || 'run'} — ${status.state} (exit ${status.exit_code})`;
  const plan = status.submit_plan;
  if (plan && !plan.error) {
    const header = plan.created === null
      ? `DRY-RUN — ${(plan.plan || []).length} offre(s) planifiée(s)`
      : `créées : ${plan.created} / tentatives : ${plan.write_attempts}` +
        (plan.aborted ? ` — ABORTED: ${plan.aborted}` : '') +
        (plan.stopped ? ` — STOPPED: ${plan.stopped}` : '');
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
  // refresh everything after a terminal state (catalog file, approved, plan…)
  openRun(CURRENT.runId);
}

async function refreshStatus() {
  const status = await api(
    `api/runs/${encodeURIComponent(CURRENT.runId)}/submit/status?offset=0`
  ).catch(() => null);
  if (!status) return;
  LOG_OFFSET = status.offset;
  updateBusyBadge(status.busy);
  if (status.state === 'running') {
    $('#progress').classList.remove('hidden');
    $('#progress-title').textContent = `${status.kind} en cours (pid ${status.pid})`;
    $('#events').textContent = '';
    startPolling();
  } else if (status.state && status.state !== 'idle') {
    $('#progress').classList.remove('hidden');
    $('#progress-title').textContent =
      `dernier run : ${status.kind || '?'} — ${status.state} (exit ${status.exit_code})`;
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
}

// ---------------------------------------------------------------- init

async function init() {
  try {
    META = await api('api/meta');
  } catch (err) {
    showError(err);
    return;
  }
  $('#refresh-runs').addEventListener('click', loadRuns);
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
  await loadRuns();
}

init();
