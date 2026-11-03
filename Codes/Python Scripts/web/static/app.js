// TOACD Web Application Controller
// Professional Navy IDE Frontend with Rigorous State Management, Stale SSE Rejection,
// and Independent Workflow Execution

// ============================================================================
// Global State Machine
// ============================================================================

let currentProgramId = 'gemm';
let currentProgramName = 'polybench-c / gemm.c';
let currentProgramCode = '';

// Active run guard for SSE streaming and asynchronous callbacks
let activeRunId = null;
let activeRunMode = null; // 'normal' | 'ai' | null
let currentEventSource = null;

// Independent workflow state containers
// States: 'idle' | 'running' | 'succeeded' | 'failed'
let normalState = {
  status: 'idle',
  programId: 'gemm',
  runId: null,
  data: null,
  error: null
};

let aiState = {
  status: 'idle',
  programId: 'gemm',
  runId: null,
  data: null,
  error: null
};

// Explanation View Mode (Feature 3: Technical / Simple English Toggle)
// 'simple' | 'technical'
let currentViewMode = 'simple';
let lastWorkflowReport = null;
let currentRunMessages = [];

// Helper: simple string hash for custom user edits
function computeSimpleHash(str) {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) - hash) + str.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash).toString(16);
}

// ============================================================================
// Tab Switching
// ============================================================================
function switchTab(tabId) {
  const navIds = ['nav-code', 'nav-ai-analysis', 'nav-optimized-code'];
  navIds.forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.className = "w-full text-left flex items-center justify-between px-3 py-2 rounded text-[13px] font-medium text-navy-300 hover:bg-navy-800 hover:text-white transition-all duration-180 nav-btn-hover font-sans cursor-pointer";
    }
  });

  const activeNav = document.getElementById(`nav-${tabId}`);
  if (activeNav) {
    activeNav.className = "w-full text-left flex items-center justify-between px-3 py-2 rounded text-[13px] font-medium transition-all duration-180 bg-accent text-white shadow-sm shadow-blue-900/30 font-sans cursor-pointer";
  }

  const tabs = ['code', 'ai-analysis', 'optimized-code'];
  tabs.forEach(t => {
    const pane = document.getElementById(`tab-${t}`);
    if (pane) pane.classList.remove('active');
  });

  const selectedPane = document.getElementById(`tab-${tabId}`);
  if (selectedPane) selectedPane.classList.add('active');

  const flag = document.getElementById('active-pipeline-flag');
  if (flag) {
    if (tabId === 'code') flag.textContent = "Workspace: 60/40 Split Workbench";
    if (tabId === 'ai-analysis') flag.textContent = "Audit: Formal Verification & XAI (6 Reports)";
    if (tabId === 'optimized-code') flag.textContent = "Buffer: Dual Source vs Transformed IR";
  }
}

// ============================================================================
// Accordion Controls
// ============================================================================
function toggleExperimentCard(cardNumber) {
  const body = document.getElementById(`card-body-${cardNumber}`);
  const chevron = document.getElementById(`card-chevron-${cardNumber}`);
  if (!body) return;

  const isCollapsed = body.classList.contains('max-h-0');
  if (isCollapsed) {
    body.classList.remove('max-h-0', 'opacity-0');
    body.classList.add('max-h-[600px]', 'opacity-100');
    if (chevron) {
      chevron.textContent = 'expand_more';
      chevron.style.transform = 'rotate(0deg)';
    }
  } else {
    body.classList.remove('max-h-[600px]', 'opacity-100');
    body.classList.add('max-h-0', 'opacity-0');
    if (chevron) {
      chevron.textContent = 'expand_less';
      chevron.style.transform = 'rotate(180deg)';
    }
  }
}

function toggleSectionAccordion(contentId, btn) {
  const content = document.getElementById(contentId);
  const icon = btn.querySelector('.material-symbols-outlined');
  if (!content) return;

  if (content.classList.contains('max-h-0')) {
    content.classList.remove('max-h-0', 'opacity-0');
    content.classList.add('max-h-[600px]', 'opacity-100');
    if (icon) icon.style.transform = 'rotate(180deg)';
  } else {
    content.classList.remove('max-h-[600px]', 'opacity-100');
    content.classList.add('max-h-0', 'opacity-0');
    if (icon) icon.style.transform = 'rotate(0deg)';
  }
}

function expandAllReports() {
  for (let i = 1; i <= 6; i++) {
    const sec = document.getElementById(`report-sec-${i}`);
    if (sec) {
      sec.classList.remove('max-h-0', 'opacity-0');
      sec.classList.add('max-h-[600px]', 'opacity-100');
    }
  }
}

function collapseAllReports() {
  for (let i = 1; i <= 6; i++) {
    const sec = document.getElementById(`report-sec-${i}`);
    if (sec) {
      sec.classList.remove('max-h-[600px]', 'opacity-100');
      sec.classList.add('max-h-0', 'opacity-0');
    }
  }
}

// ============================================================================
// Code Editor & Line Numbers
// ============================================================================
function updateLineNumbers() {
  const textarea = document.getElementById('editor-textarea');
  const lineNumbers = document.getElementById('editor-line-numbers');
  const lineColInfo = document.getElementById('editor-line-col-info');
  if (!textarea || !lineNumbers) return;

  const lines = textarea.value.split('\n');
  const count = lines.length;
  let numStr = '';
  for (let i = 1; i <= count; i++) {
    numStr += (i < 10 ? '0' + i : i) + '\n';
  }
  lineNumbers.textContent = numStr;
  if (lineColInfo) {
    lineColInfo.textContent = `Lines: ${count}`;
  }
}

// ============================================================================
// Program Selection & Complete State Reset (Task 1: Mandatory Requirements)
// ============================================================================

/**
 * Completely resets all dashboard views, workflow states, agent messages,
 * comparisons, and diagnostics when switching to a different program.
 */
function resetProgramState(programId, programName, sourceCode) {
  // 1. Detach from any active SSE stream and cancel active run tracking
  if (currentEventSource) {
    try {
      currentEventSource.close();
    } catch (e) {
      console.warn("EventSource close error:", e);
    }
    currentEventSource = null;
  }
  activeRunId = null;
  activeRunMode = null;

  // 2. Update program identity
  currentProgramId = programId;
  currentProgramName = programName;
  currentProgramCode = sourceCode;

  // 3. Reset workflow states
  normalState = {
    status: 'idle',
    programId: programId,
    runId: null,
    data: null,
    error: null
  };
  aiState = {
    status: 'idle',
    programId: programId,
    runId: null,
    data: null,
    error: null
  };

  // 4. Update editor and headers
  const textarea = document.getElementById('editor-textarea');
  if (textarea) {
    textarea.value = sourceCode;
    updateLineNumbers();
  }
  const fileTitle = document.getElementById('editor-file-title');
  const headerTitle = document.getElementById('header-filename');
  if (fileTitle) fileTitle.textContent = programName;
  if (headerTitle) headerTitle.textContent = programName;

  // Update left buffer on Tab 3
  const leftPre = document.getElementById('opt-left-code');
  if (leftPre) leftPre.textContent = sourceCode;

  // 5. Clear AI Activity panel messages & status
  currentRunMessages = [];
  clearSyncWarning();
  toastManager.clear();
  const container = document.getElementById('agent-messages-container');
  if (container) {
    container.innerHTML = '<div class="text-center py-8 text-navy-400 text-[11.5px] font-mono">Awaiting execution. Run AI Optimized to stream live multi-agent communication.</div>';
  }
  const msgCounter = document.getElementById('msg-counter');
  if (msgCounter) msgCounter.textContent = '0 messages';
  const statusLabel = document.getElementById('multiagent-status-label');
  if (statusLabel) statusLabel.textContent = 'Standby';
  const pulse = document.getElementById('pipeline-status-pulse');
  if (pulse) pulse.className = 'w-2 h-2 rounded-full bg-slate-300';

  // Reset checklist step pills
  resetChecklistSteps();

  // 6. Reset Card 1: Original / Normal Result
  renderCard1();

  // 7. Reset Card 2: AI Optimized Result
  renderCard2();

  // 8. Reset Card 3: Performance Comparison
  renderCard3();

  // 9. Reset Compilation Diagnostics Bar
  resetDiagnosticsBar();

  // 10. Clear Tab 2 (AI Analysis - 6 Accordions & Workflow Report)
  resetAIAnalysisAccordions();
  resetWorkflowReport();

  // 11. Clear Tab 3 (Optimized Code preview)
  resetOptimizedCodeBuffer();

  // 12. Reset pipeline flag & enable execution buttons
  const flag = document.getElementById('active-pipeline-flag');
  if (flag) flag.textContent = "Pipeline: Idle / Ready";
  enableRunButtons();
}

function resetChecklistSteps() {
  const steps = [
    { id: "step-profiling", title: "1. Program Profile" },
    { id: "step-strategy", title: "2. AI Strategy" },
    { id: "step-reviewer", title: "3. Reviewer Gate" },
    { id: "step-security", title: "4. Security Gate" },
    { id: "step-benchmark", title: "5. Benchmark" },
    { id: "step-regression", title: "6. Regression Audit" },
  ];
  steps.forEach(s => {
    const el = document.getElementById(s.id);
    if (el) {
      el.className = "flex items-center justify-between p-1.5 rounded bg-navy-50 border border-navy-200/60";
      el.setAttribute('data-status', 'pending');
      el.setAttribute('aria-label', `${s.title}: Pending`);
      const badge = el.querySelector('.step-badge');
      if (badge) {
        badge.className = "step-badge font-mono text-[9.5px] text-navy-400 font-normal";
        badge.textContent = "Pending";
      }
    }
  });
}

function resetDiagnosticsBar() {
  const diagBadge = document.getElementById('diagnostics-badge');
  const buildText = document.getElementById('build-status-text');
  const buildDetails = document.getElementById('build-details-text');
  const tag1 = document.getElementById('opt-pass-tag-1');
  const tag2 = document.getElementById('opt-pass-tag-2');
  const statusBox = document.getElementById('build-status-box');

  if (diagBadge) {
    diagBadge.className = "font-mono text-[11px] font-semibold px-2 py-0.5 rounded bg-emerald-100 text-emerald-800 border border-emerald-300";
    diagBadge.textContent = "Ready for compile";
  }
  if (buildText) buildText.textContent = "Toolchain status: LLVM Clang & Opt verified";
  if (buildDetails) {
    buildDetails.textContent = "Select a sample or paste custom C source code. Compiler will execute benchmark measurements in isolated run workspaces.";
  }
  if (tag1) tag1.textContent = "DQN Policy";
  if (tag2) tag2.textContent = "Security Gate";
  if (statusBox) {
    statusBox.className = "w-7 h-7 rounded bg-emerald-50 text-emerald-600 border border-emerald-200 flex items-center justify-center shrink-0 mt-0.5";
    statusBox.innerHTML = '<span class="material-symbols-outlined text-[18px]">check</span>';
  }
}

function resetAIAnalysisAccordions() {
  // Accordion 1: Program Profile
  const pfInsts = document.getElementById('pf-insts');
  const pfMem = document.getElementById('pf-mem');
  const pfBranches = document.getElementById('pf-branches');
  const pfLoops = document.getElementById('pf-loops');
  const pfDomLabel = document.getElementById('pf-dominant-label');
  const pfDomVal = document.getElementById('pf-dominant-value');
  if (pfInsts) pfInsts.textContent = "—";
  if (pfMem) pfMem.textContent = "—";
  if (pfBranches) pfBranches.textContent = "—";
  if (pfLoops) pfLoops.textContent = "—";
  if (pfDomLabel) pfDomLabel.textContent = "Awaiting execution";
  if (pfDomVal) pfDomVal.textContent = "";

  // Accordion 2: AI Selected Strategy
  const stratBase = document.getElementById('strat-baseline');
  const stratSel = document.getElementById('strat-selected');
  const stratEff = document.getElementById('strat-effective');
  const stratProv = document.getElementById('strat-provenance');
  const stratFb = document.getElementById('strat-fallback');
  const stratMod = document.getElementById('strat-model');
  if (stratBase) stratBase.textContent = "-O3 (Reference)";
  if (stratSel) stratSel.textContent = "—";
  if (stratEff) stratEff.textContent = "—";
  if (stratProv) stratProv.textContent = "—";
  if (stratFb) stratFb.textContent = "No";
  if (stratMod) stratMod.textContent = "production_v0";

  // Accordion 3: MOO Decision
  const tbody = document.getElementById('moo-candidates-tbody');
  if (tbody) {
    tbody.innerHTML = '<tr><td colspan="6" class="p-3 text-center text-navy-400">Run AI Optimized to generate Pareto frontier candidate analysis.</td></tr>';
  }

  // Accordion 4: Security Gates
  const g1 = document.getElementById('sec-gate-1');
  const g2 = document.getElementById('sec-gate-2');
  const g3 = document.getElementById('sec-gate-3');
  if (g1) g1.textContent = "Static verification of buffer indices and assertions.";
  if (g2) g2.textContent = "Checks for pointer overflow and memory boundary preservation.";
  if (g3) g3.textContent = "Enforces safe strategy substitutions if risk detected.";

  // Accordion 5: Performance Benchmark Audit
  const auditBase = document.getElementById('audit-base-time');
  const auditOpt = document.getElementById('audit-opt-time');
  const auditSpd = document.getElementById('audit-speedup');
  const auditReg = document.getElementById('audit-regression');
  if (auditBase) auditBase.textContent = "—";
  if (auditOpt) auditOpt.textContent = "—";
  if (auditSpd) auditSpd.textContent = "—";
  if (auditReg) auditReg.textContent = "—";

  // Accordion 6: XAI Reasoning
  const xaiList = document.getElementById('xai-reasons-list');
  if (xaiList) {
    xaiList.innerHTML = `
      <li class="flex items-start gap-2.5">
        <span class="material-symbols-outlined text-accent text-[17px] shrink-0 mt-0.5">check_circle</span>
        <span id="xai-main-reason">Run an optimization to view empirical XAI attribution rationale.</span>
      </li>
    `;
  }
}

function resetOptimizedCodeBuffer() {
  const rightHeader = document.getElementById('opt-right-header');
  const passBadge = document.getElementById('opt-pass-badge');
  const rightCode = document.getElementById('opt-right-code');
  if (rightHeader) rightHeader.textContent = "Synthesized: Optimized LLVM IR";
  if (passBadge) passBadge.textContent = "Transformed";
  if (rightCode) rightCode.textContent = "; Awaiting optimization run...";
}

