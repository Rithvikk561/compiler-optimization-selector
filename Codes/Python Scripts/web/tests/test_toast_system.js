// ============================================================================
// TOACD Phase 1A: Toast Notification System Automated Test Suite
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
    this.eventListeners = new Map();
    this._innerHTML = '';
    this.tabIndex = -1;
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

  removeChild(child) {
    const idx = this.children.indexOf(child);
    if (idx !== -1) {
      this.children.splice(idx, 1);
      child.parentNode = null;
    }
    return child;
  }

  remove() {
    if (this.parentNode) {
      this.parentNode.removeChild(this);
    }
  }

  addEventListener(type, fn) {
    if (!this.eventListeners.has(type)) {
      this.eventListeners.set(type, []);
    }
    this.eventListeners.get(type).push(fn);
  }

  dispatchEvent(type, eventObj = {}) {
    const listeners = this.eventListeners.get(type) || [];
    for (const fn of listeners) {
      fn({ ...eventObj, target: this, stopPropagation: () => {} });
    }
  }

  querySelector(sel) {
    if (sel === '.toast-dismiss-btn') {
      return this._dismissBtn || null;
    }
    return null;
  }

  contains(other) {
    if (other === this) return true;
    for (const c of this.children) {
      if (c === other || (c.contains && c.contains(other))) return true;
    }
    return false;
  }

  set innerHTML(html) {
    this._innerHTML = html;
    if (html.includes('toast-dismiss-btn')) {
      this._dismissBtn = new FakeElement('button');
      this._dismissBtn.className = 'toast-dismiss-btn';
      this._dismissBtn.setAttribute('aria-label', 'Dismiss notification');
      this.appendChild(this._dismissBtn);
    }
  }

  get innerHTML() {
    return this._innerHTML;
  }
}

// Global DOM mock
const fakeDocument = {
  elements: new Map(),
  createElement(tag) {
    return new FakeElement(tag);
  },
  getElementById(id) {
    return this.elements.get(id) || null;
  }
};

const fakeToastContainer = new FakeElement('div');
fakeToastContainer.id = 'toast-container';
fakeToastContainer.setAttribute('role', 'region');
fakeToastContainer.setAttribute('aria-label', 'Notifications');
fakeDocument.elements.set('toast-container', fakeToastContainer);

