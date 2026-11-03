// ============================================================================
// TOACD Phase 1B: Live Workflow Progress Automated Test Suite
// ============================================================================

const assert = require('assert');

// 1. Minimal Simulated DOM environment for Node.js
class FakeElement {
  constructor(tag = 'div') {
    this.tagName = tag.toUpperCase();
    this.id = '';
    this.className = '';
    this.classList = {
      _classes: new Set(),
      add: (c) => this.classList._classes.add(c),
      remove: (c) => this.classList._classes.delete(c),
      contains: (c) => this.classList._classes.has(c),
    };
    this.attributes = new Map();
    this.children = [];
    this.parentNode = null;
    this.textContent = '';
  }

  setAttribute(k, v) { this.attributes.set(k, String(v)); }
  getAttribute(k) { return this.attributes.get(k) || null; }
  hasAttribute(k) { return this.attributes.has(k); }
  removeAttribute(k) { this.attributes.delete(k); }

  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  querySelector(selector) {
    if (selector === '.step-badge') {
      return this.children.find(c => c.className && c.className.includes('step-badge')) || null;
    }
    if (selector === 'span:first-child') {
      return this.children.find(c => c.tagName === 'SPAN') || null;
    }
    return null;
  }
}

class FakeDocument {
  constructor() {
    this.elements = new Map();
  }

  addEventListener(type, fn) {}

  getElementById(id) {
    return this.elements.get(id) || null;
  }

  createElement(tag) {
    return new FakeElement(tag);
  }

  registerElement(id, el) {
    el.id = id;
    this.elements.set(id, el);
    return el;
  }
}

// 2. Set up document fixture matching index.html
function setupTestDocument() {
  const doc = new FakeDocument();

  const stages = [
    { id: "step-profiling", title: "1. Program Profile" },
    { id: "step-strategy", title: "2. AI Strategy" },
    { id: "step-reviewer", title: "3. Reviewer Gate" },
    { id: "step-security", title: "4. Security Gate" },
    { id: "step-benchmark", title: "5. Benchmark" },
    { id: "step-regression", title: "6. Regression Audit" },
  ];

  stages.forEach(s => {
    const stageEl = new FakeElement('div');
    stageEl.className = "flex items-center justify-between p-1.5 rounded bg-navy-50 border border-navy-200/60";
    stageEl.setAttribute('data-status', 'pending');
    stageEl.setAttribute('role', 'listitem');
    stageEl.setAttribute('aria-label', `${s.title}: Pending`);

    const titleSpan = new FakeElement('span');
    titleSpan.className = "text-[11px] text-navy-700 font-medium truncate";
    titleSpan.textContent = s.title;
    stageEl.appendChild(titleSpan);

    const badgeSpan = new FakeElement('span');
    badgeSpan.className = "step-badge font-mono text-[9.5px] text-navy-400";
    badgeSpan.textContent = "Pending";
    stageEl.appendChild(badgeSpan);

    doc.registerElement(s.id, stageEl);
  });

  const statusLabel = new FakeElement('span');
  statusLabel.textContent = "Standby";
  doc.registerElement('multiagent-status-label', statusLabel);

  return doc;
}

// Set up global environment for app.js imports
const fakeDoc = setupTestDocument();
global.document = fakeDoc;

// Load app.js module exports
const { handleStageTransition, resetChecklistSteps } = require('../static/app.js');

// 3. Test Cases
let passed = 0;
let total = 0;

function runTest(name, fn) {
  total++;
  try {
    fn();
    console.log(`[PASS] Test ${total}: ${name}`);
    passed++;
  } catch (err) {
    console.error(`[FAIL] Test ${total}: ${name}`);
    console.error(err);
  }
}

console.log("=== TOACD Phase 1B: Live Workflow Progress Verification Suite ===");

// Test 1: Initial state & resetChecklistSteps
runTest("Initial State & resetChecklistSteps resets all stages to Pending", () => {
  resetChecklistSteps();
  const stages = [
    "step-profiling", "step-strategy", "step-reviewer",
    "step-security", "step-benchmark", "step-regression"
  ];
  stages.forEach(id => {
    const el = fakeDoc.getElementById(id);
    assert.strictEqual(el.getAttribute('data-status'), 'pending', `${id} should be pending`);
    const badge = el.querySelector('.step-badge');
    assert.strictEqual(badge.textContent, 'Pending', `${id} badge should be Pending`);
    assert.ok(badge.className.includes('text-navy-400'), `${id} badge should have muted navy text`);
  });
});