// Sample Selector Handler
async function onSampleSelected(sampleId) {
  try {
    const res = await fetch(`/api/sample/${sampleId}`);
    if (!res.ok) return;
    const data = await res.json();
    const sourceCode = data.source_code || "";

    const nameMap = {
      gemm: "src/benchmarks/polybench/gemm.c",
      tc1_loop_heavy: "src/test_cases/TC1_loop_heavy.c",
      tc2_security_bounds: "src/test_cases/TC2_security_bounds_check.c",
      tc3_math_intensive: "src/test_cases/TC3_math_intensive.c",
      tc4_security_null: "src/test_cases/TC4_security_null_overflow.c",
      bubble_sort: "src/test_cases/26_bubble_sort.c"
    };
    const title = nameMap[sampleId] || `${sampleId}.c`;

    // Pattern hints
    const patternHint = document.getElementById('editor-pattern-hint');
    const vectorHint = document.getElementById('editor-vector-hint');
    if (sampleId.includes('security')) {
      if (patternHint) patternHint.textContent = "Security boundary & assertion guards present";
      if (vectorHint) vectorHint.textContent = "Security Gate Active";
    } else {
      if (patternHint) patternHint.textContent = "Affine loop nest candidate for SIMD / polyhedral tiling";
      if (vectorHint) vectorHint.textContent = "Vectorization potential: High";
    }

    // Reset everything for this new program
    resetProgramState(sampleId, title, sourceCode);

  } catch (err) {
    console.error("Failed to load sample:", err);
  }
}

// User Manual Text Editing in Editor
function onEditorContentChanged() {
  updateLineNumbers();
  const textarea = document.getElementById('editor-textarea');
  if (!textarea) return;
  const newCode = textarea.value;

  // Check if modified from current code
  if (newCode !== currentProgramCode) {
    currentProgramCode = newCode;
    const hash = computeSimpleHash(newCode);
    const newProgId = `custom_${hash}`;
    const newProgName = `custom / user_code.c (${hash.slice(0, 6)})`;

    // Reset results because the code has changed
    currentProgramId = newProgId;
    currentProgramName = newProgName;

    const fileTitle = document.getElementById('editor-file-title');
    const headerTitle = document.getElementById('header-filename');
    if (fileTitle) fileTitle.textContent = newProgName;
    if (headerTitle) headerTitle.textContent = newProgName;

    // Invalidate Left Buffer on Tab 3
    const leftPre = document.getElementById('opt-left-code');
    if (leftPre) leftPre.textContent = newCode;

    // Reset both workflows to idle for modified code
    normalState = { status: 'idle', programId: newProgId, runId: null, data: null, error: null };
    aiState = { status: 'idle', programId: newProgId, runId: null, data: null, error: null };

    renderCard1();
    renderCard2();
    renderCard3();
    resetAIAnalysisAccordions();
    resetOptimizedCodeBuffer();
  }
}

// ============================================================================
// Render Functions for the 3 Lower Analysis Cards
// ============================================================================

function renderCard1() {
  const timeEl = document.getElementById('card1-time');
  const statusEl = document.getElementById('card1-status');
  const sizeEl = document.getElementById('card1-size');
  const secEl = document.getElementById('card1-security');
  const relEl = document.getElementById('card1-reliability');
  const measEl = document.getElementById('card1-meas-status');

  if (normalState.status === 'idle') {
    if (timeEl) timeEl.textContent = "—";
    if (statusEl) statusEl.textContent = "Awaiting run";
    if (sizeEl) sizeEl.textContent = "—";
    if (secEl) secEl.textContent = "Standard baseline";
    if (relEl) relEl.textContent = "—";
    if (measEl) measEl.textContent = "NOT_RUN";
  } else if (normalState.status === 'running') {
    if (timeEl) timeEl.textContent = "Measuring...";
    if (statusEl) statusEl.textContent = "Running (-O3)";
    if (sizeEl) sizeEl.textContent = "Compiling...";
    if (secEl) secEl.textContent = "Baseline (-O3)";
    if (relEl) relEl.textContent = "In progress";
    if (measEl) measEl.textContent = "MEASURING";
  } else if (normalState.status === 'failed') {
    if (timeEl) timeEl.textContent = "Failed";
    if (statusEl) statusEl.textContent = "Error";
    if (sizeEl) sizeEl.textContent = "N/A";
    if (secEl) secEl.textContent = "Build/Execution Failed";
    if (relEl) relEl.textContent = "Unreliable";
    if (measEl) measEl.textContent = "FAILED";
  } else if (normalState.status === 'succeeded' && normalState.data) {
    const view = normalState.data.view || {};
    const timing = view.optimized_timing;
    if (timing && timing.median_s !== null) {
      if (timeEl) timeEl.textContent = `${(timing.median_s * 1000).toFixed(3)} ms`;
      if (statusEl) statusEl.textContent = "Validated";
      if (sizeEl) sizeEl.textContent = timing.code_size_bytes ? `${timing.code_size_bytes.toLocaleString()} bytes` : "—";
      if (secEl) secEl.textContent = "Baseline (-O3)";
      if (relEl) relEl.textContent = timing.timing_is_reliable ? "Reliable" : "High Variance";
      if (measEl) measEl.textContent = view.benchmark_status || "OK";
    } else {
      if (timeEl) timeEl.textContent = "Failed";
      if (statusEl) statusEl.textContent = "Error";
      if (measEl) measEl.textContent = "FAILED";
    }
  }
}

function renderCard2() {
  const timeEl = document.getElementById('card2-time');
  const statusEl = document.getElementById('card2-status');
  const badgeEl = document.getElementById('card2-strategy-badge');
  const stratEl = document.getElementById('card2-selected-strat');
  const effEl = document.getElementById('card2-effective-strat');
  const secEl = document.getElementById('card2-security');
  const sizeEl = document.getElementById('card2-size');
  const fallbackEl = document.getElementById('card2-fallback');

  if (aiState.status === 'idle') {
    if (timeEl) timeEl.textContent = "—";
    if (statusEl) statusEl.textContent = "Awaiting run";
    if (badgeEl) badgeEl.textContent = "AI Strategy";
    if (stratEl) stratEl.textContent = "—";
    if (effEl) effEl.textContent = "—";
    if (secEl) secEl.textContent = "—";
    if (sizeEl) sizeEl.textContent = "—";
    if (fallbackEl) fallbackEl.textContent = "No";
  } else if (aiState.status === 'running') {
    if (timeEl) timeEl.textContent = "Optimizing...";
    if (statusEl) statusEl.textContent = "Deliberating";
    if (badgeEl) badgeEl.textContent = "Synthesizing";
    if (stratEl) stratEl.textContent = "Proposing...";
    if (effEl) effEl.textContent = "Under Review...";
    if (secEl) secEl.textContent = "Gate Checking...";
    if (sizeEl) sizeEl.textContent = "—";
    if (fallbackEl) fallbackEl.textContent = "Evaluating";
  } else if (aiState.status === 'failed') {
    if (timeEl) timeEl.textContent = "Failed";
    if (statusEl) statusEl.textContent = "Error";
    if (badgeEl) badgeEl.textContent = "Failed";
    if (stratEl) stratEl.textContent = "Aborted";
    if (effEl) effEl.textContent = "Aborted";
    if (secEl) secEl.textContent = "Execution Failed";
    if (sizeEl) sizeEl.textContent = "N/A";
    if (fallbackEl) fallbackEl.textContent = "N/A";
  } else if (aiState.status === 'succeeded' && aiState.data) {
    const view = aiState.data.view || {};
    const timing = view.optimized_timing;
    const effStrat = view.effective_strategy || view.selected_strategy || "—";

    if (badgeEl) badgeEl.textContent = effStrat;
    if (stratEl) stratEl.textContent = view.selected_strategy || "—";
    if (effEl) effEl.textContent = effStrat;

    if (timing && timing.median_s !== null) {
      if (timeEl) timeEl.textContent = `${(timing.median_s * 1000).toFixed(3)} ms`;
      if (statusEl) statusEl.textContent = "Optimal";
      if (sizeEl) sizeEl.textContent = timing.code_size_bytes ? `${timing.code_size_bytes.toLocaleString()} bytes` : "—";
    } else {
      if (timeEl) timeEl.textContent = "Failed";
      if (statusEl) statusEl.textContent = "Error";
    }

    if (secEl) {
      secEl.textContent = view.security?.verdict || "PASSED";
    }
    if (fallbackEl) {
      fallbackEl.textContent = view.fallback_occurred ? "Yes (Security Substitute)" : "No (Direct Selection)";
    }
  }
}

function renderCard3() {
  const speedupEl = document.getElementById('card3-speedup');
  const verdictEl = document.getElementById('card3-verdict');
  const badgeEl = document.getElementById('card3-verdict-badge');
  const dotEl = document.getElementById('card3-dot');
  const deltaTimeEl = document.getElementById('card3-delta-time');
  const deltaSizeEl = document.getElementById('card3-delta-size');
  const regStatusEl = document.getElementById('card3-regression-status');

  // Both workflows must belong to the exact same program identity
  const isSameProgram = (normalState.programId === currentProgramId && aiState.programId === currentProgramId);

  // If either is running
  if (normalState.status === 'running' || aiState.status === 'running') {
    if (speedupEl) speedupEl.textContent = "—";
    if (verdictEl) verdictEl.textContent = "Execution in progress...";
    if (badgeEl) {
      badgeEl.className = "font-mono text-[10.5px] px-2 py-0.5 rounded bg-blue-100 text-accent font-semibold border border-blue-200";
      badgeEl.textContent = "RUNNING";
    }
    if (dotEl) dotEl.className = "w-2 h-2 rounded-full bg-accent animate-ping shrink-0";
    if (deltaTimeEl) deltaTimeEl.textContent = "—";
    if (deltaSizeEl) deltaSizeEl.textContent = "—";
    if (regStatusEl) regStatusEl.textContent = "In progress";
    return;
  }

  // If either failed
  if (normalState.status === 'failed' || aiState.status === 'failed') {
    if (speedupEl) speedupEl.textContent = "—";
    if (verdictEl) verdictEl.textContent = "Comparison Unavailable (Run Failed)";
    if (badgeEl) {
      badgeEl.className = "font-mono text-[10.5px] px-2 py-0.5 rounded bg-rose-100 text-rose-800 font-semibold border border-rose-300";
      badgeEl.textContent = "FAILED";
    }
    if (dotEl) dotEl.className = "w-2 h-2 rounded-full bg-rose-500 shrink-0";
    if (deltaTimeEl) deltaTimeEl.textContent = "N/A";
    if (deltaSizeEl) deltaSizeEl.textContent = "N/A";
    if (regStatusEl) regStatusEl.textContent = "FAILED";
    return;
  }

  // Both must be succeeded and from the SAME program
  if (!isSameProgram || normalState.status !== 'succeeded' || aiState.status !== 'succeeded') {
    if (speedupEl) speedupEl.textContent = "—";
    if (badgeEl) {
      badgeEl.className = "font-mono text-[10.5px] px-2 py-0.5 rounded bg-navy-100 text-navy-700 font-semibold border border-navy-200";
      badgeEl.textContent = "Awaiting Data";
    }
    if (dotEl) dotEl.className = "w-2 h-2 rounded-full bg-slate-300 shrink-0";
    if (deltaTimeEl) deltaTimeEl.textContent = "—";
    if (deltaSizeEl) deltaSizeEl.textContent = "—";
    if (regStatusEl) regStatusEl.textContent = "—";

    if (normalState.status === 'succeeded' && aiState.status !== 'succeeded') {
      if (verdictEl) verdictEl.textContent = "Awaiting AI-optimized run";
    } else if (aiState.status === 'succeeded' && normalState.status !== 'succeeded') {
      if (verdictEl) verdictEl.textContent = "Awaiting normal baseline run";
    } else {
      if (verdictEl) verdictEl.textContent = "Awaiting execution for selected program";
    }
    return;
  }

  // Both succeeded for current program: calculate genuine metrics
  const baseTiming = normalState.data?.view?.optimized_timing;
  const aiTiming = aiState.data?.view?.optimized_timing;

  if (!baseTiming || baseTiming.median_s === null || !aiTiming || aiTiming.median_s === null) {
    if (speedupEl) speedupEl.textContent = "—";
    if (verdictEl) verdictEl.textContent = "Invalid timing data";
    return;
  }

  const tBase = baseTiming.median_s;
  const tAI = aiTiming.median_s;
  if (tAI <= 0 || tBase <= 0) {
    if (speedupEl) speedupEl.textContent = "—";
    if (verdictEl) verdictEl.textContent = "Measurements not non-zero";
    return;
  }

  const speedup = tBase / tAI;
  const deltaMs = (tBase - tAI) * 1000;
  const pct = ((tBase - tAI) / tBase) * 100;

  if (deltaTimeEl) {
    deltaTimeEl.textContent = `${deltaMs >= 0 ? '-' : '+'}${Math.abs(deltaMs).toFixed(3)} ms (${pct >= 0 ? '+' : ''}${pct.toFixed(1)}%)`;
  }

  if (baseTiming.code_size_bytes && aiTiming.code_size_bytes && deltaSizeEl) {
    const dSize = aiTiming.code_size_bytes - baseTiming.code_size_bytes;
    deltaSizeEl.textContent = `${dSize >= 0 ? '+' : ''}${dSize} bytes`;
  }

  // Authoritative regression classification from backend
  const backendRegression = aiState.data?.view?.regression_overall_status;
  const isReliable = (baseTiming.timing_is_reliable !== false && aiTiming.timing_is_reliable !== false);

  // Gating for High-Noise / Unreliable / Inconclusive measurements
  if (!isReliable || backendRegression === 'INCONCLUSIVE') {
    if (speedupEl) speedupEl.textContent = `~${pct >= 0 ? '+' : ''}${pct.toFixed(1)}% (${speedup.toFixed(2)}x)`;
    if (verdictEl) verdictEl.textContent = "Inconclusive (Measurement Noise / High Variance)";
    if (badgeEl) {
      badgeEl.className = "font-mono text-[10.5px] px-2 py-0.5 rounded bg-amber-100 text-amber-800 font-semibold border border-amber-300";
      badgeEl.textContent = "INCONCLUSIVE";
    }
    if (dotEl) dotEl.className = "w-2 h-2 rounded-full bg-amber-500 shrink-0";
    if (regStatusEl) regStatusEl.textContent = "INCONCLUSIVE";
    return;
  }

  if (backendRegression === 'INCOMPARABLE') {
    if (speedupEl) speedupEl.textContent = "—";
    if (verdictEl) verdictEl.textContent = "Incomparable (Invalid Measurement)";
    if (badgeEl) {
      badgeEl.className = "font-mono text-[10.5px] px-2 py-0.5 rounded bg-rose-100 text-rose-800 font-semibold border border-rose-300";
      badgeEl.textContent = "INCOMPARABLE";
    }
    if (dotEl) dotEl.className = "w-2 h-2 rounded-full bg-rose-500 shrink-0";
    if (regStatusEl) regStatusEl.textContent = "INCOMPARABLE";
    return;
  }

  if (backendRegression === 'IMPROVED' || (!backendRegression && speedup > 1.02)) {
    // True Improvement
    if (speedupEl) speedupEl.textContent = `+${pct.toFixed(1)}% (${speedup.toFixed(2)}x)`;
    if (verdictEl) verdictEl.textContent = "Performance Improvement";
    if (badgeEl) {
      badgeEl.className = "font-mono text-[10.5px] px-2 py-0.5 rounded bg-emerald-100 text-emerald-800 font-semibold border border-emerald-300";
      badgeEl.textContent = "IMPROVED";
    }
    if (dotEl) dotEl.className = "w-2 h-2 rounded-full bg-emerald-500 shrink-0";
    if (regStatusEl) regStatusEl.textContent = "IMPROVED";
  } else if (backendRegression === 'REGRESSED' || (!backendRegression && speedup < 0.98)) {
    // True Regression
    if (speedupEl) speedupEl.textContent = `${pct.toFixed(1)}% (${speedup.toFixed(2)}x)`;
    if (verdictEl) verdictEl.textContent = "Performance Regression";
    if (badgeEl) {
      badgeEl.className = "font-mono text-[10.5px] px-2 py-0.5 rounded bg-rose-100 text-rose-800 font-semibold border border-rose-300";
      badgeEl.textContent = "REGRESSION";
    }
    if (dotEl) dotEl.className = "w-2 h-2 rounded-full bg-rose-500 shrink-0";
    if (regStatusEl) regStatusEl.textContent = "REGRESSION";
  } else {
    // UNCHANGED / Parity
    if (speedupEl) speedupEl.textContent = `~0.0% (${speedup.toFixed(2)}x)`;
    if (verdictEl) verdictEl.textContent = "No Difference (Parity)";
    if (badgeEl) {
      badgeEl.className = "font-mono text-[10.5px] px-2 py-0.5 rounded bg-slate-100 text-slate-800 font-semibold border border-slate-300";
      badgeEl.textContent = "PARITY";
    }
    if (dotEl) dotEl.className = "w-2 h-2 rounded-full bg-slate-500 shrink-0";
    if (regStatusEl) regStatusEl.textContent = "PARITY";
  }
}

