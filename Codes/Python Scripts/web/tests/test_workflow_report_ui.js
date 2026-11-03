// ============================================================================
// TOACD Phase 1C: Plain-English Workflow Report & Narrative UI Test Suite
// ============================================================================

const assert = require('assert');

function matchesSelector(el, selector) {
  if (!el || !selector) return false;
  selector = selector.trim();
  if (selector.startsWith('#')) {
    return el.id === selector.slice(1);
  }
  if (selector.startsWith('.')) {
    const cls = selector.slice(1).replace(/\\/g, '');
    return el.className && el.className.split(/\s+/).some(c => c === cls);
  }
  return el.tagName === selector.toUpperCase();
}

// 1. Simulated DOM environment for Node.js
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
    this._innerHTML = '';
    this.listeners = new Map();
    this.scrollTop = 0;
    this.scrollHeight = 100;
  }

  get innerHTML() {
    return this._innerHTML;
  }

  set innerHTML(val) {
    this._innerHTML = val;
    this.children = [];
    if (typeof val === 'string') {
      this._parseChildElements(val);
    }
  }

  _parseChildElements(html) {
    // Parse nested elements with class or id for querySelectorAll
    const tagRegex = /<([a-z0-9]+)([^>]*)>(.*?)<\/\1>/gis;
    let match;
    while ((match = tagRegex.exec(html)) !== null) {
      const tag = match[1];
      const attrsStr = match[2];
      const inner = match[3];

      const child = new FakeElement(tag);
      const idMatch = attrsStr.match(/id="([^"]+)"/);
      if (idMatch) child.id = idMatch[1];
      const classMatch = attrsStr.match(/class="([^"]+)"/);
      if (classMatch) {
        child.className = classMatch[1];
        classMatch[1].split(/\s+/).forEach(c => child.classList.add(c));
      }
      const dataSimple = attrsStr.match(/data-simple="([^"]+)"/);
      if (dataSimple) child.setAttribute('data-simple', dataSimple[1]);
      const dataTech = attrsStr.match(/data-technical="([^"]+)"/);
      if (dataTech) child.setAttribute('data-technical', dataTech[1]);
      const ariaExpanded = attrsStr.match(/aria-expanded="([^"]+)"/);
      if (ariaExpanded) child.setAttribute('aria-expanded', ariaExpanded[1]);
      const ariaPressed = attrsStr.match(/aria-pressed="([^"]+)"/);
      if (ariaPressed) child.setAttribute('aria-pressed', ariaPressed[1]);
      const ariaControls = attrsStr.match(/aria-controls="([^"]+)"/);
      if (ariaControls) child.setAttribute('aria-controls', ariaControls[1]);

      child.textContent = inner.replace(/<[^>]*>/g, '').trim();
      child._innerHTML = inner;

      this.appendChild(child);
    }
  }

  get previousElementSibling() {
    if (!this.parentNode) return null;
    const siblings = this.parentNode.children;
    const idx = siblings.indexOf(this);
    if (idx > 0) return siblings[idx - 1];
    return null;
  }

  addEventListener(evt, fn) {
    if (!this.listeners.has(evt)) this.listeners.set(evt, []);
    this.listeners.get(evt).push(fn);
  }

  click() {
    const fns = this.listeners.get('click') || [];
    fns.forEach(fn => fn({ preventDefault: () => {} }));
  }

  setAttribute(k, v) { this.attributes.set(k, String(v)); }
  getAttribute(k) { return this.attributes.get(k) || null; }
  hasAttribute(k) { return this.attributes.has(k); }
  removeAttribute(k) { this.attributes.delete(k); }

  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    if (child.id && global.document && global.document.elements) {
      global.document.elements.set(child.id, child);
    }
    return child;
  }

  querySelector(selector) {
    const matches = this.querySelectorAll(selector);
    return matches.length > 0 ? matches[0] : null;
  }

  querySelectorAll(selector) {
    if (selector.includes(',')) {
      const parts = selector.split(',').map(s => s.trim());
      const set = new Set();
      for (const p of parts) {
        for (const node of this.querySelectorAll(p)) {
          set.add(node);
        }
      }
      return Array.from(set);
    }

    const results = [];
    const search = (node) => {
      for (const child of node.children) {
        if (matchesSelector(child, selector)) {
          results.push(child);
        }
        search(child);
      }
    };
    search(this);
    return results;
  }
}