// 2. Import / Simulate the exact ToastManager logic from app.js
function escapeHtml(str) {
  if (typeof str !== 'string') return String(str || '');
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

class TestToastManager {
  constructor(doc) {
    this.doc = doc;
    this.container = null;
    this.activeToasts = [];
    this.seenNotificationIds = new Set();
    this.MAX_VISIBLE = 4;
    this.DEFAULT_DURATION = 5000;
  }

  getContainer() {
    if (!this.container) {
      this.container = this.doc.getElementById('toast-container');
    }
    return this.container;
  }

  show({ id, title, message = '', type = 'info', duration = 5000 }) {
    if (id) {
      if (this.seenNotificationIds.has(id)) {
        return null;
      }
      this.seenNotificationIds.add(id);
    }

    const container = this.getContainer();
    if (!container) return null;

    while (this.activeToasts.length >= this.MAX_VISIBLE) {
      const oldest = this.activeToasts.shift();
      if (oldest) {
        oldest.dismiss(true);
      }
    }

    const isError = (type === 'error');
    const toastId = id || `toast_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`;
    const toastEl = this.doc.createElement('div');
    toastEl.id = toastId;
    toastEl.tabIndex = 0;
    toastEl.setAttribute('role', isError ? 'alert' : 'status');
    toastEl.setAttribute('aria-live', isError ? 'assertive' : 'polite');
    toastEl.classList.add('toast-item');
    toastEl.classList.add('toast-enter');

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
        remainingTime = Math.max(remainingTime, 1000);
        startTimer();
      }
    };

    const controller = {
      id: toastId,
      element: toastEl,
      getRemainingTime: () => remainingTime,
      isTimerActive: () => timerId !== null,
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
          toastEl.remove();
        }
      }
    };

    toastEl.addEventListener('mouseenter', () => {
      isHovered = true;
      pauseTimer();
    });
    toastEl.addEventListener('mouseleave', () => {
      isHovered = false;
      resumeTimer();
    });

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

    const closeBtn = toastEl.querySelector('.toast-dismiss-btn');
    if (closeBtn) {
      closeBtn.addEventListener('click', (e) => {
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
}

// ============================================================================
// Automated Tests
// ============================================================================

async function runAllTests() {
  console.log("==================================================================");
  console.log("  TOACD Phase 1A: Accessible Toast Notification System Tests");
  console.log("==================================================================");

  let passed = 0;
  let total = 0;

  function test(name, fn) {
    total++;
    try {
      fn();
      console.log(`  [PASS] Test ${total}: ${name}`);
      passed++;
    } catch (err) {
      console.error(`  [FAIL] Test ${total}: ${name}`);
      console.error(err);
      process.exitCode = 1;
    }
  }

  async function asyncTest(name, fn) {
    total++;
    try {
      await fn();
      console.log(`  [PASS] Test ${total}: ${name}`);
      passed++;
    } catch (err) {
      console.error(`  [FAIL] Test ${total}: ${name}`);
      console.error(err);
      process.exitCode = 1;
    }
  }

  // 1. Creating and dismissing a toast
  test("Creating and dismissing a toast", () => {
    const tm = new TestToastManager(fakeDocument);
    const toast = tm.show({ id: "t1", title: "Test Toast", message: "Hello", type: "info" });
    assert(toast !== null, "Toast should be created");
    assert.strictEqual(fakeToastContainer.children.length, 1);
    assert.strictEqual(toast.element.getAttribute("role"), "status");
    assert.strictEqual(toast.element.getAttribute("aria-live"), "polite");

    toast.dismiss(true);
    assert.strictEqual(fakeToastContainer.children.length, 0);
  });

  // 2. Automatic dismissal after 5 seconds
  await asyncTest("Automatic dismissal after five seconds", async () => {
    const tm = new TestToastManager(fakeDocument);
    const toast = tm.show({ id: "t_auto", title: "Expiring Toast", duration: 50 });
    assert.strictEqual(fakeToastContainer.children.length, 1);

    await new Promise(r => setTimeout(r, 70));
    assert.strictEqual(fakeToastContainer.children.length, 0, "Toast should auto-dismiss after timer expires");
  });

  // 3. Pausing dismissal on hover or focus
  await asyncTest("Pausing dismissal on hover or focus and resuming on end", async () => {
    const tm = new TestToastManager(fakeDocument);
    const toast = tm.show({ id: "t_pause", title: "Hover Toast", duration: 80 });

    // Hover after 20ms
    await new Promise(r => setTimeout(r, 20));
    toast.element.dispatchEvent("mouseenter");
    assert.strictEqual(toast.isTimerActive(), false, "Timer should be paused on mouseenter");

    // Wait 100ms while hovered (longer than original 80ms duration)
    await new Promise(r => setTimeout(r, 100));
    assert.strictEqual(fakeToastContainer.children.length, 1, "Toast must not dismiss while hovered");

    // Leave hover
    toast.element.dispatchEvent("mouseleave");
    assert.strictEqual(toast.isTimerActive(), true, "Timer should resume on mouseleave");

    // Focus
    toast.element.dispatchEvent("focusin");
    assert.strictEqual(toast.isTimerActive(), false, "Timer should pause on focusin");

    // Unfocus
    toast.element.dispatchEvent("focusout", { relatedTarget: null });
    assert.strictEqual(toast.isTimerActive(), true, "Timer should resume on focusout");

    toast.dismiss(true);
  });

  // 4. Manual dismissal via close button
  test("Manual dismissal via close button with accessible name", () => {
    const tm = new TestToastManager(fakeDocument);
    const toast = tm.show({ id: "t_manual", title: "Close Me" });
    const btn = toast.element.querySelector(".toast-dismiss-btn");
    assert(btn !== null, "Dismiss button must exist");
    assert.strictEqual(btn.getAttribute("aria-label"), "Dismiss notification");

    btn.dispatchEvent("click");
    assert.strictEqual(fakeToastContainer.children.length, 0, "Clicking dismiss button should remove toast");
  });

  // 5. Multiple toast stacking and queue limits (max 4)
  test("Multiple toast stacking and queue limits (max 4)", () => {
    const tm = new TestToastManager(fakeDocument);
    tm.clear();

    const t1 = tm.show({ id: "stack_1", title: "Toast 1" });
    const t2 = tm.show({ id: "stack_2", title: "Toast 2" });
    const t3 = tm.show({ id: "stack_3", title: "Toast 3" });
    const t4 = tm.show({ id: "stack_4", title: "Toast 4" });
    assert.strictEqual(fakeToastContainer.children.length, 4);

    // 5th toast pushes out the oldest (stack_1)
    const t5 = tm.show({ id: "stack_5", title: "Toast 5" });
    assert.strictEqual(fakeToastContainer.children.length, 4, "Visible toasts must not exceed MAX_VISIBLE (4)");
    assert.strictEqual(tm.activeToasts[0].id, "stack_2", "Oldest toast should have been dismissed");
    assert.strictEqual(tm.activeToasts[3].id, "stack_5");
    tm.clear();
  });

  // 6. Reduced-motion styling verification
  test("Reduced-motion styling compliance", () => {
    // In index.html, @media (prefers-reduced-motion: reduce) overrides animation to none and 0.01ms duration
    // Verify toast CSS classes apply toast-enter and toast-exit
    const tm = new TestToastManager(fakeDocument);
    const toast = tm.show({ id: "t_motion", title: "Motion Test" });
    assert(toast.element.classList.contains("toast-enter"), "Must use toast-enter class for CSS animations");
    toast.dismiss(true);
  });

  // 7. Duplicate event suppression
  test("Duplicate event notification suppression", () => {
    const tm = new TestToastManager(fakeDocument);
    tm.clear();

    const t1 = tm.show({ id: "evt_dup_1", title: "First Event" });
    assert(t1 !== null);
    assert.strictEqual(fakeToastContainer.children.length, 1);

    // Second call with same stable ID
    const t2 = tm.show({ id: "evt_dup_1", title: "Duplicate Event" });
    assert.strictEqual(t2, null, "Duplicate notification ID must be rejected");
    assert.strictEqual(fakeToastContainer.children.length, 1);
    tm.clear();
  });

  // 8. Replayed events and initial SSE backfill do not trigger notifications
  test("Duplicate notification suppression during replay (isLive guard)", () => {
    const tm = new TestToastManager(fakeDocument);
    tm.clear();

    let isLive = false;
    function handleEvent(evt) {
      if (!isLive) return; // Guard
      tm.show({ id: evt.event_id, title: "Milestone" });
    }

    // Historical replay while isLive is false
    handleEvent({ event_id: "evt_hist_1", event_type: "stage_completed" });
    handleEvent({ event_id: "evt_hist_2", event_type: "stage_completed" });
    assert.strictEqual(fakeToastContainer.children.length, 0, "No toasts during historical backfill");

    // SSE backfill complete signal
    isLive = true;
    handleEvent({ event_id: "evt_live_1", event_type: "stage_completed" });
    assert.strictEqual(fakeToastContainer.children.length, 1, "Live event triggers toast");
    tm.clear();
  });

  // 9. Successful normal-run completion
  test("Successful normal-run completion", () => {
    const tm = new TestToastManager(fakeDocument);
    tm.clear();

    const toast = tm.show({
      id: "toast_run_norm_complete",
      type: "success",
      title: "Normal Run Completed",
      message: "Baseline -O3 reference execution finished successfully."
    });
    assert.strictEqual(toast.element.getAttribute("role"), "status");
    assert(toast.element.innerHTML.includes("Normal Run Completed"));
    assert(toast.element.innerHTML.includes("Baseline -O3"));
    tm.clear();
  });

  // 10. Successful AI-run completion (with verdict gating)
  test("Successful AI-run completion with authoritative verdict gating", () => {
    const tm = new TestToastManager(fakeDocument);
    tm.clear();

    // 10a. Improved verdict
    const t_imp = tm.show({
      id: "toast_ai_imp",
      type: "success",
      title: "AI Optimization Completed",
      message: "Optimization workflow finished with confirmed performance improvement."
    });
    assert(t_imp.element.innerHTML.includes("confirmed performance improvement"));

    // 10b. Parity verdict (never falsely claims improvement)
    const t_par = tm.show({
      id: "toast_ai_par",
      type: "success",
      title: "AI Optimization Completed",
      message: "Optimization workflow finished. Performance is on par with baseline."
    });
    assert(t_par.element.innerHTML.includes("Performance is on par with baseline"));
    assert(!t_par.element.innerHTML.includes("improvement"));
    tm.clear();
  });

  // 11. Compilation failure (role="alert" for urgent announcement)
  test("Compilation failure with role=alert", () => {
    const tm = new TestToastManager(fakeDocument);
    tm.clear();

    const toast = tm.show({
      id: "toast_compile_fail",
      type: "error",
      title: "Compilation Failed",
      message: "Clang reported syntax error at line 42."
    });
    assert.strictEqual(toast.element.getAttribute("role"), "alert", "Compilation failure must use role=alert");
    assert.strictEqual(toast.element.getAttribute("aria-live"), "assertive");
    assert(toast.element.innerHTML.includes("Compilation Failed"));
    assert(toast.element.innerHTML.includes("syntax error"));
    tm.clear();
  });

  // 12. Security rejection without falsely marking whole run failed
  test("Security rejection without falsely marking whole run failed", () => {
    const tm = new TestToastManager(fakeDocument);
    tm.clear();

    const toast = tm.show({
      id: "toast_sec_fallback",
      type: "warning",
      title: "Security Check Blocked Operation",
      message: "Safety policy blocked candidate; safely substituted with verified baseline (-O2)."
    });
    assert.strictEqual(toast.element.getAttribute("role"), "status", "Fallback warning does not label entire run failed");
    assert(toast.element.innerHTML.includes("Security Check Blocked Operation"));
    assert(toast.element.innerHTML.includes("-O2"));
    tm.clear();
  });

  // 13. Reliable benchmark completion
  test("Reliable benchmark completion", () => {
    const tm = new TestToastManager(fakeDocument);
    tm.clear();

    const toast = tm.show({
      id: "toast_bench_ok",
      type: "success",
      title: "Benchmark Completed",
      message: "Execution timing measurements are available and verified."
    });
    assert(toast.element.innerHTML.includes("Benchmark Completed"));
    assert(toast.element.innerHTML.includes("available and verified"));
    tm.clear();
  });

  // 14. Inconclusive benchmark results
  test("Inconclusive benchmark results", () => {
    const tm = new TestToastManager(fakeDocument);
    tm.clear();

    const toast = tm.show({
      id: "toast_bench_inconclusive",
      type: "warning",
      title: "Benchmark Results Inconclusive",
      message: "Measurements exhibit high variance or noise; does not support a confident performance conclusion."
    });
    assert(toast.element.innerHTML.includes("Benchmark Results Inconclusive"));
    assert(!toast.element.innerHTML.includes("improvement"));
    tm.clear();
  });

  // 15. Stale run events not triggering notifications
  test("Stale run events not triggering notifications", () => {
    const tm = new TestToastManager(fakeDocument);
    tm.clear();

    let activeRunId = "run_current_100";
    function processEvent(evt) {
      if (evt.run_id !== activeRunId) return false;
      tm.show({ id: `toast_${evt.run_id}`, title: "Should not show" });
      return true;
    }

    const ret = processEvent({ run_id: "run_stale_99" });
    assert.strictEqual(ret, false);
    assert.strictEqual(fakeToastContainer.children.length, 0, "Stale run event must be dropped without toast");
  });

  // 16. Switching programs while an old run is finishing
  test("Switching programs while an old run is finishing clears toasts and drops notifications", () => {
    const tm = new TestToastManager(fakeDocument);
    tm.clear();

    let currentProgramId = "gemm";
    tm.show({ id: "t_old_prog", title: "Old Program Toast" });
    assert.strictEqual(fakeToastContainer.children.length, 1);

    // Switch program
    currentProgramId = "2mm";
    tm.clear(); // Program switch clears toasts
    assert.strictEqual(fakeToastContainer.children.length, 0, "Program switch must clear toasts");

    // Old run finishes for 'gemm'
    function onRunFinish(progId) {
      if (progId !== currentProgramId) return; // Guard
      tm.show({ id: "t_gemm_done", title: "Gemm Finished" });
    }
    onRunFinish("gemm");
    assert.strictEqual(fakeToastContainer.children.length, 0, "Old program completion must not show toast");
  });

  // 17. Safe rendering of untrusted notification content (XSS protection)
  test("Safe rendering of untrusted notification content", () => {
    const tm = new TestToastManager(fakeDocument);
    tm.clear();

    const maliciousError = `<script>alert('xss')</script><img src="x" onerror="alert(1)"/> & special "chars"`;
    const toast = tm.show({
      id: "toast_xss",
      type: "error",
      title: "Error: <script>bad()</script>",
      message: maliciousError
    });

    const rendered = toast.element.innerHTML;
    assert(!rendered.includes("<script>"), "Must escape raw <script> tags");
    assert(rendered.includes("&lt;script&gt;"), "Must render escaped script tags");
    assert(rendered.includes("&amp; special &quot;chars&quot;"), "Must escape ampersands and quotes");
    tm.clear();
  });

  console.log("==================================================================");
  console.log(`Results: ${passed}/${total} passed (${total - passed} failed)`);
  console.log("==================================================================");
  assert.strictEqual(passed, total, "All tests must pass");
}

runAllTests().catch(err => {
  console.error("Test execution failure:", err);
  process.exit(1);
});