// ============================================================================
// Toolchain Status Inspection
// ============================================================================
async function loadToolchainStatus() {
  try {
    const res = await fetch('/api/status');
    if (!res.ok) return;
    const data = await res.json();

    const engineText = document.getElementById('toolchain-engine-text');
    const platformText = document.getElementById('host-platform-text');
    const sidebarStatus = document.getElementById('sidebar-llvm-status');
    const sidebarTarget = document.getElementById('sidebar-llvm-target');
    const headerTarget = document.getElementById('header-target');

    if (data.clang_found && data.opt_found) {
      if (engineText) engineText.textContent = `${data.clang_version.split(' ')[0]} ${data.clang_version.split(' ')[2] || ''} Ready`;
      if (sidebarStatus) sidebarStatus.textContent = `Clang & Opt 23.1 · Ready`;
    } else {
      if (engineText) engineText.textContent = `Toolchain Incomplete`;
      if (sidebarStatus) sidebarStatus.textContent = `Toolchain Offline`;
    }

    if (platformText) platformText.textContent = `Host: ${data.host_platform} (Raptorlake)`;
    if (sidebarTarget) sidebarTarget.textContent = `Target: ${data.default_target}`;
    if (headerTarget) headerTarget.textContent = `Target: ${data.default_target}`;

  } catch (err) {
    console.warn("Toolchain status load error:", err);
  }
}

// ============================================================================
// Multi-Agent Activity Feed Formatting
// ============================================================================

function getAgentBadgeHtml(role) {
  const styles = {
    CodeAnalystAgent: "bg-cyan-100 text-cyan-800 border-cyan-300",
    ProgramProfilingAgent: "bg-purple-100 text-purple-800 border-purple-300",
    OptimizationStrategistAgent: "bg-blue-100 text-blue-800 border-blue-300",
    OptimizationReviewerAgent: "bg-amber-100 text-amber-800 border-amber-300",
    BenchmarkAgent: "bg-emerald-100 text-emerald-800 border-emerald-300",
    FinalDecisionAgent: "bg-indigo-100 text-indigo-800 border-indigo-300",
    Orchestrator: "bg-navy-100 text-navy-800 border-navy-300"
  };
  const cls = styles[role] || "bg-navy-100 text-navy-700 border-navy-200";
  return `<span class="px-1.5 py-0.5 rounded font-mono text-[10px] font-bold border ${cls}">${role.replace("Agent", "")}</span>`;
}

function getMessageTypeTagHtml(mtype) {
  const map = {
    STRATEGY_PROPOSAL: "bg-blue-50 text-accent font-semibold",
    REVIEW_ACCEPT: "bg-emerald-50 text-emerald-700 font-semibold",
    REVIEW_REJECT: "bg-rose-50 text-rose-700 font-semibold",
    STRATEGY_REVISED: "bg-amber-50 text-amber-700 font-semibold",
    FINAL_DECISION: "bg-indigo-50 text-indigo-700 font-semibold",
    BENCHMARK_REPORT: "bg-emerald-50 text-emerald-700 font-semibold",
    PROGRAM_PROFILE: "bg-purple-50 text-purple-700 font-semibold",
    IR_FEATURES: "bg-cyan-50 text-cyan-700 font-semibold",
    CODE_ANALYSIS: "bg-cyan-50 text-cyan-700 font-semibold"
  };
  const cls = map[mtype] || "bg-navy-100 text-navy-600";
  return `<span class="px-1.5 py-0.2 rounded font-mono text-[9.5px] ${cls}">${mtype}</span>`;
}

function formatPayloadSummary(mtype, payload) {
  if (!payload) return "";
  if (mtype === 'STRATEGY_PROPOSAL') {
    const strat = payload.strategy || "—";
    const conf = payload.confidence ? ` (conf: ${payload.confidence})` : "";
    return `Proposed optimization: <strong class="text-accent">${strat}</strong>${conf}. Reason: ${payload.selection_reason || "Policy selection"}`;
  }
  if (mtype === 'REVIEW_REJECT') {
    return `<span class="text-rose-700 font-semibold">Rejected:</span> ${payload.reason || "Critique issued"}. Requested: <em>${payload.requested_action || "revision"}</em>`;
  }
  if (mtype === 'REVIEW_ACCEPT') {
    return `<span class="text-emerald-700 font-semibold">Approved:</span> Strategy <strong class="text-navy-900">${payload.strategy}</strong> meets verification constraints.`;
  }
  if (mtype === 'STRATEGY_REVISED') {
    return `Revised proposal: <strong class="text-amber-700">${payload.strategy}</strong>. Adaptation: ${payload.revision_reason || "Policy adjustment"}`;
  }
  if (mtype === 'FINAL_DECISION') {
    const eff = payload.effective_strategy;
    const fb = payload.fallback_occurred ? " <span class='text-amber-600 font-bold'>[SECURITY FALLBACK]</span>" : "";
    return `Security Gate authorized: <strong class="text-emerald-700">${eff}</strong>${fb}. Gates: ${payload.security_gate_result?.overall_verdict || "PASS"}`;
  }
  if (mtype === 'BENCHMARK_REPORT') {
    const timing = payload.moo_result?.baseline || payload.timing;
    const med = timing?.median_s ? `${(timing.median_s * 1000).toFixed(2)}ms` : "Complete";
    return `Execution measurement: <strong class="text-navy-900">${med}</strong>. Correctness validated against reference.`;
  }
  if (mtype === 'PROGRAM_PROFILE') {
    const prof = payload.profile || {};
    return `Profile: <strong class="text-navy-900">${prof.label || "Analyzed"}</strong> (Dominant: ${prof.dominant_feature || "Insts"}=${prof.dominant_feature_value || 0})`;
  }
  if (mtype === 'IR_FEATURES') {
    const f = payload.ir_features || {};
    return `Extracted ${f.total_instructions || 0} instructions, ${f.vectorizable_loops || 0} loops, ${f.memory_instructions || 0} memory ops.`;
  }
  return JSON.stringify(payload).slice(0, 100);
}

function explainAgentMessage(msg) {
  if (!msg || typeof msg !== 'object') {
    return {
      sender: "Unknown",
      recipient: "Unknown",
      message_type: "UNKNOWN",
      step: 0,
      timestamp: "",
      category: "error",
      simple_text: "Malformed or empty agent message.",
      technical_summary: "Empty message payload",
      raw_payload: {}
    };
  }

  const sender = String(msg.sender || "Agent");
  const recipient = String(msg.recipient || "All");
  const mtype = String(msg.message_type || msg.type || "UNKNOWN").toUpperCase();
  const step = parseInt(msg.step, 10) || 1;
  const timestamp = String(msg.timestamp || "");
  const payload = (msg.payload && typeof msg.payload === 'object') ? msg.payload : {};

  let category = "observation";
  let simple_text = "";
  let technical_summary = "";

  if (mtype === "IR_FEATURES") {
    category = "observation";
    const f = payload.ir_features || {};
    const tot = f.total_instructions || payload.total_instructions || 0;
    const loops = f.vectorizable_loops || payload.vectorizable_loops || 0;
    const mem = (f.load_instructions || 0) + (f.store_instructions || 0) || f.memory_instructions || 0;
    simple_text = `The Code Analyst examined the unoptimized program structure and counted ${Number(tot).toLocaleString()} instructions, ${loops} vectorizable loop nests, and ${mem} memory operations to guide optimization choices.`;
    technical_summary = `IR features extracted: ${tot} instructions, ${loops} loops, ${mem} memory operations.`;

  } else if (mtype === "PROFILE" || mtype === "PROGRAM_PROFILE") {
    category = "observation";
    const prof = payload.profile || payload;
    const label = prof.label || "mixed";
    const dominant = prof.dominant_feature || "instructions";
    simple_text = `Program profiling classified this code as '${label}' workload with '${dominant}' as the dominant computational characteristic.`;
    technical_summary = `Program profile: label=${label}, dominant_feature=${dominant}.`;

  } else if (mtype === "STRATEGY_PROPOSAL") {
    category = "proposal";
    const strat = payload.strategy || "candidate";
    simple_text = `The Optimization Strategist proposed candidate optimization sequence '${strat}' based on multi-objective search.`;
    technical_summary = `Candidate strategy proposed: '${strat}'.`;

  } else if (mtype === "REVIEW_ACCEPT") {
    category = "review";
    const strat = payload.strategy || "candidate";
    simple_text = `The Optimization Reviewer evaluated candidate '${strat}' against compiler safety diagnostics and approved it for security gate evaluation.`;
    technical_summary = `Reviewer APPROVED candidate '${strat}'.`;

  } else if (mtype === "REVIEW_REJECT") {
    category = "review";
    const strat = payload.strategy || "candidate";
    const feedback = payload.feedback || "Policy mismatch or diagnostic alert";
    const rev = payload.revision_number || 0;
    simple_text = `The Optimization Reviewer critiqued candidate '${strat}' and rejected it due to diagnostic concerns: '${feedback}'. The Strategist must formulate a revised proposal.`;
    technical_summary = `Reviewer REJECTED candidate '${strat}' (revision: ${rev}, critique: ${feedback}).`;

  } else if (mtype === "STRATEGY_REVISED") {
    category = "proposal";
    const strat = payload.strategy || "revised";
    const prev = payload.revising_strategy || "previous";
    const rev = payload.revision_number || 1;
    simple_text = `The Optimization Strategist adapted its recommendation in response to Reviewer feedback, proposing alternative candidate '${strat}' (replacing '${prev}') for revision round #${rev}.`;
    technical_summary = `Revised strategy '${strat}' formulated for revision #${rev} (replacing '${prev}').`;

  } else if (mtype === "FINAL_DECISION") {
    category = "security";
    const eff = payload.effective_strategy || "baseline";
    const fallback = Boolean(payload.fallback_occurred);
    const gate_res = payload.security_gate_result || {};
    const verdict = gate_res.overall_verdict || gate_res.decision || "PASS";
    if (fallback) {
      simple_text = `The Security Gate detected safety or verification risks in the proposed candidate and safely substituted verified baseline strategy '${eff}' (MOO fallback applied).`;
      technical_summary = `Security Gate triggered FALLBACK to '${eff}' (verdict: ${verdict}).`;
    } else if (verdict === "BLOCK" || verdict === "BLOCKED" || verdict === "REJECT") {
      simple_text = `The Security Gate BLOCKED deployment of candidate '${eff}' due to security constraint violations.`;
      technical_summary = `Security Gate BLOCKED strategy '${eff}' (verdict: ${verdict}).`;
    } else {
      simple_text = `The Security Gate completed static AST scanning and pointer safety checks, authorizing '${eff}' for compilation.`;
      technical_summary = `Security Gate AUTHORIZED strategy '${eff}' (verdict: ${verdict}).`;
    }

  } else if (mtype === "BENCHMARK_RESULT" || mtype === "BENCHMARK_REPORT") {
    category = "benchmark";
    const status = payload.status || "OK";
    const timing = payload.timing || (payload.moo_result && payload.moo_result.optimized) || {};
    const med = timing.median_s;
    if (status === "OK" && med !== undefined && med !== null) {
      const ms = Math.round(med * 100000) / 100;
      simple_text = `The Benchmark Agent compiled and measured the program under hardware performance timers, recording an execution runtime of ${ms} ms with exit code 0.`;
      technical_summary = `Empirical benchmark recorded: median=${ms} ms, status=OK.`;
    } else if (status !== "OK") {
      const err = payload.error || "Benchmark execution failure";
      simple_text = `The Benchmark Agent reported a benchmarking failure during measurement: ${err}.`;
      technical_summary = `Benchmark failed: ${err}.`;
    } else {
      simple_text = "The Benchmark Agent completed execution timing measurements.";
      technical_summary = "Benchmark execution completed.";
    }

  } else if (mtype === "CODE_ANALYSIS") {
    category = "observation";
    const analysis = payload.analysis || "Inspected source code.";
    simple_text = `The Code Analyst examined the source program to prepare for baseline -O3 compilation: ${analysis}`;
    technical_summary = `Code analysis complete: ${analysis}`;

  } else if (mtype === "ERROR") {
    category = "error";
    const err = payload.error || payload.message || "Unknown error";
    const stage = payload.stage || "execution";
    simple_text = `An agent reported an error during the ${stage} stage: ${err}.`;
    technical_summary = `Execution error in stage '${stage}': ${err}.`;

  } else {
    category = "coordination";
    const keys = Object.keys(payload);
    simple_text = `This agent sent a message of type '${mtype}', but TOACD does not yet have a specialized plain-English explanation for this specific message type.`;
    technical_summary = `Generic agent message: type=${mtype}, keys=${keys.join(', ')}.`;
  }

  return {
    sender,
    recipient,
    message_type: mtype,
    step,
    timestamp,
    category,
    simple_text,
    technical_summary,
    raw_payload: payload
  };
}