// Test 2: Started transition moves stage to Running and updates progress header
runTest("Started transition moves stage to Running with honest stage count", () => {
  handleStageTransition({
    stage: 'profiling',
    status: 'started',
    payload: { source_path: 'input.c' }
  });

  const el = fakeDoc.getElementById('step-profiling');
  assert.strictEqual(el.getAttribute('data-status'), 'running');
  const badge = el.querySelector('.step-badge');
  assert.strictEqual(badge.textContent, 'Running');
  assert.ok(badge.className.includes('animate-pulse'));
  assert.ok(el.className.includes('bg-blue-50'));

  const statusLabel = fakeDoc.getElementById('multiagent-status-label');
  assert.strictEqual(statusLabel.textContent, 'Stage 1/6 · Profiling');
});

// Test 3: Completed transition sets emerald styling and descriptive badge
runTest("Completed transition sets emerald styling and descriptive badge", () => {
  handleStageTransition({
    stage: 'profiling',
    status: 'completed',
    payload: { features: { total_instructions: 42 } }
  });

  const el = fakeDoc.getElementById('step-profiling');
  assert.strictEqual(el.getAttribute('data-status'), 'completed');
  const badge = el.querySelector('.step-badge');
  assert.strictEqual(badge.textContent, 'Completed');
  assert.ok(badge.className.includes('text-emerald-700'));
  assert.ok(el.className.includes('bg-emerald-50'));
});

// Test 4: Strategy selection completed displays selected strategy name
runTest("Strategy selection completed displays selected strategy name", () => {
  handleStageTransition({
    stage: 'strategy_selection',
    status: 'started'
  });
  const statusLabel = fakeDoc.getElementById('multiagent-status-label');
  assert.strictEqual(statusLabel.textContent, 'Stage 2/6 · Strategy Selection');

  handleStageTransition({
    stage: 'strategy_selection',
    status: 'completed',
    payload: { strategy: '-O2' }
  });

  const el = fakeDoc.getElementById('step-strategy');
  assert.strictEqual(el.getAttribute('data-status'), 'completed');
  const badge = el.querySelector('.step-badge');
  assert.strictEqual(badge.textContent, 'Strategy: -O2');
  assert.ok(badge.className.includes('text-emerald-700'));
});

// Test 5: Agent review completed displays revisions count if revised
runTest("Agent review completed displays revisions count if revised", () => {
  handleStageTransition({
    stage: 'agent_review',
    status: 'started'
  });
  handleStageTransition({
    stage: 'agent_review',
    status: 'completed',
    payload: { strategy: '-O2', revisions: 2 }
  });

  const el = fakeDoc.getElementById('step-reviewer');
  assert.strictEqual(el.getAttribute('data-status'), 'completed');
  const badge = el.querySelector('.step-badge');
  assert.strictEqual(badge.textContent, 'Review: Approved (2 rev)');
});

// Test 6: Security Gate verification with Fallback
runTest("Security Gate verification with Fallback displays Fallback badge", () => {
  handleStageTransition({
    stage: 'security_verification',
    status: 'started'
  });
  handleStageTransition({
    stage: 'security_verification',
    status: 'completed',
    payload: {
      fallback_occurred: true,
      effective_strategy: '-O2',
      verdict: 'PASS'
    }
  });

  const el = fakeDoc.getElementById('step-security');
  assert.strictEqual(el.getAttribute('data-status'), 'completed');
  const badge = el.querySelector('.step-badge');
  assert.strictEqual(badge.textContent, 'Fallback: -O2');
});

// Test 7: Security Gate explicitly BLOCKED without fallback
runTest("Security Gate explicitly BLOCKED displays Blocked status", () => {
  handleStageTransition({
    stage: 'security_verification',
    status: 'blocked',
    payload: {
      verdict: 'BLOCKED',
      fallback_occurred: false
    }
  });

  const el = fakeDoc.getElementById('step-security');
  assert.strictEqual(el.getAttribute('data-status'), 'blocked');
  const badge = el.querySelector('.step-badge');
  assert.strictEqual(badge.textContent, 'Blocked');
  assert.ok(badge.className.includes('text-amber-700'));
  assert.ok(el.className.includes('bg-amber-50'));
});