class FakeDocument {
  constructor() {
    this.elements = new Map();
  }

  addEventListener(type, fn) {}

  getElementById(id) {
    if (!this.elements.has(id)) {
      const el = new FakeElement('div');
      el.id = id;
      this.elements.set(id, el);
    }
    return this.elements.get(id);
  }

  createElement(tag) {
    return new FakeElement(tag);
  }

  registerElement(id, el) {
    el.id = id;
    this.elements.set(id, el);
    return el;
  }

  querySelectorAll(selector) {
    if (selector.startsWith('#agent-messages-container ')) {
      const c = this.getElementById('agent-messages-container');
      const sub = selector.replace('#agent-messages-container ', '');
      return c.querySelectorAll(sub);
    }
    if (selector.startsWith('#workflow-narrative-steps ')) {
      const c = this.getElementById('workflow-narrative-steps');
      const sub = selector.replace('#workflow-narrative-steps ', '');
      return c.querySelectorAll(sub);
    }

    const results = [];
    for (const el of this.elements.values()) {
      if (matchesSelector(el, selector)) {
        if (!results.includes(el)) results.push(el);
      }
      for (const child of el.querySelectorAll(selector)) {
        if (!results.includes(child)) results.push(child);
      }
    }
    return results;
  }
}

// Mock sessionStorage
const mockStorage = new Map();
global.sessionStorage = {
  getItem: (k) => (mockStorage.has(k) ? mockStorage.get(k) : null),
  setItem: (k, v) => mockStorage.set(k, String(v)),
  removeItem: (k) => mockStorage.delete(k),
  clear: () => mockStorage.clear(),
};

// 2. Set up document fixture matching index.html
function setupTestDocument() {
  const doc = new FakeDocument();

  // Create report DOM hierarchy
  const placeholder = doc.getElementById('workflow-report-placeholder');
  const card = doc.getElementById('workflow-report-card');
  card.classList.add('hidden');

  // Register dimension elements with icon children
  ['report-dim-execution', 'report-dim-compilation', 'report-dim-security', 'report-dim-correctness', 'report-dim-speedup'].forEach(dimId => {
    const dimEl = doc.getElementById(dimId);
    const icon = doc.createElement('span');
    icon.className = 'material-symbols-outlined';
    icon.textContent = 'check';
    dimEl.appendChild(icon);
  });

  // Toggle buttons
  const btnSimple = doc.getElementById('toggle-view-simple');
  btnSimple.setAttribute('aria-pressed', 'true');
  const btnTech = doc.getElementById('toggle-view-technical');
  btnTech.setAttribute('aria-pressed', 'false');

  // Agent message container
  doc.getElementById('agent-messages-container');
  doc.getElementById('msg-counter');

  // Narrative steps container
  doc.getElementById('workflow-narrative-steps');
  doc.getElementById('narrative-progress-badge');

  return doc;
}

const fakeDoc = setupTestDocument();
global.document = fakeDoc;

const {
  renderWorkflowReport,
  resetWorkflowReport,
  escapeHtml,
  explainAgentMessage,
  appendAgentMessageCard,
  renderWorkflowNarrative,
  resetWorkflowNarrative,
  setViewMode,
  setupViewModeToggle,
  getCurrentViewMode,
  toggleMessageDrawer,
  toggleNarrativeDetails,
} = require('../static/app.js');

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

console.log("=== TOACD Phase 1C: Plain-English Workflow Report UI Verification Suite ===");

// Test 1: Reset hides report card and shows placeholder
runTest("resetWorkflowReport hides report card and shows placeholder", () => {
  const placeholder = fakeDoc.getElementById('workflow-report-placeholder');
  const card = fakeDoc.getElementById('workflow-report-card');
  placeholder.classList.add('hidden');
  card.classList.remove('hidden');

  resetWorkflowReport();
  assert.ok(!placeholder.classList.contains('hidden'));
  assert.ok(card.classList.contains('hidden'));
});