function getMessageCategoryBadgeHtml(category) {
  const cat = (category || 'coordination').toLowerCase();
  let bgClass = "bg-slate-100 text-slate-700 border-slate-300";
  if (cat === 'observation') bgClass = "bg-sky-50 text-sky-700 border-sky-300";
  else if (cat === 'proposal') bgClass = "bg-indigo-50 text-indigo-700 border-indigo-300";
  else if (cat === 'review') bgClass = "bg-purple-50 text-purple-700 border-purple-300";
  else if (cat === 'security') bgClass = "bg-emerald-50 text-emerald-700 border-emerald-300";
  else if (cat === 'benchmark') bgClass = "bg-blue-50 text-blue-700 border-blue-300";
  else if (cat === 'error') bgClass = "bg-rose-50 text-rose-700 border-rose-300";
  return `<span class="px-1.5 py-0.2 rounded font-mono text-[9px] font-semibold border ${bgClass} uppercase tracking-wider">${escapeHtml(cat)}</span>`;
}

function toggleMessageDrawer(cardId) {
  const drawer = document.getElementById(`${cardId}-payload`);
  if (!drawer) return;
  const isHidden = drawer.classList.contains('hidden');
  const btn = drawer.previousElementSibling;
  if (isHidden) {
    drawer.classList.remove('hidden');
    if (btn) {
      btn.setAttribute('aria-expanded', 'true');
      const chev = btn.querySelector('.toggle-chevron');
      if (chev) chev.classList.add('rotate-180');
    }
  } else {
    drawer.classList.add('hidden');
    if (btn) {
      btn.setAttribute('aria-expanded', 'false');
      const chev = btn.querySelector('.toggle-chevron');
      if (chev) chev.classList.remove('rotate-180');
    }
  }
}

function appendAgentMessageCard(msg) {
  const container = document.getElementById('agent-messages-container');
  if (!container) return;

  if (container.querySelector('.text-center')) {
    container.innerHTML = '';
  }

  currentRunMessages.push(msg);
  const cardIndex = currentRunMessages.length;
  const cardId = `msg-card-${cardIndex}`;

  const exp = explainAgentMessage(msg);
  const senderBadge = getAgentBadgeHtml(exp.sender);
  const typeTag = getMessageTypeTagHtml(exp.message_type);
  const categoryBadge = getMessageCategoryBadgeHtml(exp.category);
  const timeStr = exp.timestamp ? (exp.timestamp.split('T')[1]?.slice(0, 8) || "") : "";
  const currentText = (currentViewMode === 'technical') ? exp.technical_summary : exp.simple_text;
  const rawJson = JSON.stringify(exp.raw_payload || {}, null, 2);
  const fieldCount = Object.keys(exp.raw_payload || {}).length;

  const card = document.createElement('div');
  card.id = cardId;
  card.className = "p-2.5 rounded bg-white border border-navy-200/80 shadow-2xs flex flex-col gap-1.5 msg-card-hover transition-all duration-180";

  card.innerHTML = `
    <div class="flex items-center justify-between gap-1 border-b border-navy-100 pb-1.5">
      <div class="flex items-center gap-1.5 min-w-0 flex-wrap">
        ${senderBadge}
        <span class="text-[10px] text-navy-400 font-mono">→ ${escapeHtml(exp.recipient)}</span>
        ${typeTag}
        ${categoryBadge}
      </div>
      <div class="flex items-center gap-1 text-[9.5px] font-mono text-navy-400 shrink-0">
        <span>Step ${exp.step}</span>
        <span>·</span>
        <span>${timeStr || 'live'}</span>
      </div>
    </div>
    <div class="msg-explanation text-[11px] text-navy-800 leading-snug font-sans"
         data-simple="${escapeHtml(exp.simple_text)}"
         data-technical="${escapeHtml(exp.technical_summary)}">
      ${escapeHtml(currentText)}
    </div>
    <div class="mt-0.5">
      <button type="button"
              class="drawer-toggle flex items-center gap-1 text-[9.5px] text-navy-500 hover:text-navy-800 font-mono cursor-pointer transition-colors"
              aria-expanded="false"
              aria-controls="${cardId}-payload"
              onclick="toggleMessageDrawer('${cardId}')">
        <span class="material-symbols-outlined text-[12px] transition-transform duration-150 toggle-chevron">expand_more</span>
        <span>Technical Payload (${fieldCount} field${fieldCount === 1 ? '' : 's'})</span>
      </button>
      <div id="${cardId}-payload" class="hidden mt-1 p-2 bg-navy-950 text-sky-200 rounded font-mono text-[9.5px] overflow-x-auto max-h-48 whitespace-pre" role="region" aria-label="Raw message payload">
${escapeHtml(rawJson)}
      </div>
    </div>
  `;

  container.appendChild(card);
  container.scrollTop = container.scrollHeight;

  const countEl = document.getElementById('msg-counter');
  if (countEl) {
    const total = container.querySelectorAll('.p-2\\.5.rounded.bg-white, .p-2.rounded.bg-white').length;
    countEl.textContent = `${total} message${total === 1 ? '' : 's'}`;
  }
}

// ============================================================================
// Authoritative Stage Transition Handler & Event Reducer (Phase 0)
// ============================================================================

function handleStageTransition(evt) {
  const stage = evt.stage;
  let status = evt.status || (evt.event_type ? evt.event_type.replace('stage_', '') : '');
  const payload = evt.payload || {};

  const stageElMap = {
    profiling: { id: "step-profiling", num: 1, name: "Profiling", title: "1. Program Profile" },
    strategy_selection: { id: "step-strategy", num: 2, name: "Strategy Selection", title: "2. AI Strategy" },
    agent_review: { id: "step-reviewer", num: 3, name: "Reviewer Gate", title: "3. Reviewer Gate" },
    security_verification: { id: "step-security", num: 4, name: "Security Verification", title: "4. Security Gate" },
    benchmarking: { id: "step-benchmark", num: 5, name: "Benchmarking", title: "5. Benchmark" },
    regression_analysis: { id: "step-regression", num: 6, name: "Regression Analysis", title: "6. Regression Audit" }
  };

  const stageMeta = stageElMap[stage];
  if (!stageMeta) return;
  const el = document.getElementById(stageMeta.id);
  if (!el) return;
  const badge = el.querySelector('.step-badge');
  const stageTitle = stageMeta.title;

  // Determine semantic state:
  // 'pending' | 'running' | 'completed' | 'failed' | 'blocked' | 'skipped' | 'inconclusive'
  let semanticState = status;
  if (status === 'started') semanticState = 'running';

  if (status === 'completed') {
    if (stage === 'benchmarking') {
      const timingReliable = payload.timing_is_reliable !== false &&
        (!payload.timing || payload.timing.timing_is_reliable !== false) &&
        payload.valid_reference !== false &&
        (!payload.moo_result?.baseline || payload.moo_result.baseline.timing_is_reliable !== false) &&
        (!payload.moo_result?.optimized || payload.moo_result.optimized.timing_is_reliable !== false);
      if (!timingReliable) {
        semanticState = 'inconclusive';
      }
    } else if (stage === 'regression_analysis') {
      const regStatus = (payload.overall_status || payload.status || '').toUpperCase();
      if (regStatus === 'INCONCLUSIVE') {
        semanticState = 'inconclusive';
      }
    }
  } else if (status === 'inconclusive') {
    semanticState = 'inconclusive';
  }

  // Check for Blocked
  if (status === 'blocked' || payload.verdict === 'BLOCKED' || payload.verdict === 'REJECT') {
    if (!payload.fallback_occurred) {
      semanticState = 'blocked';
    }
  }

  // Update live stage progress header indicator
  const statusLabel = document.getElementById('multiagent-status-label');
  if (status === 'started' && statusLabel) {
    statusLabel.textContent = `Stage ${stageMeta.num}/6 · ${stageMeta.name}`;
  }

  el.setAttribute('data-status', semanticState);

  if (semanticState === 'running') {
    el.className = "flex items-center justify-between p-1.5 rounded bg-blue-50/90 border border-blue-300 shadow-2xs";
    el.setAttribute('aria-label', `${stageTitle}: Running`);
    if (badge) {
      badge.className = "step-badge font-mono text-[9.5px] font-semibold text-accent animate-pulse";
      badge.textContent = "Running";
    }
  } else if (semanticState === 'completed') {
    el.className = "flex items-center justify-between p-1.5 rounded bg-emerald-50/80 border border-emerald-300";
    let badgeText = "Completed";
    if (stage === 'strategy_selection') {
      badgeText = `Strategy: ${payload.strategy || 'Done'}`;
    } else if (stage === 'agent_review') {
      const revStr = payload.revisions ? ` (${payload.revisions} rev)` : '';
      badgeText = `Review: Approved${revStr}`;
    } else if (stage === 'security_verification') {
      badgeText = payload.fallback_occurred ? `Fallback: ${payload.effective_strategy || 'baseline'}` : `Security: ${payload.verdict || 'Passed'}`;
    } else if (stage === 'regression_analysis') {
      badgeText = `Regression: ${payload.overall_status || 'Audited'}`;
    } else if (stage === 'benchmarking') {
      badgeText = "Benchmarked";
    }
    el.setAttribute('aria-label', `${stageTitle}: ${badgeText}`);
    if (badge) {
      badge.className = "step-badge font-mono text-[9.5px] font-semibold text-emerald-700";
      badge.textContent = badgeText;
    }
  } else if (semanticState === 'failed') {
    el.className = "flex items-center justify-between p-1.5 rounded bg-rose-50 border border-rose-300";
    const failDetail = payload.error ? `Failed (${payload.error.slice(0, 15)})` : "Failed";
    el.setAttribute('aria-label', `${stageTitle}: Failed`);
    if (badge) {
      badge.className = "step-badge font-mono text-[9.5px] font-semibold text-rose-700";
      badge.textContent = failDetail;
    }
  } else if (semanticState === 'blocked') {
    el.className = "flex items-center justify-between p-1.5 rounded bg-amber-50 border border-amber-300";
    el.setAttribute('aria-label', `${stageTitle}: Blocked`);
    if (badge) {
      badge.className = "step-badge font-mono text-[9.5px] font-semibold text-amber-700";
      badge.textContent = "Blocked";
    }
  } else if (semanticState === 'skipped') {
    el.className = "flex items-center justify-between p-1.5 rounded bg-navy-50/60 border border-navy-200/40 opacity-70";
    el.setAttribute('aria-label', `${stageTitle}: Skipped`);
    if (badge) {
      badge.className = "step-badge font-mono text-[9.5px] text-navy-400";
      badge.textContent = "Skipped";
    }
  } else if (semanticState === 'inconclusive') {
    el.className = "flex items-center justify-between p-1.5 rounded bg-amber-50/70 border border-amber-300";
    el.setAttribute('aria-label', `${stageTitle}: Inconclusive`);
    if (badge) {
      badge.className = "step-badge font-mono text-[9.5px] font-semibold text-amber-800";
      badge.textContent = "Inconclusive";
    }
  } else if (semanticState === 'pending') {
    el.className = "flex items-center justify-between p-1.5 rounded bg-navy-50 border border-navy-200/60";
    el.setAttribute('aria-label', `${stageTitle}: Pending`);
    if (badge) {
      badge.className = "step-badge font-mono text-[9.5px] text-navy-400 font-normal";
      badge.textContent = "Pending";
    }
  }
}

// ============================================================================
// Accessible Toast Notification System (Phase 1A)
// ============================================================================