// Test 8: Skipped stage displays Skipped badge with muted styling
runTest("Skipped stage displays Skipped badge with muted styling", () => {
  handleStageTransition({
    stage: 'strategy_selection',
    status: 'skipped',
    payload: { reason: 'Baseline mode uses fixed -O3' }
  });

  const el = fakeDoc.getElementById('step-strategy');
  assert.strictEqual(el.getAttribute('data-status'), 'skipped');
  const badge = el.querySelector('.step-badge');
  assert.strictEqual(badge.textContent, 'Skipped');
  assert.ok(badge.className.includes('text-navy-400'));
  assert.ok(el.className.includes('opacity-70'));
});

// Test 9: Failed stage displays Failed badge with rose styling
runTest("Failed stage displays Failed badge with rose styling", () => {
  handleStageTransition({
    stage: 'benchmarking',
    status: 'failed',
    payload: { error: 'Execution timeout exceeded' }
  });

  const el = fakeDoc.getElementById('step-benchmark');
  assert.strictEqual(el.getAttribute('data-status'), 'failed');
  const badge = el.querySelector('.step-badge');
  assert.ok(badge.textContent.includes('Failed'));
  assert.ok(badge.className.includes('text-rose-700'));
  assert.ok(el.className.includes('bg-rose-50'));
});

// Test 10: High variance / unreliable timing benchmarking produces Inconclusive
runTest("Unreliable timing benchmark produces Inconclusive semantic state", () => {
  handleStageTransition({
    stage: 'benchmarking',
    status: 'completed',
    payload: {
      strategy: '-O3',
      timing_is_reliable: false,
      timing: { median_s: 0.0001, timing_is_reliable: false }
    }
  });

  const el = fakeDoc.getElementById('step-benchmark');
  assert.strictEqual(el.getAttribute('data-status'), 'inconclusive');
  const badge = el.querySelector('.step-badge');
  assert.strictEqual(badge.textContent, 'Inconclusive');
  assert.ok(badge.className.includes('text-amber-800'));
  assert.ok(el.className.includes('bg-amber-50'));
});

// Test 11: Inconclusive regression comparison produces Inconclusive state
runTest("Inconclusive regression comparison produces Inconclusive state", () => {
  handleStageTransition({
    stage: 'regression_analysis',
    status: 'completed',
    payload: {
      overall_status: 'INCONCLUSIVE'
    }
  });

  const el = fakeDoc.getElementById('step-regression');
  assert.strictEqual(el.getAttribute('data-status'), 'inconclusive');
  const badge = el.querySelector('.step-badge');
  assert.strictEqual(badge.textContent, 'Inconclusive');
});

// Test 12: Baseline normal execution workflow path
runTest("Baseline normal execution path: profiling -> skipped 2,3,4 -> benchmark -> skipped 6", () => {
  resetChecklistSteps();

  // 1. Profiling
  handleStageTransition({ stage: 'profiling', status: 'started' });
  handleStageTransition({ stage: 'profiling', status: 'completed' });
  assert.strictEqual(fakeDoc.getElementById('step-profiling').getAttribute('data-status'), 'completed');

  // 2, 3, 4 Skipped
  handleStageTransition({ stage: 'strategy_selection', status: 'skipped' });
  handleStageTransition({ stage: 'agent_review', status: 'skipped' });
  handleStageTransition({ stage: 'security_verification', status: 'skipped' });
  assert.strictEqual(fakeDoc.getElementById('step-strategy').getAttribute('data-status'), 'skipped');
  assert.strictEqual(fakeDoc.getElementById('step-reviewer').getAttribute('data-status'), 'skipped');
  assert.strictEqual(fakeDoc.getElementById('step-security').getAttribute('data-status'), 'skipped');

  // 5. Benchmark
  handleStageTransition({ stage: 'benchmarking', status: 'started' });
  handleStageTransition({ stage: 'benchmarking', status: 'completed', payload: { timing_is_reliable: true } });
  assert.strictEqual(fakeDoc.getElementById('step-benchmark').getAttribute('data-status'), 'completed');

  // 6. Regression Skipped
  handleStageTransition({ stage: 'regression_analysis', status: 'skipped' });
  assert.strictEqual(fakeDoc.getElementById('step-regression').getAttribute('data-status'), 'skipped');
});