// Test 2: renderWorkflowReport with null resets report
runTest("renderWorkflowReport(null) calls reset", () => {
  const card = fakeDoc.getElementById('workflow-report-card');
  card.classList.remove('hidden');

  renderWorkflowReport(null);
  assert.ok(card.classList.contains('hidden'));
});

// Test 3: renderWorkflowReport populates Header & Run Summary (Section A)
runTest("renderWorkflowReport populates Header and Section A", () => {
  const mockReport = {
    run_id: "test_run_123",
    mode: "ai",
    status: "completed",
    summary: {
      headline: "AI Optimization Workflow Completed",
      mode_label: "AI-Optimized Multi-Agent Run",
      execution_outcome: "Completed successfully",
      is_conclusive: true,
      conclusive_reason: "Benchmark measurements are statistically stable and conclusive.",
      plain_text: "System executed multi-agent deliberation and optimization.",
    },
    overall_conclusion: {
      verdict_badge: "SPEEDUP_VERIFIED",
    },
  };

  renderWorkflowReport(mockReport);

  const card = fakeDoc.getElementById('workflow-report-card');
  assert.ok(!card.classList.contains('hidden'));

  assert.strictEqual(fakeDoc.getElementById('report-run-id').textContent, "test_run_123");
  assert.strictEqual(fakeDoc.getElementById('report-mode-badge').textContent, "AI-Optimized Multi-Agent Run");
  assert.strictEqual(fakeDoc.getElementById('report-verdict-badge').textContent, "SPEEDUP_VERIFIED");
  assert.strictEqual(fakeDoc.getElementById('report-summary-headline').textContent, "AI Optimization Workflow Completed");
  assert.strictEqual(fakeDoc.getElementById('report-summary-text').textContent, "System executed multi-agent deliberation and optimization.");
  assert.strictEqual(fakeDoc.getElementById('report-conclusive-badge').textContent, "Conclusive");
});

// Test 4: Section B Program Analysis
runTest("renderWorkflowReport populates Section B Program Analysis", () => {
  const mockReport = {
    run_id: "test_prof",
    mode: "ai",
    program_analysis: {
      profile_label: "loop_oriented",
      profile_explanation: "Program is dominated by loops.",
      instructions: 150,
      loops: 4,
      memory_instructions: 45,
      dominant_feature: "loops",
      static_vs_runtime_note: "Static IR measurements.",
    },
  };

  renderWorkflowReport(mockReport);
  assert.strictEqual(fakeDoc.getElementById('report-profile-label').textContent, "loop_oriented");
  assert.strictEqual(fakeDoc.getElementById('report-profile-insts').textContent, 150);
  assert.strictEqual(fakeDoc.getElementById('report-profile-loops').textContent, 4);
  assert.strictEqual(fakeDoc.getElementById('report-profile-mem').textContent, 45);
  assert.strictEqual(fakeDoc.getElementById('report-profile-dominant').textContent, "loops");
});

// Test 5: Section C Optimization Strategy & Fallback Alert
runTest("renderWorkflowReport populates Section C Strategy and Fallback Alert", () => {
  const mockReport = {
    run_id: "test_strat",
    mode: "ai",
    optimization_strategy: {
      selected_strategy: "unsafe_candidate",
      effective_strategy: "-O2",
      fallback_occurred: true,
      fallback_reason: "Security constraints required safe baseline.",
      applied_transformations: "Standard -O2 pipeline.",
      decision_rationale: "Selected for loop optimization.",
    },
  };

  renderWorkflowReport(mockReport);
  assert.strictEqual(fakeDoc.getElementById('report-strategy-selected').textContent, "unsafe_candidate");
  assert.strictEqual(fakeDoc.getElementById('report-strategy-effective').textContent, "-O2");

  const fbAlert = fakeDoc.getElementById('report-fallback-alert');
  assert.ok(!fbAlert.classList.contains('hidden'));
  assert.strictEqual(fakeDoc.getElementById('report-fallback-reason').textContent, "Security constraints required safe baseline.");
});