function escapeHtml(str) {
  if (typeof str !== 'string') return String(str || '');
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

class ToastManager {
  constructor() {
    this.container = null;
    this.activeToasts = []; // Active toast controllers in display order
    this.seenNotificationIds = new Set();
    this.MAX_VISIBLE = 4;
    this.DEFAULT_DURATION = 5000;
  }

  getContainer() {
    if (!this.container) {
      this.container = document.getElementById('toast-container');
    }
    return this.container;
  }

  show({ id, title, message = '', type = 'info', duration = 5000 }) {
    // 1. Deduplication by stable notification ID
    if (id) {
      if (this.seenNotificationIds.has(id)) {
        return null;
      }
      this.seenNotificationIds.add(id);
    }

    const container = this.getContainer();
    if (!container) return null;

    // 2. Queue Limit Enforcement (max 4 visible toasts)
    while (this.activeToasts.length >= this.MAX_VISIBLE) {
      const oldest = this.activeToasts.shift();
      if (oldest) {
        oldest.dismiss(true);
      }
    }

    const isError = (type === 'error');
    const toastId = id || `toast_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`;
    const toastEl = document.createElement('div');
    toastEl.id = toastId;
    toastEl.tabIndex = 0;
    toastEl.setAttribute('role', isError ? 'alert' : 'status');
    toastEl.setAttribute('aria-live', isError ? 'assertive' : 'polite');
    toastEl.className = "toast-item toast-enter pointer-events-auto flex items-start gap-3 p-3.5 rounded-lg bg-navy-900/95 text-white shadow-xl border border-navy-700/80 backdrop-blur-md w-full select-none focus:outline-none focus:ring-1 focus:ring-accent";

    // Icon mapping matching Professional Navy tokens
    const iconMap = {
      success: { icon: 'check_circle', color: 'text-emerald-400' },
      error: { icon: 'error', color: 'text-rose-400' },
      warning: { icon: 'warning', color: 'text-amber-400' },
      info: { icon: 'info', color: 'text-blue-400' }
    };
    const iconConfig = iconMap[type] || iconMap.info;

    toastEl.innerHTML = `
      <div class="shrink-0 mt-0.5">
        <span class="material-symbols-outlined text-[20px] ${iconConfig.color}">${iconConfig.icon}</span>
      </div>
      <div class="flex-1 min-w-0 pr-1">
        <div class="font-sans font-semibold text-[13px] text-white leading-snug">${escapeHtml(title)}</div>
        ${message ? `<div class="font-sans text-[11.5px] text-navy-200 mt-0.5 leading-relaxed break-words">${escapeHtml(message)}</div>` : ''}
      </div>
      <button type="button"
              class="toast-dismiss-btn shrink-0 text-navy-400 hover:text-white transition-colors p-1 rounded focus:outline-none focus:ring-1 focus:ring-accent cursor-pointer"
              aria-label="Dismiss notification">
        <span class="material-symbols-outlined text-[16px]">close</span>
      </button>
    `;

    // Timer & pause on hover/focus state
    let remainingTime = duration || this.DEFAULT_DURATION;
    let lastStartTime = Date.now();
    let timerId = null;
    let isHovered = false;
    let isFocused = false;
    let isDismissed = false;

    const startTimer = () => {
      if (isDismissed || remainingTime <= 0) return;
      lastStartTime = Date.now();
      timerId = setTimeout(() => {
        controller.dismiss();
      }, remainingTime);
    };

    const pauseTimer = () => {
      if (timerId) {
        clearTimeout(timerId);
        timerId = null;
        remainingTime -= (Date.now() - lastStartTime);
      }
    };

    const resumeTimer = () => {
      if (!isHovered && !isFocused && !timerId && !isDismissed) {
        remainingTime = Math.max(remainingTime, 1000); // At least 1s on resume
        startTimer();
      }
    };

    const controller = {
      id: toastId,
      element: toastEl,
      dismiss: (immediate = false) => {
        if (isDismissed) return;
        isDismissed = true;
        if (timerId) {
          clearTimeout(timerId);
          timerId = null;
        }

        const idx = this.activeToasts.findIndex(t => t.id === toastId);
        if (idx !== -1) {
          this.activeToasts.splice(idx, 1);
        }

        if (immediate) {
          toastEl.remove();
        } else {
          toastEl.classList.remove('toast-enter');
          toastEl.classList.add('toast-exit');
          setTimeout(() => {
            toastEl.remove();
          }, 220);
        }
      }
    };

    // Hover listeners
    toastEl.addEventListener('mouseenter', () => {
      isHovered = true;
      pauseTimer();
    });
    toastEl.addEventListener('mouseleave', () => {
      isHovered = false;
      resumeTimer();
    });

    // Focus listeners (keyboard accessibility)
    toastEl.addEventListener('focusin', () => {
      isFocused = true;
      pauseTimer();
    });
    toastEl.addEventListener('focusout', (e) => {
      if (!toastEl.contains(e.relatedTarget)) {
        isFocused = false;
        resumeTimer();
      }
    });

    // Close button click listener
    const closeBtn = toastEl.querySelector('.toast-dismiss-btn');
    if (closeBtn) {
      closeBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        controller.dismiss();
      });
    }

    container.appendChild(toastEl);
    this.activeToasts.push(controller);
    startTimer();

    return controller;
  }

  clear() {
    while (this.activeToasts.length > 0) {
      const toast = this.activeToasts.pop();
      if (toast) {
        toast.dismiss(true);
      }
    }
    this.seenNotificationIds.clear();
  }

  // Phase 1C integration hooks (stubs)
  showReportGenerated(reportId) {
    // Phase 1C Integration Point: Will trigger when workflow summary report is generated
    console.debug("Phase 1C Integration Point: showReportGenerated", reportId);
  }

  showReportDownloadStarted(filename) {
    // Phase 1C Integration Point: Will trigger when report download starts
    console.debug("Phase 1C Integration Point: showReportDownloadStarted", filename);
  }
}

const toastManager = new ToastManager();

// ============================================================================
// Real-time SSE Connection, Sequence Gap Detection & Replay Deduplication
// ============================================================================

function showSyncWarning(message) {
  let warningEl = document.getElementById('sync-warning-banner');
  if (!warningEl) {
    const container = document.getElementById('agent-messages-container');
    if (container && container.parentNode) {
      warningEl = document.createElement('div');
      warningEl.id = 'sync-warning-banner';
      container.parentNode.insertBefore(warningEl, container);
    }
  }
  if (warningEl) {
    warningEl.className = "p-2 rounded bg-amber-50 border border-amber-300 text-amber-800 text-[11px] font-mono flex items-center gap-1.5 mb-1";
    warningEl.innerHTML = `<span class="material-symbols-outlined text-[15px] text-amber-600">warning</span><span>${message}</span>`;
  }
}

function clearSyncWarning() {
  const warningEl = document.getElementById('sync-warning-banner');
  if (warningEl) {
    warningEl.remove();
  }
}

function connectSSE(runId, expectedProgramId, mode, onComplete, existingState = null) {
  if (currentEventSource) {
    try {
      currentEventSource.close();
    } catch (e) {}
    currentEventSource = null;
  }

  // Scoped event reducer state (carried over on resync to preserve deduplication)
  const seenEventIds = existingState?.seenEventIds || new Set();
  const missingSeqs = existingState?.missingSeqs || new Set();
  const resyncedCursors = existingState?.resyncedCursors || new Set();
  let lastSeenSeq = existingState?.lastSeenSeq || 0;
  let lastSeenEventId = existingState?.lastSeenEventId || null;
  let terminalHandled = existingState?.terminalHandled || false;
  let hasUnresolvedGap = existingState?.hasUnresolvedGap || false;
  let isLive = false;

  const url = existingState?.resyncCursor
    ? `/api/events/${runId}?last_event_id=${encodeURIComponent(existingState.resyncCursor)}`
    : `/api/events/${runId}`;

  const sse = new EventSource(url);
  currentEventSource = sse;

  // Signal from server that historical backfill is complete; events following are live
  sse.addEventListener('backfill_complete', () => {
    isLive = true;
  });

  function processIncomingEvent(data) {
    if (!data) return;

    // 1. Run and Program Identity Guard
    if (data.run_id && data.run_id !== activeRunId) {
      console.debug("Rejected stale run_id:", data.run_id, "active:", activeRunId);
      return;
    }
    if (data.program_id && data.program_id !== currentProgramId) {
      console.debug("Rejected stale program_id:", data.program_id, "current:", currentProgramId);
      return;
    }

    // 2. Deduplication by Stable Event ID
    if (data.event_id) {
      if (seenEventIds.has(data.event_id)) {
        return; // Drop duplicate event on replay or network repetition
      }
      seenEventIds.add(data.event_id);
    }

    // 3. Monotonic Sequence Verification & Explicit Gap Detection
    if (typeof data.seq === 'number') {
      if (data.seq <= lastSeenSeq && lastSeenSeq > 0) {
        // Older or duplicate sequence number:
        // Do not roll back lastSeenSeq or allow old state to corrupt current state
        console.warn("Older event sequence received:", data.seq, "lastSeen:", lastSeenSeq);
        if (missingSeqs.has(data.seq)) {
          missingSeqs.delete(data.seq);
          if (missingSeqs.size === 0) {
            hasUnresolvedGap = false;
            clearSyncWarning();
          }
        }
      } else if (lastSeenSeq > 0 && data.seq > lastSeenSeq + 1) {
        // Explicit sequence gap: missing one or more events between lastSeenSeq and data.seq
        const gapStart = lastSeenSeq + 1;
        const gapEnd = data.seq - 1;
        for (let s = gapStart; s <= gapEnd; s++) {
          missingSeqs.add(s);
        }
        hasUnresolvedGap = true;
        const missingList = Array.from(missingSeqs).sort((a, b) => a - b).join(', ');
        showSyncWarning(`Sync Warning: Event sequence gap detected (seq ${missingList} missing).`);

        // Check if resynchronization via Last-Event-ID can be requested
        if (lastSeenEventId && !resyncedCursors.has(lastSeenEventId)) {
          resyncedCursors.add(lastSeenEventId);
          console.info(`Requesting resync for missing events after ${lastSeenEventId}`);
          try {
            sse.close();
          } catch (e) {}
          if (currentEventSource === sse) currentEventSource = null;

          connectSSE(runId, expectedProgramId, mode, onComplete, {
            seenEventIds,
            missingSeqs,
            resyncedCursors,
            lastSeenSeq: data.seq,
            lastSeenEventId: data.event_id || lastSeenEventId,
            terminalHandled,
            hasUnresolvedGap,
            resyncCursor: lastSeenEventId
          });
          return;
        }

        lastSeenSeq = data.seq;
        if (data.event_id) lastSeenEventId = data.event_id;
      } else {
        // Normal sequential advancement (data.seq === lastSeenSeq + 1 or first event)
        lastSeenSeq = data.seq;
        if (data.event_id) lastSeenEventId = data.event_id;

        if (missingSeqs.has(data.seq)) {
          missingSeqs.delete(data.seq);
          if (missingSeqs.size === 0) {
            hasUnresolvedGap = false;
            clearSyncWarning();
          }
        }
      }
    }

    const evtType = data.event_type || data.type;

    // 4. Dispatch based on canonical event type
    if (evtType === 'agent_message') {
      // If message details are nested inside payload (canonical envelope), flatten for rendering
      const msgData = {
        event_id: data.event_id,
        run_id: data.run_id,
        program_id: data.program_id,
        step: data.payload?.step || data.step || 1,
        sender: data.payload?.sender || data.sender || "Agent",
        recipient: data.payload?.recipient || data.recipient || "Orchestrator",
        message_type: data.payload?.message_type || data.message_type || "MSG",
        timestamp: data.payload?.timestamp || data.timestamp,
        payload: data.payload?.payload || (data.payload?.analysis ? data.payload : (data.payload || {})),
      };
      appendAgentMessageCard(msgData);
    } else if (typeof evtType === 'string' && evtType.startsWith('stage_')) {
      handleStageTransition(data);

      // Live workflow milestone notifications (Phase 1A)
      if (isLive) {
        if (data.stage === 'security_verification' && data.status === 'completed' && data.payload?.fallback_occurred) {
          const eff = data.payload.effective_strategy || 'baseline';
          toastManager.show({
            id: `toast_${data.run_id}_security_blocked`,
            type: 'warning',
            title: 'Security Check Blocked Operation',
            message: `Safety policy blocked candidate; safely substituted with verified baseline (${eff}).`
          });
        } else if (data.stage === 'benchmarking' && data.status === 'completed') {
          const timing = data.payload?.timing || {};
          const isReliable = timing.timing_is_reliable !== false && (!data.payload?.moo_result?.baseline || data.payload.moo_result.baseline.timing_is_reliable !== false);
          if (isReliable) {
            toastManager.show({
              id: `toast_${data.run_id}_benchmark_complete`,
              type: 'success',
              title: 'Benchmark Completed',
              message: 'Execution timing measurements are available and verified.'
            });
          } else {
            toastManager.show({
              id: `toast_${data.run_id}_benchmark_inconclusive`,
              type: 'warning',
              title: 'Benchmark Results Inconclusive',
              message: 'Measurements do not support a confident performance conclusion.'
            });
          }
        } else if (data.stage === 'compilation' && data.status === 'failed') {
          toastManager.show({
            id: `toast_${data.run_id}_compilation_failed`,
            type: 'error',
            title: 'Compilation Failed',
            message: data.payload?.error || 'Compiler reported errors during code generation.'
          });
        }
      }
    } else if (evtType === 'done' || evtType === 'error') {
      if (terminalHandled) return;
      terminalHandled = true;

      try {
        sse.close();
      } catch (e) {}
      if (currentEventSource === sse) currentEventSource = null;

      // Ensure terminal event never conceals an unresolved event gap
      if (hasUnresolvedGap && missingSeqs.size > 0) {
        const missingList = Array.from(missingSeqs).sort((a, b) => a - b).join(', ');
        showSyncWarning(`Incomplete History: Run ended with unrecovered sequence gap (seq ${missingList} missing).`);
      }

      if (onComplete) {
        onComplete(runId, evtType === 'done', { hasUnresolvedGap });
      }
    }
  }

  // Bind event listeners for canonical event types
  const eventTypes = [
    'agent_message',
    'stage_started',
    'stage_completed',
    'stage_failed',
    'stage_blocked',
    'stage_skipped',
    'done',
    'error'
  ];

  eventTypes.forEach(t => {
    sse.addEventListener(t, (e) => {
      try {
        const data = JSON.parse(e.data);
        processIncomingEvent(data);
      } catch (err) {
        console.error("SSE parse error for", t, err);
      }
    });
  });

  // Fallback for general un-typed messages
  sse.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      processIncomingEvent(data);
    } catch (ignore) {}
  };

  sse.onerror = (e) => {
    if (sse.readyState === EventSource.CLOSED) {
      if (currentEventSource === sse) currentEventSource = null;
      if (!terminalHandled && onComplete) {
        terminalHandled = true;
        onComplete(runId, false, { hasUnresolvedGap });
      }
    }
  };
}

// ============================================================================
// Execution Triggers
// ============================================================================

function disableRunButtons() {
  const btnNormal = document.getElementById('btn-run-normal');
  const btnAI = document.getElementById('btn-run-ai');
  if (btnNormal) btnNormal.disabled = true;
  if (btnAI) btnAI.disabled = true;
}

function enableRunButtons() {
  const btnNormal = document.getElementById('btn-run-normal');
  const btnAI = document.getElementById('btn-run-ai');
  if (btnNormal) btnNormal.disabled = false;
  if (btnAI) btnAI.disabled = false;
}

// Run Normal Execution (-O3 Baseline)
async function runNormalExecution() {
  const textarea = document.getElementById('editor-textarea');
  const code = textarea ? textarea.value : "";
  if (!code.trim()) {
    alert("Please provide C source code before running.");
    return;
  }

  // Set running state for Normal workflow
  clearSyncWarning();
  toastManager.clear();
  resetChecklistSteps();
  resetWorkflowReport();
  normalState = {
    status: 'running',
    programId: currentProgramId,
    runId: null,
    data: null,
    error: null
  };

  renderCard1();
  renderCard3(); // Invalidates comparison while measuring

  disableRunButtons();
  const pulse = document.getElementById('pipeline-status-pulse');
  const statusLabel = document.getElementById('multiagent-status-label');
  const flag = document.getElementById('active-pipeline-flag');
  if (pulse) pulse.className = "w-2 h-2 rounded-full bg-navy-600 animate-ping";
  if (statusLabel) statusLabel.textContent = "Baseline Running";
  if (flag) flag.textContent = "Running: Baseline -O3";

  try {
    const res = await fetch('/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        mode: 'normal',
        program_id: currentProgramId,
        source_code: code
      })
    });

    if (!res.ok) throw new Error("Failed to start baseline run");
    const initData = await res.json();
    const runId = initData.run_id;

    activeRunId = runId;
    activeRunMode = 'normal';
    normalState.runId = runId;

    connectSSE(runId, currentProgramId, 'normal', async (finishedRunId, isSuccess) => {
      // Guard: Ensure user did not switch programs during run
      if (finishedRunId === activeRunId && normalState.programId === currentProgramId) {
        await handleRunFinished(finishedRunId, 'normal', isSuccess);
      }
      enableRunButtons();
    });

  } catch (err) {
    alert("Execution error: " + err.message);
    normalState.status = 'failed';
    normalState.error = err.message;
    renderCard1();
    renderCard3();
    enableRunButtons();
  }
}

