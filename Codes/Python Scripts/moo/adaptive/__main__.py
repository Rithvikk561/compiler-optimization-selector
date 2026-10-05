"""
moo/adaptive/__main__.py — Week 11: CLI entry point for the adaptive learning package.

Usage (from the 'moo' parent directory):
    python -m moo.adaptive [--help]
    python -m moo.adaptive status --store-dir <path>
    python -m moo.adaptive list-candidates --candidate-dir <path>

This is a minimal informational CLI — it does NOT trigger training automatically.
"""

from __future__ import annotations

import json
import os
import sys

_MOO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PS_DIR = os.path.dirname(_MOO_DIR)
if _PS_DIR not in sys.path:
    sys.path.insert(0, _PS_DIR)


def _cmd_status(store_dir: str) -> None:
    from moo.adaptive.storage import ExperienceStore
    store = ExperienceStore(store_dir)
    print(f"Experience Store: {store_dir}")
    print(f"  Record count : {store.record_count}")
    print(f"  Corrupt lines: {store.corrupt_line_count}")
    print(f"  Data file    : {store.data_path}")
    print(f"  Manifest     : {store.manifest_path}")


def _cmd_list_candidates(candidate_dir: str) -> None:
    from moo.adaptive.learner import DQNLearner
    learner = DQNLearner(candidate_dir=candidate_dir)
    candidates = learner.list_candidates()
    if not candidates:
        print(f"No candidate models in: {candidate_dir}")
        return
    print(f"Candidate models in: {candidate_dir}")
    for mvi in candidates:
        print(
            f"  v{mvi.model_version:3d} | {mvi.model_id} | "
            f"experiences={mvi.experience_count} | "
            f"loss={mvi.mean_loss:.4f if mvi.mean_loss is not None else 'N/A'} | "
            f"is_production={mvi.is_production}"
        )


def main(argv: list[str] | None = None) -> None:
    if argv is None:
        argv = sys.argv[1:]

    if not argv or argv[0] in ("-h", "--help"):
        print(
            "Week 11 Adaptive Self-Learning — CLI\n"
            "Usage:\n"
            "  python -m moo.adaptive status --store-dir <path>\n"
            "  python -m moo.adaptive list-candidates --candidate-dir <path>\n"
        )
        return

    cmd = argv[0]
    args = argv[1:]

    def _get_arg(flag: str, default: str) -> str:
        for i, a in enumerate(args):
            if a == flag and i + 1 < len(args):
                return args[i + 1]
        return default

    if cmd == "status":
        store_dir = _get_arg("--store-dir", os.path.join(_MOO_DIR, "adaptive", "experience_store"))
        _cmd_status(store_dir)
    elif cmd == "list-candidates":
        cdir = _get_arg("--candidate-dir", os.path.join(_MOO_DIR, "adaptive", "candidate_models"))
        _cmd_list_candidates(cdir)
    else:
        print(f"Unknown command: {cmd!r}. Use --help for usage.")
        sys.exit(1)


if __name__ == "__main__":
    main()