// Test 6: Section D Security and Correctness
runTest("renderWorkflowReport populates Section D Security and Correctness", () => {
  const mockReport = {
    run_id: "test_sec_corr",
    mode: "ai",
    security_and_correctness: {
      security_status: "Passed",
      security_details: "AST checks satisfied.",
      compilation_status: "Passed",
      compilation_details: "LLVM exit 0.",
      correctness_status: "Passed",
      correctness_details: "Numerical output matched.",
      fallback_handling: "None",
    },
  };

  renderWorkflowReport(mockReport);
  assert.strictEqual(fakeDoc.getElementById('report-sec-badge').textContent, "Passed");
  assert.strictEqual(fakeDoc.getElementById('report-comp-badge').textContent, "Passed");
  assert.strictEqual(fakeDoc.getElementById('report-corr-badge').textContent, "Passed");
  assert.strictEqual(fakeDoc.getElementById('report-fb-badge').textContent, "None");
});

// Test 7: Section E Performance Results & Inconclusive Badge
runTest("renderWorkflowReport populates Section E Performance Results", () => {
  const mockReport = {
    run_id: "test_perf",
    mode: "ai",
    performance: {
      baseline_time_ms: 20.5,
      optimized_time_ms: 16.4,
      code_size_bytes: 1400,
      benchmark_verdict: "IMPROVED",
      speedup_text: "+25.0% speedup (1.25x faster than baseline)",
      verdict_explanation: "Confirmed performance gain.",
      reliability_explanation: "Low variance across samples.",
    },
  };

  renderWorkflowReport(mockReport);
  assert.strictEqual(fakeDoc.getElementById('report-perf-baseline').textContent, "20.5 ms");
  assert.strictEqual(fakeDoc.getElementById('report-perf-optimized').textContent, "16.4 ms");
  assert.strictEqual(fakeDoc.getElementById('report-perf-size').textContent, "1400 B");
  assert.strictEqual(fakeDoc.getElementById('report-perf-verdict').textContent, "IMPROVED");
  assert.strictEqual(fakeDoc.getElementById('report-perf-speedup').textContent, "+25.0% speedup (1.25x faster than baseline)");
});

// Test 8: Section G Overall Conclusion & 5-Dimension Checkmarks
runTest("renderWorkflowReport populates Section G Overall Conclusion and 5 Dimensions", () => {
  const mockReport = {
    run_id: "test_conc",
    mode: "ai",
    overall_conclusion: {
      headline: "Optimization Successful",
      text: "All verification and performance criteria met.",
      verdict_badge: "SPEEDUP_VERIFIED",
      execution_succeeded: true,
      compilation_succeeded: true,
      security_passed: true,
      correctness_verified: true,
      performance_improved: true,
    },
  };

  renderWorkflowReport(mockReport);
  assert.strictEqual(fakeDoc.getElementById('report-conclusion-headline').textContent, "Optimization Successful");
  assert.strictEqual(fakeDoc.getElementById('report-conclusion-badge').textContent, "SPEEDUP_VERIFIED");

  // Check dimension styling
  const dimSpeedup = fakeDoc.getElementById('report-dim-speedup');
  assert.ok(dimSpeedup.className.includes('text-emerald-400'));
});

// Test 9: Safe escaping of untrusted strings in escapeHtml
runTest("escapeHtml safely sanitizes potentially dangerous HTML content", () => {
  const unsafe = '<script>alert("xss")</script> & " \'';
  const safe = escapeHtml(unsafe);
  assert.ok(!safe.includes('<script>'));
  assert.ok(safe.includes('&lt;script&gt;'));
  assert.ok(safe.includes('&quot;'));
  assert.ok(safe.includes('&#39;'));
  assert.ok(safe.includes('&amp;'));
});

// Test 10: Provisional IN_PROGRESS badge rendering
runTest("renderWorkflowReport styles provisional IN_PROGRESS badge correctly", () => {
  const mockReport = {
    run_id: "test_running_ui",
    mode: "ai",
    is_provisional: true,
    summary: { headline: "Workflow In Progress (Provisional)" },
    overall_conclusion: {
      headline: "Workflow In Progress",
      verdict_badge: "IN_PROGRESS",
    },
  };
  renderWorkflowReport(mockReport);
  const badge = fakeDoc.getElementById('report-verdict-badge');
  assert.strictEqual(badge.textContent, "IN_PROGRESS");
  assert.ok(badge.className.includes("animate-pulse"));
  assert.ok(badge.className.includes("text-sky-400"));
});