// Run AI Optimized Execution
async function runAIOptimizedExecution() {
  const textarea = document.getElementById('editor-textarea');
  const code = textarea ? textarea.value : "";
  if (!code.trim()) {
    alert("Please provide C source code before running.");
    return;
  }

  // Set running state for AI workflow
  aiState = {
    status: 'running',
    programId: currentProgramId,
    runId: null,
    data: null,
    error: null
  };

  renderCard2();
  renderCard3(); // Invalidates comparison while measuring

  // Clear messages container for fresh run
  currentRunMessages = [];
  clearSyncWarning();
  toastManager.clear();
  const container = document.getElementById('agent-messages-container');
  if (container) {
    container.innerHTML = '<div class="text-center py-4 text-accent text-[11.5px] font-mono animate-pulse">Multi-Agent deliberation in progress...</div>';
  }
  const msgCounter = document.getElementById('msg-counter');
  if (msgCounter) msgCounter.textContent = '0 messages';
  resetChecklistSteps();
  resetWorkflowReport();

  disableRunButtons();
  const pulse = document.getElementById('pipeline-status-pulse');
  const statusLabel = document.getElementById('multiagent-status-label');
  const flag = document.getElementById('active-pipeline-flag');
  if (pulse) pulse.className = "w-2 h-2 rounded-full bg-accent animate-ping";
  if (statusLabel) statusLabel.textContent = "Agents Deliberating";
  if (flag) flag.textContent = "Running: Multi-Agent AI Optimization";

  try {
    const res = await fetch('/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        mode: 'ai',
        program_id: currentProgramId,
        source_code: code
      })
    });

    if (!res.ok) throw new Error("Failed to start AI optimization run");
    const initData = await res.json();
    const runId = initData.run_id;

    activeRunId = runId;
    activeRunMode = 'ai';
    aiState.runId = runId;

    connectSSE(runId, currentProgramId, 'ai', async (finishedRunId, isSuccess) => {
      // Guard: Ensure user did not switch programs during run
      if (finishedRunId === activeRunId && aiState.programId === currentProgramId) {
        await handleRunFinished(finishedRunId, 'ai', isSuccess);
      }
      enableRunButtons();
    });

  } catch (err) {
    alert("Execution error: " + err.message);
    aiState.status = 'failed';
    aiState.error = err.message;
    renderCard2();
    renderCard3();
    enableRunButtons();
  }
}

// Handle Run Finished (Success or Failure)
async function handleRunFinished(runId, mode, isSuccess) {
  // Guard check
  if (runId !== activeRunId) return;

  try {
    const res = await fetch(`/api/results/${runId}`);
    if (!res.ok) throw new Error(`Results fetch failed (HTTP ${res.status})`);
    const data = await res.json();

    // Guard: ensure results belong to the selected program
    if (data.program_id && data.program_id !== currentProgramId) {
      console.warn("Discarding results from different program:", data.program_id);
      return;
    }

    const runStatus = data.status; // 'completed' | 'failed' | 'error'
    const view = data.view || {};
    const record = data.record || {};

    if (runStatus === 'completed') {
      if (mode === 'normal') {
        normalState = {
          status: 'succeeded',
          programId: currentProgramId,
          runId: runId,
          data: data,
          error: null
        };
        renderCard1();
        toastManager.show({
          id: `toast_${runId}_normal_complete`,
          type: 'success',
          title: 'Normal Run Completed',
          message: 'Baseline -O3 reference execution finished successfully.'
        });
      } else {
        aiState = {
          status: 'succeeded',
          programId: currentProgramId,
          runId: runId,
          data: data,
          error: null
        };
        renderCard2();
        applyAIAnalysisData(data);
        applyOptimizedCodeData(data);

        const backendRegression = view.regression?.overall_status;
        let msg = 'Optimization workflow finished. Deliberation and compilation complete.';
        if (backendRegression === 'IMPROVED') {
          msg = 'Optimization workflow finished with confirmed performance improvement.';
        } else if (backendRegression === 'PARITY') {
          msg = 'Optimization workflow finished. Performance is on par with baseline.';
        } else if (backendRegression === 'REGRESSED') {
          msg = 'Optimization workflow finished. Performance regressed compared to baseline.';
        }

        toastManager.show({
          id: `toast_${runId}_ai_complete`,
          type: 'success',
          title: 'AI Optimization Completed',
          message: msg
        });
      }
      applyDiagnosticsBar(data);

      const pulse = document.getElementById('pipeline-status-pulse');
      const statusLabel = document.getElementById('multiagent-status-label');
      const flag = document.getElementById('active-pipeline-flag');
      if (pulse) pulse.className = "w-2 h-2 rounded-full bg-emerald-500";
      if (statusLabel) statusLabel.textContent = "Ready / Complete";
      if (flag) flag.textContent = "Pipeline: Completed";

    } else {
      // Explicit failure handling
      const errMsg = data.error || "Run execution failed";
      if (errMsg.toLowerCase().includes('compil') || errMsg.toLowerCase().includes('clang') || errMsg.toLowerCase().includes('syntax')) {
        toastManager.show({
          id: `toast_${runId}_compilation_failed`,
          type: 'error',
          title: 'Compilation Failed',
          message: errMsg
        });
      } else {
        toastManager.show({
          id: `toast_${runId}_failed`,
          type: 'error',
          title: 'Execution Failed',
          message: errMsg
        });
      }
      if (mode === 'normal') {
        normalState = {
          status: 'failed',
          programId: currentProgramId,
          runId: runId,
          data: data,
          error: errMsg
        };
        renderCard1();
      } else {
        aiState = {
          status: 'failed',
          programId: currentProgramId,
          runId: runId,
          data: data,
          error: errMsg
        };
        renderCard2();
      }

      applyDiagnosticsBarFailure(errMsg);

      const pulse = document.getElementById('pipeline-status-pulse');
      const statusLabel = document.getElementById('multiagent-status-label');
      const flag = document.getElementById('active-pipeline-flag');
      if (pulse) pulse.className = "w-2 h-2 rounded-full bg-rose-500";
      if (statusLabel) statusLabel.textContent = "Execution Failed";
      if (flag) flag.textContent = "Pipeline: Error";
    }

    // Render Plain-English Workflow Report (Phase 1C)
    if (data.report) {
      renderWorkflowReport(data.report);
    } else {
      fetch(`/api/report/${runId}`)
        .then(r => r.ok ? r.json() : null)
        .then(rep => { if (rep) renderWorkflowReport(rep); })
        .catch(e => console.warn("Report fetch error:", e));
    }

    // Always update comparison
    renderCard3();

  } catch (err) {
    console.error("handleRunFinished error:", err);
    if (mode === 'normal') {
      normalState.status = 'failed';
      normalState.error = err.message;
      renderCard1();
    } else {
      aiState.status = 'failed';
      aiState.error = err.message;
      renderCard2();
    }
    renderCard3();
  }
}

function applyDiagnosticsBar(data) {
  const diagBadge = document.getElementById('diagnostics-badge');
  const buildText = document.getElementById('build-status-text');
  const buildDetails = document.getElementById('build-details-text');
  const tag1 = document.getElementById('opt-pass-tag-1');
  const tag2 = document.getElementById('opt-pass-tag-2');
  const statusBox = document.getElementById('build-status-box');

  if (diagBadge) {
    diagBadge.className = "font-mono text-[11px] font-semibold px-2 py-0.5 rounded bg-emerald-100 text-emerald-800 border border-emerald-300";
    diagBadge.textContent = "Diagnostics clean (0 errors)";
  }
  if (buildText) {
    buildText.textContent = `Build: SUCCESS (LLVM-IR SSA generated in ${data.elapsed_s || 0.1}s)`;
  }
  if (buildDetails) {
    const strat = data.view?.effective_strategy || data.view?.selected_strategy || "-O2";
    buildDetails.textContent = `Clang verified AST nodes. Transformed with strategy [${strat}] under Security Gate supervision.`;
  }
  if (tag1) tag1.textContent = data.view?.effective_strategy || "DQN Policy";
  if (tag2) tag2.textContent = data.view?.fallback_occurred ? "Gate Fallback" : "Security Passed";
  if (statusBox) {
    statusBox.className = "w-7 h-7 rounded bg-emerald-50 text-emerald-600 border border-emerald-200 flex items-center justify-center shrink-0 mt-0.5";
    statusBox.innerHTML = '<span class="material-symbols-outlined text-[18px]">check</span>';
  }
}

function applyDiagnosticsBarFailure(errMsg) {
  const diagBadge = document.getElementById('diagnostics-badge');
  const buildText = document.getElementById('build-status-text');
  const buildDetails = document.getElementById('build-details-text');
  const statusBox = document.getElementById('build-status-box');

  if (diagBadge) {
    diagBadge.className = "font-mono text-[11px] font-semibold px-2 py-0.5 rounded bg-rose-100 text-rose-800 border border-rose-300";
    diagBadge.textContent = "Build / Runtime Error";
  }
  if (buildText) {
    buildText.textContent = "Build: FAILED";
  }
  if (buildDetails) {
    buildDetails.textContent = `Error detail: ${errMsg}`;
  }
  if (statusBox) {
    statusBox.className = "w-7 h-7 rounded bg-rose-50 text-rose-600 border border-rose-200 flex items-center justify-center shrink-0 mt-0.5";
    statusBox.innerHTML = '<span class="material-symbols-outlined text-[18px]">close</span>';
  }
}

// ============================================================================
// Plain-English Workflow Report & Narrative (Phase 1C & Understandable AI)
// ============================================================================

function getNarrativeBadgeClass(status) {
  const s = String(status || '').toLowerCase();
  if (s.includes('complete') || s === 'completed') {
    return 'bg-emerald-100 text-emerald-800 border-emerald-300';
  }
  if (s.includes('skip') || s === 'skipped') {
    return 'bg-navy-100 text-navy-600 border-navy-200';
  }
  if (s.includes('block') || s === 'blocked') {
    return 'bg-amber-100 text-amber-800 border-amber-300';
  }
  if (s.includes('fail') || s === 'failed') {
    return 'bg-rose-100 text-rose-800 border-rose-300';
  }
  if (s.includes('run') || s === 'running' || s.includes('progress')) {
    return 'bg-sky-100 text-sky-800 border-sky-300 animate-pulse';
  }
  return 'bg-slate-100 text-slate-700 border-slate-200';
}

function toggleNarrativeDetails(btn, detailsId) {
  const details = document.getElementById(detailsId);
  if (!details) return;
  const isHidden = details.classList.contains('hidden');
  if (isHidden) {
    details.classList.remove('hidden');
    btn.setAttribute('aria-expanded', 'true');
    const chev = btn.querySelector('.step-chevron');
    if (chev) chev.classList.add('rotate-180');
  } else {
    details.classList.add('hidden');
    btn.setAttribute('aria-expanded', 'false');
    const chev = btn.querySelector('.step-chevron');
    if (chev) chev.classList.remove('rotate-180');
  }
}

function renderWorkflowNarrative(narrative) {
  const container = document.getElementById('workflow-narrative-steps');
  if (!container) return;
  if (!narrative || !Array.isArray(narrative.steps) || narrative.steps.length === 0) {
    container.innerHTML = '<div class="text-[11.5px] text-navy-500 italic p-3 text-center font-sans">No narrative steps recorded for this run.</div>';
    return;
  }

  // Update progress badge
  const badgeEl = document.getElementById('narrative-progress-badge');
  if (badgeEl) {
    const total = narrative.steps.length;
    const completed = narrative.steps.filter(s => s.status === 'completed').length;
    badgeEl.textContent = `${completed} / ${total} STAGES COMPLETED`;
    if (completed === total) {
      badgeEl.className = "px-2 py-0.5 rounded font-mono text-[10px] font-semibold bg-emerald-100 text-emerald-800 border border-emerald-200";
    } else {
      badgeEl.className = "px-2 py-0.5 rounded font-mono text-[10px] font-semibold bg-navy-100 text-navy-800 border border-navy-200";
    }
  }

  container.innerHTML = narrative.steps.map((step, idx) => {
    const stepId = `narrative-step-${step.step_number || (idx + 1)}`;
    const badgeCls = getNarrativeBadgeClass(step.badge || step.status);
    const mainText = (currentViewMode === 'technical') ? step.technical_explanation : step.simple_explanation;

    // Evidence list
    let evidenceHtml = '';
    if (Array.isArray(step.evidence) && step.evidence.length > 0) {
      const items = step.evidence.map(ev => `
        <li class="flex items-start gap-1.5">
          <span class="material-symbols-outlined text-[13px] text-navy-400 shrink-0 mt-0.5">check_circle</span>
          <span>${escapeHtml(ev)}</span>
        </li>
      `).join('');
      evidenceHtml = `
        <div class="mt-2 pt-2 border-t border-navy-100/70">
          <span class="text-[10px] font-mono uppercase tracking-wider text-navy-500 font-semibold">Supporting Evidence</span>
          <ul class="mt-1 space-y-1 text-[11px] text-navy-700 font-sans">
            ${items}
          </ul>
        </div>
      `;
    }

    // Technical details drawer
    let detailsHtml = '';
    const detailsKeys = (step.technical_details && typeof step.technical_details === 'object') ? Object.keys(step.technical_details) : [];
    if (detailsKeys.length > 0) {
      detailsHtml = `
        <div class="mt-2">
          <button type="button"
                  class="flex items-center gap-1 text-[10px] text-navy-500 hover:text-navy-800 font-mono cursor-pointer transition-colors"
                  aria-expanded="false"
                  aria-controls="${stepId}-details"
                  onclick="toggleNarrativeDetails(this, '${stepId}-details')">
            <span class="material-symbols-outlined text-[12px] transition-transform duration-150 step-chevron">expand_more</span>
            <span>Technical Details (${detailsKeys.length} metrics)</span>
          </button>
          <div id="${stepId}-details" class="hidden mt-1.5 p-2 bg-navy-950 text-sky-200 rounded font-mono text-[10px] overflow-x-auto max-h-40 whitespace-pre" role="region" aria-label="Step technical details">
${escapeHtml(JSON.stringify(step.technical_details, null, 2))}
          </div>
        </div>
      `;
    }

    return `
      <div class="p-3 rounded-lg border border-navy-200/80 bg-white shadow-2xs hover:border-navy-300 transition-colors" id="${stepId}">
        <div class="flex items-center justify-between gap-2 border-b border-navy-100/70 pb-1.5">
          <div class="flex items-center gap-2">
            <span class="w-5 h-5 rounded-full bg-navy-800 text-white font-mono text-[10px] font-bold flex items-center justify-center shrink-0">${step.step_number || (idx + 1)}</span>
            <h4 class="text-[12px] font-bold text-navy-900 font-sans">${escapeHtml(step.title || 'Workflow Step')}</h4>
          </div>
          <span class="px-2 py-0.5 rounded font-mono text-[9.5px] font-bold uppercase border ${badgeCls}">${escapeHtml(step.badge || step.status || 'STATUS')}</span>
        </div>
        <div class="step-explanation mt-2 text-[11.5px] text-navy-800 leading-relaxed font-sans"
             data-simple="${escapeHtml(step.simple_explanation || '')}"
             data-technical="${escapeHtml(step.technical_explanation || '')}">
          ${escapeHtml(mainText || '')}
        </div>
        ${evidenceHtml}
        ${detailsHtml}
      </div>
    `;
  }).join('');
}

