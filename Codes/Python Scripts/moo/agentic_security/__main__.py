"""
moo.agentic_security.__main__ — CLI entry point to run attack evaluation suite and print metrics report.
"""

from __future__ import annotations

import sys
from .corpus import CORE_ATTACKS, BENIGN_CASES, STRESS_CASES
from .metrics import compute_metrics


def main() -> None:
    print("=" * 70)
    print("TOACD WEEK 13B — AGENTIC AI SECURITY EVALUATION SUITE")
    print("=" * 70)

    print(f"\nEvaluating Core Attack Corpus ({len(CORE_ATTACKS)} cases) and Benign Corpus ({len(BENIGN_CASES)} cases)...")
    m = compute_metrics(CORE_ATTACKS, BENIGN_CASES)

    print("\n--- Headline Detection & Blocking Metrics ---")
    print(f"  Precision:                 {m.precision:.4f}")
    print(f"  Recall (Detection Rate):   {m.recall:.4f}")
    print(f"  F1 Score:                  {m.f1:.4f}")
    print(f"  False Positive Rate (FPR): {m.fpr:.4f}")
    print(f"  False Negative Rate (FNR): {m.fnr:.4f}")
    print(f"  Attack Blocking Rate:      {m.attack_blocking_rate:.4f}")
    print(f"  Log Completeness:          {m.log_completeness:.4f}")
    print(f"  Risk-Level Agreement:      {m.risk_level_agreement:.4f}")

    print("\n--- Comparative Attack Success Rate (ASR) ---")
    print(f"  Unprotected NaiveExecutor: {m.naive_asr:.4f} ({int(m.naive_asr * 100)}% compromise)")
    print(f"  Protected GuardedExecutor: {m.guarded_asr:.4f} (0% compromise)")

    print("\n--- Latency Performance (ms) ---")
    print(f"  Mean Latency:              {m.mean_latency_ms:.3f} ms")
    print(f"  Median Latency:            {m.median_latency_ms:.3f} ms")
    print(f"  P95 Latency:               {m.p95_latency_ms:.3f} ms")
    print(f"  Max Latency:               {m.max_latency_ms:.3f} ms")

    print("\n--- Stress Cases (Limitations Assessment) ---")
    for sc in STRESS_CASES:
        print(f"  [{sc.case_id}] {sc.name}: {sc.notes}")

    print("\n" + "=" * 70)
    print("EVALUATION COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