// Test 11: Cross-run ID mismatch guard rejects mismatched report
runTest("renderWorkflowReport rejects reports with mismatching active run_id", () => {
  // Set fakeDoc elements to known text
  const runIdEl = fakeDoc.getElementById('report-run-id');
  runIdEl.textContent = "original_run_id";

  const appModule = require('../static/app.js');
  if (appModule.setActiveRunId) appModule.setActiveRunId("active_run_999");
  global.activeRunId = "active_run_999";
  const staleReport = {
    run_id: "stale_run_001",
    mode: "ai",
    summary: { headline: "Stale Report" },
  };

  renderWorkflowReport(staleReport);
  // DOM element should NOT have been updated to stale_run_001
  assert.strictEqual(runIdEl.textContent, "original_run_id");
  if (appModule.setActiveRunId) appModule.setActiveRunId(null);
  global.activeRunId = null;
});

// Test 12: renderWorkflowNarrative populates all 7 steps and updates progress badge
runTest("renderWorkflowNarrative populates all 7 chronological steps and progress badge", () => {
  const mockNarrative = {
    steps: [
      { step_number: 1, title: "Program Analysis", status: "completed", badge: "PROFILED", simple_explanation: "Analyzed IR.", technical_explanation: "Extracted IR metrics.", evidence: ["Instructions: 120"], technical_details: { instructions: 120 } },
      { step_number: 2, title: "Strategy Selection", status: "completed", badge: "SELECTED", simple_explanation: "Selected -O3.", technical_explanation: "Pass sequence -O3.", evidence: ["Flag: -O3"], technical_details: { strategy: "-O3" } },
      { step_number: 3, title: "Agent Review", status: "completed", badge: "APPROVED", simple_explanation: "Reviewer approved.", technical_explanation: "0 alerts.", evidence: ["Approved"], technical_details: {} },
      { step_number: 4, title: "Security Verification", status: "completed", badge: "PASSED", simple_explanation: "Safety verified.", technical_explanation: "Security gate PASS.", evidence: ["Verdict: PASS"], technical_details: { verdict: "PASS" } },
      { step_number: 5, title: "Compilation & Correctness", status: "completed", badge: "VERIFIED", simple_explanation: "Clean compile and run.", technical_explanation: "Exit code 0.", evidence: ["Exit code 0"], technical_details: {} },
      { step_number: 6, title: "Benchmarking", status: "completed", badge: "SPEEDUP_VERIFIED", simple_explanation: "Recorded 20 ms vs 30 ms.", technical_explanation: "Speedup +50%.", evidence: ["20 ms vs 30 ms"], technical_details: { base_ms: 30, opt_ms: 20 } },
      { step_number: 7, title: "Final Outcome", status: "completed", badge: "SPEEDUP_VERIFIED", simple_explanation: "Workflow succeeded.", technical_explanation: "IMPROVED verdict.", evidence: ["Outcome: verified"], technical_details: {} },
    ],
  };

  renderWorkflowNarrative(mockNarrative);

  const badge = fakeDoc.getElementById('narrative-progress-badge');
  assert.strictEqual(badge.textContent, "7 / 7 STAGES COMPLETED");

  const container = fakeDoc.getElementById('workflow-narrative-steps');
  assert.ok(container.innerHTML.includes("Program Analysis"));
  assert.ok(container.innerHTML.includes("Strategy Selection"));
  assert.ok(container.innerHTML.includes("Agent Review"));
  assert.ok(container.innerHTML.includes("Security Verification"));
  assert.ok(container.innerHTML.includes("Compilation &amp; Correctness"));
  assert.ok(container.innerHTML.includes("Benchmarking"));
  assert.ok(container.innerHTML.includes("Final Outcome"));
  assert.ok(container.innerHTML.includes("Supporting Evidence"));
});