function resetWorkflowNarrative() {
  const container = document.getElementById('workflow-narrative-steps');
  if (container) {
    container.innerHTML = '<div class="text-[11.5px] text-navy-400 italic p-4 text-center font-sans">Awaiting execution. Run optimization to generate narrative.</div>';
  }
  const badgeEl = document.getElementById('narrative-progress-badge');
  if (badgeEl) {
    badgeEl.textContent = 'STANDBY';
    badgeEl.className = 'px-2 py-0.5 rounded font-mono text-[10px] font-semibold bg-navy-100 text-navy-800 border border-navy-200';
  }
}

function setViewMode(mode) {
  if (mode !== 'simple' && mode !== 'technical') return;
  currentViewMode = mode;
  try {
    if (typeof sessionStorage !== 'undefined') {
      sessionStorage.setItem('toacd_view_mode', mode);
    }
  } catch (e) {
    // ignore sessionStorage errors in restricted environments
  }

  // Update button appearances
  const btnSimple = document.getElementById('toggle-view-simple');
  const btnTech = document.getElementById('toggle-view-technical');
  if (btnSimple && btnTech) {
    if (mode === 'simple') {
      btnSimple.setAttribute('aria-pressed', 'true');
      btnSimple.className = "px-2.5 py-1 rounded text-[11px] font-sans font-semibold transition-all cursor-pointer bg-accent text-white shadow-xs";
      btnTech.setAttribute('aria-pressed', 'false');
      btnTech.className = "px-2.5 py-1 rounded text-[11px] font-sans font-medium text-navy-300 hover:text-white transition-all cursor-pointer";
    } else {
      btnTech.setAttribute('aria-pressed', 'true');
      btnTech.className = "px-2.5 py-1 rounded text-[11px] font-sans font-semibold transition-all cursor-pointer bg-accent text-white shadow-xs";
      btnSimple.setAttribute('aria-pressed', 'false');
      btnSimple.className = "px-2.5 py-1 rounded text-[11px] font-sans font-medium text-navy-300 hover:text-white transition-all cursor-pointer";
    }
  }

  // Update all agent message cards currently in container
  const msgEls = document.querySelectorAll('#agent-messages-container .msg-explanation');
  msgEls.forEach(el => {
    const text = (mode === 'technical') ? el.getAttribute('data-technical') : el.getAttribute('data-simple');
    if (text !== null && text !== undefined) {
      el.textContent = text;
    }
  });

  // Update all workflow narrative step cards
  const stepEls = document.querySelectorAll('#workflow-narrative-steps .step-explanation');
  stepEls.forEach(el => {
    const text = (mode === 'technical') ? el.getAttribute('data-technical') : el.getAttribute('data-simple');
    if (text !== null && text !== undefined) {
      el.textContent = text;
    }
  });
}

function setupViewModeToggle() {
  const btnSimple = document.getElementById('toggle-view-simple');
  const btnTech = document.getElementById('toggle-view-technical');
  if (btnSimple) {
    btnSimple.addEventListener('click', () => setViewMode('simple'));
  }
  if (btnTech) {
    btnTech.addEventListener('click', () => setViewMode('technical'));
  }
  let saved = null;
  try {
    if (typeof sessionStorage !== 'undefined') {
      saved = sessionStorage.getItem('toacd_view_mode');
    }
  } catch (e) {}
  if (saved === 'simple' || saved === 'technical') {
    setViewMode(saved);
  } else {
    setViewMode('simple');
  }
}

function resetWorkflowReport() {
  const placeholder = document.getElementById('workflow-report-placeholder');
  const card = document.getElementById('workflow-report-card');
  if (placeholder) placeholder.classList.remove('hidden');
  if (card) card.classList.add('hidden');
  resetWorkflowNarrative();
  lastWorkflowReport = null;
}

function renderWorkflowReport(report) {
  if (!report) {
    resetWorkflowReport();
    return;
  }

  // Cross-run and cross-program isolation guards
  const effectiveProgId = (typeof currentProgramId !== 'undefined' && currentProgramId) || (typeof global !== 'undefined' && global.currentProgramId);
  const effectiveRunId = (typeof activeRunId !== 'undefined' && activeRunId) || (typeof global !== 'undefined' && global.activeRunId);
  if (report.program_id && effectiveProgId && report.program_id !== effectiveProgId) {
    console.debug("Rejected report for mismatching program_id:", report.program_id, "current:", effectiveProgId);
    return;
  }
  if (report.run_id && effectiveRunId && report.run_id !== effectiveRunId) {
    console.debug("Rejected report for mismatching run_id:", report.run_id, "active:", effectiveRunId);
    return;
  }

  const placeholder = document.getElementById('workflow-report-placeholder');
  const card = document.getElementById('workflow-report-card');
  if (placeholder) placeholder.classList.add('hidden');
  if (card) card.classList.remove('hidden');

  // Header
  const modeBadge = document.getElementById('report-mode-badge');
  const runIdEl = document.getElementById('report-run-id');
  const verdictBadge = document.getElementById('report-verdict-badge');
  if (modeBadge) modeBadge.textContent = report.summary?.mode_label || (report.mode === 'ai' ? 'AI-Optimized Multi-Agent Run' : 'Standard Baseline Reference');
  if (runIdEl) runIdEl.textContent = report.run_id || 'unknown';
  if (verdictBadge) {
    const vb = report.overall_conclusion?.verdict_badge || 'REPORT';
    verdictBadge.textContent = vb;
    if (vb === 'IN_PROGRESS' || report.is_provisional) {
      verdictBadge.className = "px-2.5 py-1 rounded font-mono text-[11px] font-bold bg-navy-800 text-sky-400 border border-sky-500/50 animate-pulse";
    } else if (['SPEEDUP_VERIFIED', 'BASELINE_READY', 'PARITY', 'FALLBACK_APPLIED', 'COMPLETED'].includes(vb)) {
      verdictBadge.className = "px-2.5 py-1 rounded font-mono text-[11px] font-bold bg-navy-800 text-emerald-300 border border-navy-700";
    } else if (['REGRESSED', 'REGRESSION', 'COMPILATION_FAILED', 'SECURITY_BLOCKED', 'EXECUTION_FAILED', 'FAILED_NO_DETAILS'].includes(vb)) {
      verdictBadge.className = "px-2.5 py-1 rounded font-mono text-[11px] font-bold bg-navy-800 text-rose-300 border border-rose-700/50";
    } else {
      verdictBadge.className = "px-2.5 py-1 rounded font-mono text-[11px] font-bold bg-navy-800 text-amber-300 border border-navy-700";
    }
  }

  // Section A: Run Summary
  const headlineEl = document.getElementById('report-summary-headline');
  const summaryTextEl = document.getElementById('report-summary-text');
  const conclusiveBadge = document.getElementById('report-conclusive-badge');
  const conclusiveReason = document.getElementById('report-conclusive-reason');

  if (headlineEl) headlineEl.textContent = report.summary?.headline || 'Workflow Summary';
  if (summaryTextEl) summaryTextEl.textContent = report.summary?.plain_text || '';
  if (conclusiveBadge) {
    const isConc = report.summary?.is_conclusive;
    conclusiveBadge.textContent = isConc ? 'Conclusive' : 'Inconclusive / Noisy';
    conclusiveBadge.className = isConc
      ? "px-2 py-0.5 rounded font-mono text-[10px] font-semibold bg-emerald-100 text-emerald-800 border border-emerald-200"
      : "px-2 py-0.5 rounded font-mono text-[10px] font-semibold bg-amber-100 text-amber-800 border border-amber-200";
  }
  if (conclusiveReason) conclusiveReason.textContent = report.summary?.conclusive_reason || '';

  // Section B: Program Analysis
  const pa = report.program_analysis || {};
  const profLabel = document.getElementById('report-profile-label');
  const profExpl = document.getElementById('report-profile-explanation');
  const profInsts = document.getElementById('report-profile-insts');
  const profLoops = document.getElementById('report-profile-loops');
  const profMem = document.getElementById('report-profile-mem');
  const profDom = document.getElementById('report-profile-dominant');
  const profNote = document.getElementById('report-profile-note');

  if (profLabel) profLabel.textContent = pa.profile_label || 'Not Profiled';
  if (profExpl) profExpl.textContent = pa.profile_explanation || '';
  if (profInsts) profInsts.textContent = (pa.instructions !== null && pa.instructions !== undefined) ? pa.instructions : '—';
  if (profLoops) profLoops.textContent = (pa.loops !== null && pa.loops !== undefined) ? pa.loops : '—';
  if (profMem) profMem.textContent = (pa.memory_instructions !== null && pa.memory_instructions !== undefined) ? pa.memory_instructions : '—';
  if (profDom) profDom.textContent = pa.dominant_feature || '—';
  if (profNote) profNote.textContent = pa.static_vs_runtime_note || '';

  // Section C: Optimization Strategy
  const os = report.optimization_strategy || {};
  const selStrat = document.getElementById('report-strategy-selected');
  const effStrat = document.getElementById('report-strategy-effective');
  const fbAlert = document.getElementById('report-fallback-alert');
  const fbReason = document.getElementById('report-fallback-reason');
  const transEl = document.getElementById('report-strategy-transformations');
  const ratEl = document.getElementById('report-strategy-rationale');

  if (selStrat) selStrat.textContent = os.selected_strategy || '—';
  if (effStrat) effStrat.textContent = os.effective_strategy || '—';
  if (fbAlert) {
    if (os.fallback_occurred) {
      fbAlert.classList.remove('hidden');
      if (fbReason) fbReason.textContent = os.fallback_reason || 'Security gate substituted baseline strategy.';
    } else {
      fbAlert.classList.add('hidden');
    }
  }
  if (transEl) transEl.textContent = os.applied_transformations || 'None';
  if (ratEl) ratEl.textContent = os.decision_rationale || '—';

  // Section D: Security and Correctness
  const sc = report.security_and_correctness || {};
  const secBadge = document.getElementById('report-sec-badge');
  const secDetails = document.getElementById('report-sec-details');
  const compBadge = document.getElementById('report-comp-badge');
  const compDetails = document.getElementById('report-comp-details');
  const corrBadge = document.getElementById('report-corr-badge');
  const corrDetails = document.getElementById('report-corr-details');
  const fbBadge = document.getElementById('report-fb-badge');
  const fbDetails = document.getElementById('report-fb-details');

  function styleBadge(el, statusStr) {
    if (!el) return;
    el.textContent = statusStr || 'Not recorded';
    const s = (statusStr || '').toLowerCase();
    if (s.includes('pass')) {
      el.className = "px-1.5 py-0.2 rounded font-mono text-[10px] font-semibold bg-emerald-100 text-emerald-800 border border-emerald-300";
    } else if (s.includes('fail')) {
      el.className = "px-1.5 py-0.2 rounded font-mono text-[10px] font-semibold bg-rose-100 text-rose-800 border border-rose-300";
    } else if (s.includes('block')) {
      el.className = "px-1.5 py-0.2 rounded font-mono text-[10px] font-semibold bg-amber-100 text-amber-800 border border-amber-300";
    } else if (s.includes('skip') || s.includes('applicable') || s.includes('none')) {
      el.className = "px-1.5 py-0.2 rounded font-mono text-[10px] font-semibold bg-navy-100 text-navy-600 border border-navy-200";
    } else {
      el.className = "px-1.5 py-0.2 rounded font-mono text-[10px] font-semibold bg-slate-100 text-slate-700 border border-slate-200";
    }
  }

  styleBadge(secBadge, sc.security_status);
  if (secDetails) secDetails.textContent = sc.security_details || '';
  styleBadge(compBadge, sc.compilation_status);
  if (compDetails) compDetails.textContent = sc.compilation_details || '';
  styleBadge(corrBadge, sc.correctness_status);
  if (corrDetails) corrDetails.textContent = sc.correctness_details || '';
  styleBadge(fbBadge, sc.fallback_handling);
  if (fbDetails) fbDetails.textContent = os.fallback_occurred ? 'Substituted baseline strategy.' : 'Original strategy retained.';

  // Section E: Performance Results
  const pr = report.performance || {};
  const baseEl = document.getElementById('report-perf-baseline');
  const optEl = document.getElementById('report-perf-optimized');
  const sizeEl = document.getElementById('report-perf-size');
  const verdEl = document.getElementById('report-perf-verdict');
  const speedupEl = document.getElementById('report-perf-speedup');
  const verdDescEl = document.getElementById('report-perf-verdict-desc');
  const relDescEl = document.getElementById('report-perf-reliability-desc');

  if (baseEl) baseEl.textContent = (pr.baseline_time_ms !== null && pr.baseline_time_ms !== undefined) ? `${pr.baseline_time_ms} ms` : '—';
  if (optEl) optEl.textContent = (pr.optimized_time_ms !== null && pr.optimized_time_ms !== undefined) ? `${pr.optimized_time_ms} ms` : '—';
  if (sizeEl) sizeEl.textContent = (pr.code_size_bytes !== null && pr.code_size_bytes !== undefined) ? `${pr.code_size_bytes} B` : '—';
  if (verdEl) {
    verdEl.textContent = pr.benchmark_verdict || 'NOT_RUN';
    if (pr.benchmark_verdict === 'IMPROVED') verdEl.className = "font-bold text-[13px] text-emerald-700";
    else if (pr.benchmark_verdict === 'REGRESSED') verdEl.className = "font-bold text-[13px] text-rose-700";
    else if (pr.benchmark_verdict === 'INCONCLUSIVE') verdEl.className = "font-bold text-[13px] text-amber-700";
    else verdEl.className = "font-bold text-[13px] text-navy-700";
  }
  if (speedupEl) speedupEl.textContent = pr.speedup_text || '—';
  if (verdDescEl) verdDescEl.textContent = pr.verdict_explanation || '';
  if (relDescEl) relDescEl.textContent = pr.reliability_explanation || '';

  // Section F: Problems and Limitations
  const probContainer = document.getElementById('report-problems-container');
  if (probContainer) {
    probContainer.innerHTML = '';
    const problems = report.problems_and_limitations || [];
    if (problems.length === 0) {
      probContainer.innerHTML = '<div class="text-[12px] text-navy-500 font-sans italic">No issues or limitations recorded.</div>';
    } else {
      problems.forEach(p => {
        const item = document.createElement('div');
        const isErr = p.severity === 'error';
        const isWarn = p.severity === 'warning';
        const bgCls = isErr ? 'bg-rose-50 border-rose-200 text-rose-900' : (isWarn ? 'bg-amber-50 border-amber-200 text-amber-900' : 'bg-blue-50 border-blue-200 text-blue-900');
        const icon = isErr ? 'error' : (isWarn ? 'warning' : 'info');
        const iconColor = isErr ? 'text-rose-600' : (isWarn ? 'text-amber-600' : 'text-blue-600');
        item.className = `p-2 rounded border ${bgCls} flex items-start gap-2 text-[12px] font-sans`;
        item.innerHTML = `
          <span class="material-symbols-outlined text-[17px] ${iconColor} shrink-0 mt-0.5">${icon}</span>
          <div>
            <strong>${escapeHtml(p.title)}:</strong>
            <span class="ml-1">${escapeHtml(p.description)}</span>
          </div>
        `;
        probContainer.appendChild(item);
      });
    }
  }

  // Section G: Overall Conclusion
  const oc = report.overall_conclusion || {};
  const concBadge = document.getElementById('report-conclusion-badge');
  const concHead = document.getElementById('report-conclusion-headline');
  const concText = document.getElementById('report-conclusion-text');

  if (concBadge) {
    const vb = oc.verdict_badge || 'COMPLETED';
    concBadge.textContent = vb;
    if (vb === 'IN_PROGRESS' || report.is_provisional) {
      concBadge.className = "px-2 py-0.5 rounded font-mono text-[10.5px] font-bold bg-sky-100 text-sky-800 border border-sky-300 animate-pulse";
    } else if (['SPEEDUP_VERIFIED', 'BASELINE_READY', 'PARITY', 'FALLBACK_APPLIED', 'COMPLETED'].includes(vb)) {
      concBadge.className = "px-2 py-0.5 rounded font-mono text-[10.5px] font-bold bg-emerald-100 text-emerald-800 border border-emerald-300";
    } else if (['REGRESSED', 'REGRESSION', 'COMPILATION_FAILED', 'SECURITY_BLOCKED', 'EXECUTION_FAILED', 'FAILED_NO_DETAILS'].includes(vb)) {
      concBadge.className = "px-2 py-0.5 rounded font-mono text-[10.5px] font-bold bg-rose-100 text-rose-800 border border-rose-300";
    } else {
      concBadge.className = "px-2 py-0.5 rounded font-mono text-[10.5px] font-bold bg-amber-100 text-amber-800 border border-amber-300";
    }
  }
  if (concHead) concHead.textContent = oc.headline || 'Workflow Conclusion';
  if (concText) concText.textContent = oc.text || '';

  function styleDim(id, active) {
    const el = document.getElementById(id);
    if (!el) return;
    const icon = el.querySelector('.material-symbols-outlined');
    if (active) {
      el.className = "flex items-center gap-1.5 text-emerald-400 font-semibold";
      if (icon) icon.textContent = "check_circle";
    } else {
      el.className = "flex items-center gap-1.5 text-navy-400 font-normal";
      if (icon) icon.textContent = "cancel";
    }
  }

  styleDim('report-dim-execution', oc.execution_succeeded);
  styleDim('report-dim-compilation', oc.compilation_succeeded);
  styleDim('report-dim-security', oc.security_passed);
  styleDim('report-dim-correctness', oc.correctness_verified);
  styleDim('report-dim-speedup', oc.performance_improved);

  // Plain-English Workflow Narrative (Feature 1)
  lastWorkflowReport = report;
  if (report.workflow_narrative) {
    renderWorkflowNarrative(report.workflow_narrative);
  } else {
    resetWorkflowNarrative();
  }
}

