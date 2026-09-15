'use strict';

/* Lot 2 (2026-09-15) — the admin page's candidate-contract block (src/admin/static/app.js,
   between the `// candidate-contract:begin` / `:end` markers) is a literal port of
   src/candidate_contract.py. This runner feeds it the SAME examples the Python tests use
   (tests/fixtures/candidate_contract_examples.json) and fails on any divergence.

   Run:  node tests/js/candidate_contract_check.js      (CI runs it; the VPS has no node —
   tests/test_candidate_contract.py guards the block's presence there.)
   Exit code 0 = every case agrees; 1 = divergence(s) listed; 2 = setup problem. */

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..', '..');
const APP_JS = path.join(ROOT, 'src', 'admin', 'static', 'app.js');
const FIXTURE = path.join(ROOT, 'tests', 'fixtures', 'candidate_contract_examples.json');

function fail(message) {
  console.error(`candidate_contract_check: ${message}`);
  process.exit(2);
}

const source = fs.readFileSync(APP_JS, 'utf8');
const begin = source.indexOf('// candidate-contract:begin');
const end = source.indexOf('// candidate-contract:end');
if (begin < 0 || end < 0 || end < begin) fail('markers not found in app.js');
const block = source.slice(begin, end);

// Evaluate the block alone (app.js's top level touches the DOM) — its function
// declarations become properties of the fresh context.
const context = vm.createContext({});
try {
  vm.runInContext(block, context, { filename: 'app.js#candidate-contract' });
} catch (err) {
  fail(`the block does not evaluate: ${err.message}`);
}
for (const name of ['fp', 'normalizeTargets', 'primaryTarget', 'flattenTarget']) {
  if (typeof context[name] !== 'function') fail(`${name}() missing from the block`);
}

const cases = JSON.parse(fs.readFileSync(FIXTURE, 'utf8'));
if (!Array.isArray(cases) || cases.length === 0) fail('fixture is empty');

// Key-order-insensitive deep equality via canonical JSON (Python dict vs JS object order
// is not part of the contract; VALUES are).
function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value !== null && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((k) => `${JSON.stringify(k)}:${canonical(value[k])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}

const failures = [];
function check(name, label, run, expect) {
  // expect: {error: substring} | {value: any}
  let result;
  let error = null;
  try {
    result = run();
  } catch (err) {
    error = err;
  }
  if (expect.error !== undefined) {
    if (error === null) {
      failures.push(`${name} / ${label}: expected an error containing ${JSON.stringify(expect.error)}, got ${JSON.stringify(result)}`);
    } else if (!String(error.message).includes(expect.error)) {
      failures.push(`${name} / ${label}: error ${JSON.stringify(error.message)} does not contain ${JSON.stringify(expect.error)}`);
    }
    return;
  }
  if (error !== null) {
    failures.push(`${name} / ${label}: unexpected error ${JSON.stringify(error.message)}`);
    return;
  }
  if (canonical(result) !== canonical(expect.value)) {
    failures.push(`${name} / ${label}: got ${canonical(result)} expected ${canonical(expect.value)}`);
  }
}

for (const testCase of cases) {
  const name = testCase.name;
  const snapshot = canonical(testCase.candidate);
  const candidate = JSON.parse(JSON.stringify(testCase.candidate));

  if ('expect_error' in testCase) {
    check(name, 'fp', () => context.fp(candidate), { error: testCase.expect_error });
  } else {
    check(name, 'fp', () => context.fp(candidate), { value: testCase.expected_fingerprint });
  }
  if ('expect_targets_error' in testCase) {
    check(name, 'normalizeTargets', () => context.normalizeTargets(candidate), { error: testCase.expect_targets_error });
  } else {
    check(name, 'normalizeTargets', () => context.normalizeTargets(candidate), { value: testCase.expected_targets });
  }
  if (canonical(candidate) !== snapshot) failures.push(`${name}: the block mutated its input`);
}

if (failures.length > 0) {
  console.error(`candidate_contract_check: ${failures.length} divergence(s) between app.js and the Python contract:`);
  for (const line of failures) console.error(`  - ${line}`);
  process.exit(1);
}
console.log(`candidate_contract_check: ${cases.length} cases, app.js mirror agrees with src/candidate_contract.py`);