// Test 13: resetWorkflowNarrative clears narrative steps container and resets badge
runTest("resetWorkflowNarrative clears container and sets standby badge", () => {
  resetWorkflowNarrative();
  const badge = fakeDoc.getElementById('narrative-progress-badge');
  assert.strictEqual(badge.textContent, "STANDBY");
  const container = fakeDoc.getElementById('workflow-narrative-steps');
  assert.ok(container.innerHTML.includes("Awaiting execution"));
});

// Test 14: explainAgentMessage generates deterministic categories and explanations
runTest("explainAgentMessage produces structured category and dual explanations", () => {
  const msgIr = {
    sender: "CodeAnalyst",
    message_type: "IR_FEATURES",
    payload: { ir_features: { total_instructions: 350, vectorizable_loops: 2, load_instructions: 50, store_instructions: 20 } },
  };
  const expIr = explainAgentMessage(msgIr);
  assert.strictEqual(expIr.category, "observation");
  assert.ok(expIr.simple_text.includes("counted 350 instructions"));
  assert.ok(expIr.technical_summary.includes("IR features extracted: 350"));

  const msgReview = {
    sender: "OptimizationReviewer",
    message_type: "REVIEW_REJECT",
    payload: { strategy: "-O3", feedback: "Exceeds register pressure threshold", revision_number: 1 },
  };
  const expReview = explainAgentMessage(msgReview);
  assert.strictEqual(expReview.category, "review");
  assert.ok(expReview.simple_text.includes("rejected it due to diagnostic concerns"));
  assert.ok(expReview.technical_summary.includes("Reviewer REJECTED candidate"));

  const msgSec = {
    sender: "SecurityGate",
    message_type: "FINAL_DECISION",
    payload: { effective_strategy: "baseline", fallback_occurred: true },
  };
  const expSec = explainAgentMessage(msgSec);
  assert.strictEqual(expSec.category, "security");
  assert.ok(expSec.simple_text.includes("safely substituted verified baseline"));
});

// Test 15: appendAgentMessageCard appends card with category chip and payload drawer toggle
runTest("appendAgentMessageCard creates message card with category chip and drawer toggle", () => {
  const container = fakeDoc.getElementById('agent-messages-container');
  container.children = [];
  container.innerHTML = '';

  const msg = {
    sender: "OptimizationStrategist",
    recipient: "Reviewer",
    message_type: "STRATEGY_PROPOSAL",
    step: 2,
    timestamp: "2026-10-28T12:00:00Z",
    payload: { strategy: "-O3 -funroll-loops", passes: ["instcombine", "loop-unroll"] },
  };

  appendAgentMessageCard(msg);

  assert.ok(container.children.length > 0);
  const card = container.children[0];
  assert.ok(card.innerHTML.includes("STRATEGY_PROPOSAL"));
  assert.ok(card.innerHTML.includes("PROPOSAL")); // Category chip
  assert.ok(card.innerHTML.includes("Technical Payload"));
  assert.ok(card.innerHTML.includes("aria-controls"));
  assert.ok(card.innerHTML.includes("aria-expanded=\"false\""));
});

// Test 16: setViewMode('technical') switches DOM text and toggles button states
runTest("setViewMode('technical') updates buttons, agent cards, and narrative step cards", () => {
  setViewMode('technical');

  assert.strictEqual(getCurrentViewMode(), 'technical');
  const btnSimple = fakeDoc.getElementById('toggle-view-simple');
  const btnTech = fakeDoc.getElementById('toggle-view-technical');
  assert.strictEqual(btnSimple.getAttribute('aria-pressed'), 'false');
  assert.strictEqual(btnTech.getAttribute('aria-pressed'), 'true');
  assert.strictEqual(global.sessionStorage.getItem('toacd_view_mode'), 'technical');
});

// Test 17: setViewMode('simple') reverts to Simple English mode
runTest("setViewMode('simple') updates buttons and restores simple English mode", () => {
  setViewMode('simple');

  assert.strictEqual(getCurrentViewMode(), 'simple');
  const btnSimple = fakeDoc.getElementById('toggle-view-simple');
  const btnTech = fakeDoc.getElementById('toggle-view-technical');
  assert.strictEqual(btnSimple.getAttribute('aria-pressed'), 'true');
  assert.strictEqual(btnTech.getAttribute('aria-pressed'), 'false');
  assert.strictEqual(global.sessionStorage.getItem('toacd_view_mode'), 'simple');
});