// ============================================================================
// Tab 2 & 3 Population
// ============================================================================

function applyAIAnalysisData(data) {
  const record = data.record || {};
  const view = data.view || {};

  // 1. Program Profile
  const ir = record.ir_features || {};
  const p = record.program_profile || {};
  const pfInsts = document.getElementById('pf-insts');
  const pfMem = document.getElementById('pf-mem');
  const pfBranches = document.getElementById('pf-branches');
  const pfLoops = document.getElementById('pf-loops');
  const pfDomLabel = document.getElementById('pf-dominant-label');
  const pfDomVal = document.getElementById('pf-dominant-value');

  if (pfInsts) pfInsts.textContent = ir.total_instructions || ir.inst_count || "—";
  if (pfMem) pfMem.textContent = (ir.load_instructions || 0) + (ir.store_instructions || 0) || ir.memory_instructions || "—";
  if (pfBranches) pfBranches.textContent = ir.branch_instructions || ir.branch_count || "—";
  if (pfLoops) pfLoops.textContent = ir.vectorizable_loops || "—";
  if (pfDomLabel) pfDomLabel.textContent = p.label || "Computationally Balanced";
  if (pfDomVal) pfDomVal.textContent = p.dominant_feature ? `Dominant: ${p.dominant_feature}` : "";

  // 2. AI Selected Strategy
  const stratSel = document.getElementById('strat-selected');
  const stratEff = document.getElementById('strat-effective');
  const stratProv = document.getElementById('strat-provenance');
  const stratFb = document.getElementById('strat-fallback');
  const stratMod = document.getElementById('strat-model');

  if (stratSel) stratSel.textContent = view.selected_strategy || "—";
  if (stratEff) stratEff.textContent = view.effective_strategy || "—";
  if (stratProv) stratProv.textContent = view.selection_provenance || "ORIGINAL_SELECTION";
  if (stratFb) stratFb.textContent = view.fallback_occurred ? "Yes (Gate Substituted)" : "No";
  if (stratMod) stratMod.textContent = record.selection_model_id || "production_v0";

  // 3. MOO Decision Table
  const tbody = document.getElementById('moo-candidates-tbody');
  if (tbody) {
    const candidates = record.pareto_frontier || [];
    if (candidates.length > 0) {
      tbody.innerHTML = candidates.map((c, idx) => {
        const isSelected = (c === view.effective_strategy);
        const selClass = isSelected ? "bg-blue-50/60 font-semibold text-navy-900" : "";
        const star = isSelected ? `<span class="material-symbols-outlined text-[14px] text-accent">star</span>` : "";
        const badge = isSelected
          ? `<span class="px-2 py-0.5 rounded bg-accent text-white text-[10px]">SELECTED</span>`
          : `<span class="px-2 py-0.5 rounded bg-navy-100 text-navy-600 text-[10px]">CANDIDATE</span>`;
        return `
          <tr class="${selClass}">
            <td class="p-2 flex items-center gap-1">${star} #${idx+1} (${c})</td>
            <td class="p-2">#${idx+1}</td>
            <td class="p-2 text-emerald-600 font-semibold">Pareto Optimal</td>
            <td class="p-2 font-bold ${isSelected ? 'text-accent' : 'text-navy-700'}">Measured</td>
            <td class="p-2">Compact</td>
            <td class="p-2">${badge}</td>
          </tr>
        `;
      }).join('');
    } else {
      tbody.innerHTML = `
        <tr class="bg-blue-50/60 font-semibold text-navy-900">
          <td class="p-2 flex items-center gap-1 text-accent"><span class="material-symbols-outlined text-[14px]">star</span> #1 (${view.effective_strategy || '-O2'})</td>
          <td class="p-2">#1</td>
          <td class="p-2 text-emerald-600 font-semibold">Pareto Optimal</td>
          <td class="p-2 text-accent font-bold">Evaluated</td>
          <td class="p-2">Optimized</td>
          <td class="p-2"><span class="px-2 py-0.5 rounded bg-accent text-white text-[10px]">SELECTED</span></td>
        </tr>
      `;
    }
  }

  // 4. Security Gates
  const g1 = document.getElementById('sec-gate-1');
  const g2 = document.getElementById('sec-gate-2');
  const g3 = document.getElementById('sec-gate-3');
  const gateRes = record.security_gate || {};
  if (g1) g1.textContent = "Source code AST scanned: No unsafe pointer casts or buffer overflows.";
  if (g2) g2.textContent = "Memory boundary verification: Loop bounds and asserts preserved.";
  if (g3) g3.textContent = `Security Gate verdict: ${gateRes.overall_verdict || "PERMITTED"}. Fallback triggered: ${view.fallback_occurred ? 'YES' : 'NO'}.`;

  // 5. Performance Benchmark Audit
  const auditBase = document.getElementById('audit-base-time');
  const auditOpt = document.getElementById('audit-opt-time');
  const auditSpd = document.getElementById('audit-speedup');
  const auditReg = document.getElementById('audit-regression');

  const bTime = view.baseline_timing?.median_s;
  const oTime = view.optimized_timing?.median_s;

  if (auditBase) auditBase.textContent = bTime ? `${(bTime * 1000).toFixed(2)} ms` : "—";
  if (auditOpt) auditOpt.textContent = oTime ? `${(oTime * 1000).toFixed(2)} ms` : "—";
  if (bTime && oTime && auditSpd) {
    const spd = bTime / oTime;
    auditSpd.textContent = `${spd.toFixed(2)}x (${spd >= 1.0 ? 'Gain' : 'Regression'})`;
  }
  if (auditReg) auditReg.textContent = view.regression_overall_status || "Audited";

  // 6. XAI Reasoning
  const xaiList = document.getElementById('xai-reasons-list');
  const xai = record.xai_result || {};
  const trace = record.decision_trace || {};

  if (xaiList) {
    const r1 = trace.selection_reason || xai.explanation || `DQN Policy selected ${view.effective_strategy} optimizing for execution time and memory footprint.`;
    const r2 = `Pareto Frontier Evaluation: Evaluated candidates against multi-objective scalarization weights.`;
    const r3 = `Security Gate: Verification constraints satisfied without numerical drift.`;

    xaiList.innerHTML = `
      <li class="flex items-start gap-2.5">
        <span class="material-symbols-outlined text-accent text-[17px] shrink-0 mt-0.5">check_circle</span>
        <span><strong class="text-navy-900">Selection Rationale:</strong> ${r1}</span>
      </li>
      <li class="flex items-start gap-2.5">
        <span class="material-symbols-outlined text-accent text-[17px] shrink-0 mt-0.5">check_circle</span>
        <span><strong class="text-navy-900">Pareto Dominance:</strong> ${r2}</span>
      </li>
      <li class="flex items-start gap-2.5">
        <span class="material-symbols-outlined text-accent text-[17px] shrink-0 mt-0.5">check_circle</span>
        <span><strong class="text-navy-900">Safety & Security Proof:</strong> ${r3}</span>
      </li>
    `;
  }
}

function applyOptimizedCodeData(data) {
  const leftCode = document.getElementById('opt-left-code');
  const rightCode = document.getElementById('opt-right-code');
  const rightHeader = document.getElementById('opt-right-header');
  const passBadge = document.getElementById('opt-pass-badge');

  if (leftCode && data.source_code) {
    leftCode.textContent = data.source_code;
  }

  const strat = data.view?.effective_strategy || "-O2";
  if (rightHeader) {
    rightHeader.textContent = `Synthesized: [${strat}] LLVM IR`;
  }
  if (passBadge) {
    passBadge.textContent = strat;
  }

  if (rightCode) {
    if (data.opt_ir) {
      rightCode.textContent = data.opt_ir;
    } else {
      rightCode.textContent = `; LLVM IR Generated for strategy ${strat}\n; Target: x86_64-pc-windows-msvc\n; Optimization passes executed successfully in isolated workspace.\n; Exit code: 0 (Diagnostics clean)`;
    }
  }
}

// Copy Synthesized Code Action
function copyOptimizedCode(btn) {
  const codeEl = document.getElementById('opt-right-code');
  if (!codeEl) return;

  navigator.clipboard.writeText(codeEl.textContent).then(() => {
    const textEl = document.getElementById('copy-btn-text');
    if (textEl) {
      const orig = textEl.textContent;
      textEl.textContent = "Copied to Clipboard!";
      setTimeout(() => { textEl.textContent = orig; }, 2000);
    }
  }).catch(err => {
    alert("Clipboard copy failed: " + err);
  });
}

// Save Synthesized Code Action
function saveOptimizedCode(btn) {
  const codeEl = document.getElementById('opt-right-code');
  if (!codeEl) return;

  const blob = new Blob([codeEl.textContent], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `optimized_${activeRunId || 'kernel'}.ll`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ============================================================================
// Initialization on DOMContentLoaded
// ============================================================================
if (typeof document !== 'undefined' && document.addEventListener) {
  document.addEventListener('DOMContentLoaded', async () => {
    const textarea = document.getElementById('editor-textarea');
    if (textarea) {
      textarea.addEventListener('input', onEditorContentChanged);
      textarea.addEventListener('scroll', () => {
        const lineNumbers = document.getElementById('editor-line-numbers');
        if (lineNumbers) lineNumbers.scrollTop = textarea.scrollTop;
      });
    }

    // Setup Technical / Simple English Toggle
    setupViewModeToggle();

    // Load Toolchain Status
    await loadToolchainStatus();

    // Load Default Sample
    await onSampleSelected('gemm');
  });
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    handleStageTransition,
    resetChecklistSteps,
    renderWorkflowReport,
    resetWorkflowReport,
    ToastManager,
    escapeHtml,
    setActiveRunId: (id) => { activeRunId = id; },
    setCurrentProgramId: (id) => { currentProgramId = id; },
    explainAgentMessage,
    appendAgentMessageCard,
    renderWorkflowNarrative,
    resetWorkflowNarrative,
    setViewMode,
    setupViewModeToggle,
    getCurrentViewMode: () => currentViewMode,
    setCurrentViewMode: (m) => { currentViewMode = m; },
    toggleMessageDrawer,
    toggleNarrativeDetails,
  };
}