// Test 13: Full AI execution workflow path
runTest("Full AI optimization workflow path: all 6 stages complete successfully", () => {
  resetChecklistSteps();

  handleStageTransition({ stage: 'profiling', status: 'started' });
  handleStageTransition({ stage: 'profiling', status: 'completed' });

  handleStageTransition({ stage: 'strategy_selection', status: 'started' });
  handleStageTransition({ stage: 'strategy_selection', status: 'completed', payload: { strategy: '-O2' } });

  handleStageTransition({ stage: 'agent_review', status: 'started' });
  handleStageTransition({ stage: 'agent_review', status: 'completed', payload: { strategy: '-O2' } });

  handleStageTransition({ stage: 'security_verification', status: 'started' });
  handleStageTransition({ stage: 'security_verification', status: 'completed', payload: { verdict: 'PASS' } });

  handleStageTransition({ stage: 'benchmarking', status: 'started' });
  handleStageTransition({ stage: 'benchmarking', status: 'completed', payload: { timing_is_reliable: true } });

  handleStageTransition({ stage: 'regression_analysis', status: 'started' });
  handleStageTransition({ stage: 'regression_analysis', status: 'completed', payload: { overall_status: 'IMPROVED' } });

  const allStages = [
    "step-profiling", "step-strategy", "step-reviewer",
    "step-security", "step-benchmark", "step-regression"
  ];
  allStages.forEach(id => {
    assert.strictEqual(fakeDoc.getElementById(id).getAttribute('data-status'), 'completed', `${id} should be completed`);
  });
  assert.strictEqual(fakeDoc.getElementById('step-regression').querySelector('.step-badge').textContent, 'Regression: IMPROVED');
});

// Test 14: Replay & Reconnection reconstructs exact workflow state deterministically
runTest("Replay & Reconnection reconstructs exact workflow state deterministically", () => {
  resetChecklistSteps();

  // Sequence of historical events from an AI run
  const historicalEvents = [
    { seq: 1, stage: 'profiling', status: 'started' },
    { seq: 2, stage: 'profiling', status: 'completed' },
    { seq: 3, stage: 'strategy_selection', status: 'started' },
    { seq: 4, stage: 'strategy_selection', status: 'completed', payload: { strategy: '-O3' } },
    { seq: 5, stage: 'agent_review', status: 'started' },
    { seq: 6, stage: 'agent_review', status: 'completed', payload: { strategy: '-O3' } },
    { seq: 7, stage: 'security_verification', status: 'started' },
    { seq: 8, stage: 'security_verification', status: 'completed', payload: { verdict: 'PASS' } },
    { seq: 9, stage: 'benchmarking', status: 'started' },
    { seq: 10, stage: 'benchmarking', status: 'completed', payload: { timing_is_reliable: true } },
    { seq: 11, stage: 'regression_analysis', status: 'started' },
    { seq: 12, stage: 'regression_analysis', status: 'completed', payload: { overall_status: 'PARITY' } },
  ];

  historicalEvents.forEach(evt => handleStageTransition(evt));

  assert.strictEqual(fakeDoc.getElementById('step-profiling').getAttribute('data-status'), 'completed');
  assert.strictEqual(fakeDoc.getElementById('step-strategy').querySelector('.step-badge').textContent, 'Strategy: -O3');
  assert.strictEqual(fakeDoc.getElementById('step-reviewer').querySelector('.step-badge').textContent, 'Review: Approved');
  assert.strictEqual(fakeDoc.getElementById('step-security').querySelector('.step-badge').textContent, 'Security: PASS');
  assert.strictEqual(fakeDoc.getElementById('step-benchmark').querySelector('.step-badge').textContent, 'Benchmarked');
  assert.strictEqual(fakeDoc.getElementById('step-regression').querySelector('.step-badge').textContent, 'Regression: PARITY');
});

console.log(`\nResults: ${passed}/${total} tests passed.`);
if (passed !== total) {
  process.exit(1);
}