// Test 18: setupViewModeToggle restores saved mode from sessionStorage
runTest("setupViewModeToggle loads persisted view mode from sessionStorage", () => {
  global.sessionStorage.setItem('toacd_view_mode', 'technical');
  setupViewModeToggle();
  assert.strictEqual(getCurrentViewMode(), 'technical');

  // Clean up
  setViewMode('simple');
});

// Test 19: toggleMessageDrawer toggles hidden class and aria-expanded
runTest("toggleMessageDrawer toggles hidden class and aria-expanded", () => {
  const cardId = "test-card-drawer";
  const btn = fakeDoc.createElement('button');
  btn.setAttribute('aria-expanded', 'false');
  const chev = fakeDoc.createElement('span');
  chev.className = 'toggle-chevron';
  btn.appendChild(chev);

  const drawer = fakeDoc.createElement('div');
  drawer.id = `${cardId}-payload`;
  drawer.classList.add('hidden');

  const wrapper = fakeDoc.createElement('div');
  wrapper.appendChild(btn);
  wrapper.appendChild(drawer);
  fakeDoc.registerElement(drawer.id, drawer);

  // Expand
  toggleMessageDrawer(cardId);
  assert.ok(!drawer.classList.contains('hidden'));
  assert.strictEqual(btn.getAttribute('aria-expanded'), 'true');

  // Collapse
  toggleMessageDrawer(cardId);
  assert.ok(drawer.classList.contains('hidden'));
  assert.strictEqual(btn.getAttribute('aria-expanded'), 'false');
});

// Test 20: toggleNarrativeDetails expands and collapses step technical details
runTest("toggleNarrativeDetails toggles details drawer and aria-expanded", () => {
  const detailsId = "test-narrative-details";
  const btn = fakeDoc.createElement('button');
  btn.setAttribute('aria-expanded', 'false');
  const chev = fakeDoc.createElement('span');
  chev.className = 'step-chevron';
  btn.appendChild(chev);

  const details = fakeDoc.createElement('div');
  details.id = detailsId;
  details.classList.add('hidden');
  fakeDoc.registerElement(detailsId, details);

  // Expand
  toggleNarrativeDetails(btn, detailsId);
  assert.ok(!details.classList.contains('hidden'));
  assert.strictEqual(btn.getAttribute('aria-expanded'), 'true');

  // Collapse
  toggleNarrativeDetails(btn, detailsId);
  assert.ok(details.classList.contains('hidden'));
  assert.strictEqual(btn.getAttribute('aria-expanded'), 'false');
});

// Test 21: Toggle view switching preserves data integrity and verdicts (Neutrality)
runTest("View mode switching does not alter underlying reports, run IDs, or verdicts", () => {
  const mockReport = {
    run_id: "test_neutrality_run",
    mode: "ai",
    status: "completed",
    summary: { headline: "Complete", is_conclusive: true },
    overall_conclusion: { verdict_badge: "SPEEDUP_VERIFIED", performance_improved: true },
    workflow_narrative: {
      steps: [
        { step_number: 1, title: "Step 1", status: "completed", badge: "COMPLETED", simple_explanation: "Simple 1", technical_explanation: "Tech 1", evidence: [] }
      ]
    }
  };

  renderWorkflowReport(mockReport);
  const runIdBefore = fakeDoc.getElementById('report-run-id').textContent;
  const verdictBefore = fakeDoc.getElementById('report-verdict-badge').textContent;

  setViewMode('technical');
  assert.strictEqual(fakeDoc.getElementById('report-run-id').textContent, runIdBefore);
  assert.strictEqual(fakeDoc.getElementById('report-verdict-badge').textContent, verdictBefore);

  setViewMode('simple');
  assert.strictEqual(fakeDoc.getElementById('report-run-id').textContent, runIdBefore);
  assert.strictEqual(fakeDoc.getElementById('report-verdict-badge').textContent, verdictBefore);
});

console.log(`\nResults: ${passed}/${total} tests passed.`);
if (passed !== total) {
  process.exit(1);
}
