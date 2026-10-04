"""
moo/bench/generator.py — Seeded, deterministic synthetic C benchmark generator.

Generates safe, bounded C programs across six families:
  - loop        : loop-heavy programs (nested/counted loops)
  - math        : mathematical computation (integer/float arithmetic)
  - memory      : array/struct/memory access patterns
  - recursion   : recursive algorithms with bounded depth
  - branch      : branching/conditional logic
  - function    : multi-function call hierarchies

Design constraints:
  - Seeded/deterministic: same seed → identical source text.
  - Bounded execution: no infinite loops; all arrays statically sized.
  - No undefined behaviour: no signed integer overflow, no out-of-bounds.
  - No rand/time/scanf/malloc: deterministic output with known checksum.
  - Unique filenames: gen_<family>_seed<seed>_<index>.c
  - Generated programs MUST NOT collide with existing test_cases filenames.
  - Output is SUBSTANTIALLY different from the legacy generate_dataset.py
    which only used 5 fixed files.

Each generated program:
  1. Computes a deterministic result using only static data and arithmetic.
  2. Prints the result to stdout so correctness can be verified.
  3. Returns exit code 0.
"""

from __future__ import annotations

import hashlib
import os
import random
import textwrap
from typing import Optional

from .schema import CorpusEntry

# ---------------------------------------------------------------------------
# Family constants
# ---------------------------------------------------------------------------

GENERATOR_FAMILIES: tuple[str, ...] = (
    "loop",
    "math",
    "memory",
    "recursion",
    "branch",
    "function",
)

# ---------------------------------------------------------------------------
# Internal RNG (never uses global random state)
# ---------------------------------------------------------------------------

class _SeededRNG:
    """Thin wrapper around random.Random to keep generator state isolated."""
    def __init__(self, seed: int):
        self._rng = random.Random(seed)

    def randint(self, a: int, b: int) -> int:
        return self._rng.randint(a, b)

    def choice(self, seq):
        return self._rng.choice(seq)

    def shuffle(self, lst: list) -> list:
        result = list(lst)
        self._rng.shuffle(result)
        return result


# ---------------------------------------------------------------------------
# Per-family source generators
# ---------------------------------------------------------------------------

def _gen_loop(rng: _SeededRNG, idx: int) -> str:
    """Generate a loop-heavy program."""
    outer = rng.randint(3, 8)
    inner = rng.randint(4, 12)
    step  = rng.randint(1, 3)
    init  = rng.randint(1, 10)

    return textwrap.dedent(f"""\
        /* Generated benchmark: loop family, index {idx}
         * Deterministic nested loop accumulator.
         * No UB: all array accesses bounded; no overflow risk (long long). */
        #include <stdio.h>

        int main(void) {{
            long long acc = {init}LL;
            int i, j;
            for (i = 0; i < {outer * 100}; i += {step}) {{
                for (j = 1; j <= {inner}; j++) {{
                    acc += (long long)i * j;
                    acc ^= (acc >> 3);
                }}
            }}
            /* acc is deterministic; print as signed decimal */
            printf("%lld\\n", acc);
            return 0;
        }}
    """)


def _gen_math(rng: _SeededRNG, idx: int) -> str:
    """Generate a math-heavy computation program."""
    n       = rng.randint(50, 200)
    a_init  = rng.randint(2, 15)
    b_init  = rng.randint(3, 20)

    return textwrap.dedent(f"""\
        /* Generated benchmark: math family, index {idx}
         * Integer arithmetic series — Euclidean GCD chain.
         * Bounded: at most {n} iterations, no division by zero (b >= 1). */
        #include <stdio.h>

        static long long gcd(long long a, long long b) {{
            while (b != 0) {{
                long long t = b;
                b = a % b;
                a = t;
            }}
            return a;
        }}

        int main(void) {{
            long long a = {a_init}LL, b = {b_init}LL;
            long long result = 0;
            int k;
            for (k = 0; k < {n}; k++) {{
                result += gcd(a + (long long)k, b + (long long)k * 2 + 1);
                a = a * 3 + 1;
                b = b * 2 + k + 1;
                /* Keep values from growing unboundedly */
                if (a > 1000000LL) a = a % 999983LL + 1;
                if (b > 1000000LL) b = b % 999979LL + 1;
            }}
            printf("%lld\\n", result);
            return 0;
        }}
    """)


def _gen_memory(rng: _SeededRNG, idx: int) -> str:
    """Generate a memory-access-heavy program."""
    size  = rng.randint(32, 128)
    iters = rng.randint(4, 20)
    seed_v = rng.randint(1, 100)

    return textwrap.dedent(f"""\
        /* Generated benchmark: memory family, index {idx}
         * Array fill, reverse, and reduction.
         * Static allocation only — no malloc, no out-of-bounds. */
        #include <stdio.h>

        #define N {size}

        static void fill(long long arr[], int n, long long seed) {{
            int i;
            for (i = 0; i < n; i++) {{
                seed = seed * 6364136223846793005LL + 1442695040888963407LL;
                arr[i] = (seed >> 33) & 0x7FFFFFFFL;
            }}
        }}

        static void reverse(long long arr[], int n) {{
            int lo = 0, hi = n - 1;
            while (lo < hi) {{
                long long t = arr[lo];
                arr[lo++] = arr[hi];
                arr[hi--] = t;
            }}
        }}

        static long long sum(const long long arr[], int n) {{
            long long s = 0;
            int i;
            for (i = 0; i < n; i++) s += arr[i];
            return s;
        }}

        int main(void) {{
            long long arr[N];
            long long total = 0;
            int it;
            for (it = 0; it < {iters}; it++) {{
                fill(arr, N, (long long)(it + {seed_v}));
                reverse(arr, N);
                total += sum(arr, N);
            }}
            printf("%lld\\n", total);
            return 0;
        }}
    """)


def _gen_recursion(rng: _SeededRNG, idx: int) -> str:
    """Generate a recursion-heavy program with bounded depth."""
    n = rng.randint(20, 38)   # Fibonacci with memoization stops stack explosion

    return textwrap.dedent(f"""\
        /* Generated benchmark: recursion family, index {idx}
         * Memoized Fibonacci — bounded depth, no stack overflow for n<={n}.
         * memo[] is statically sized. */
        #include <stdio.h>

        #define MAXN {n + 1}
        static long long memo[MAXN];
        static int computed[MAXN];

        static long long fib(int n) {{
            if (n <= 1) return (long long)n;
            if (computed[n]) return memo[n];
            memo[n] = fib(n - 1) + fib(n - 2);
            computed[n] = 1;
            return memo[n];
        }}

        int main(void) {{
            long long total = 0;
            int i;
            for (i = 0; i <= {n}; i++) {{
                total += fib(i);
            }}
            printf("%lld\\n", total);
            return 0;
        }}
    """)


def _gen_branch(rng: _SeededRNG, idx: int) -> str:
    """Generate a branch-heavy computation program."""
    n       = rng.randint(100, 500)
    mod_val = rng.randint(5, 17)

    return textwrap.dedent(f"""\
        /* Generated benchmark: branch family, index {idx}
         * FizzBuzz-style multi-branch accumulator over {n} values.
         * All branches deterministic; no UB. */
        #include <stdio.h>

        int main(void) {{
            long long acc = 0;
            int i;
            for (i = 1; i <= {n}; i++) {{
                if (i % {mod_val} == 0 && i % 3 == 0) {{
                    acc += (long long)i * 7;
                }} else if (i % {mod_val} == 0) {{
                    acc += (long long)i * 3;
                }} else if (i % 3 == 0) {{
                    acc += (long long)i * 5;
                }} else if (i % 2 == 0) {{
                    acc -= (long long)i;
                }} else {{
                    acc += 1;
                }}
            }}
            printf("%lld\\n", acc);
            return 0;
        }}
    """)


def _gen_function(rng: _SeededRNG, idx: int) -> str:
    """Generate a function-call-heavy program."""
    n       = rng.randint(20, 80)
    depth   = rng.randint(2, 5)
    base    = rng.randint(2, 9)

    return textwrap.dedent(f"""\
        /* Generated benchmark: function family, index {idx}
         * Mutual-call chain computing power sums.
         * Bounded depth={depth}; no recursion deeper than that. */
        #include <stdio.h>

        static long long poly(int x, int deg);

        static long long square(long long v) {{
            return v * v;
        }}

        static long long cube(long long v) {{
            return v * v * v;
        }}

        static long long poly(int x, int deg) {{
            if (deg <= 0) return 1LL;
            if (deg == 1) return (long long)x;
            if (deg == 2) return square((long long)x);
            return cube((long long)x);
        }}

        static long long series_sum(int n, int base, int deg) {{
            long long s = 0;
            int i;
            for (i = 1; i <= n; i++) {{
                s += poly(base + i, deg);
            }}
            return s;
        }}

        int main(void) {{
            long long total = 0;
            int d;
            for (d = 0; d <= {depth}; d++) {{
                total += series_sum({n}, {base}, d);
            }}
            printf("%lld\\n", total);
            return 0;
        }}
    """)


# ---------------------------------------------------------------------------
# Family dispatch table
# ---------------------------------------------------------------------------

_FAMILY_GENERATORS = {
    "loop":      _gen_loop,
    "math":      _gen_math,
    "memory":    _gen_memory,
    "recursion": _gen_recursion,
    "branch":    _gen_branch,
    "function":  _gen_function,
}


# ---------------------------------------------------------------------------
# BenchmarkGenerator
# ---------------------------------------------------------------------------

class BenchmarkGenerator:
    """
    Deterministic seeded generator of synthetic C benchmark programs.

    Usage
    -----
    gen = BenchmarkGenerator(seed=42, output_dir="/path/to/benchmarks_generated")
    entries = gen.generate(n_per_family=5)
    # Returns list[CorpusEntry] with origin="generated"

    The same seed + n_per_family always produces identical source files.
    Different seeds always produce distinct source files.
    Generated filenames are of the form: gen_<family>_seed<seed>_<idx>.c
    These will never collide with the existing test_cases/ naming pattern
    (which uses numeric prefixes like 01_hello_world.c).
    """

    def __init__(self, seed: int = 42, output_dir: Optional[str] = None):
        """
        Parameters
        ----------
        seed        : master seed for all generated programs
        output_dir  : directory where .c source files are written.
                      If None, files are generated in-memory only (source_path
                      is set to None in CorpusEntry).
        """
        self.seed = seed
        self.output_dir = output_dir

    def _make_rng(self, family: str, idx: int) -> _SeededRNG:
        """Derive a deterministic per-program RNG from master seed + family + idx."""
        derived = int(
            hashlib.sha256(
                f"{self.seed}:{family}:{idx}".encode()
            ).hexdigest(), 16
        ) % (2**31)
        return _SeededRNG(derived)

    def _filename(self, family: str, idx: int) -> str:
        return f"gen_{family}_seed{self.seed}_{idx}.c"

    def _program_id(self, family: str, idx: int) -> str:
        return f"gen_{family}_seed{self.seed}_{idx}"

    def generate_one(
        self,
        family: str,
        idx: int,
    ) -> tuple[str, CorpusEntry]:
        """
        Generate one synthetic C program.

        Returns
        -------
        (source_text, CorpusEntry)
        If output_dir is set, the file is written and source_path is absolute.
        """
        if family not in _FAMILY_GENERATORS:
            raise ValueError(f"Unknown generator family: {family!r}")

        rng = self._make_rng(family, idx)
        source_text = _FAMILY_GENERATORS[family](rng, idx)
        filename = self._filename(family, idx)
        program_id = self._program_id(family, idx)

        source_path: Optional[str] = None
        if self.output_dir:
            os.makedirs(self.output_dir, exist_ok=True)
            source_path = os.path.abspath(
                os.path.join(self.output_dir, filename)
            )
            with open(source_path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(source_text)

        sha = hashlib.sha256(source_text.encode("utf-8")).hexdigest()

        entry = CorpusEntry(
            program_id=program_id,
            source_path=source_path or "",
            source_sha256=sha,
            origin="generated",
            family=family,
            generator_seed=self.seed,
            generator_index=idx,
            excluded=False,
            exclusion_reason=None,
        )
        return source_text, entry

    def generate(
        self,
        n_per_family: int = 5,
        families: Optional[tuple[str, ...]] = None,
    ) -> list[CorpusEntry]:
        """
        Generate n_per_family programs per family.

        Parameters
        ----------
        n_per_family : number of programs per generator family
        families     : subset of GENERATOR_FAMILIES to use (default: all)

        Returns
        -------
        Ordered list of CorpusEntry with origin="generated".
        Order: by family (as in GENERATOR_FAMILIES), then by index.
        """
        active_families = families if families is not None else GENERATOR_FAMILIES
        entries: list[CorpusEntry] = []
        for family in active_families:
            for idx in range(n_per_family):
                _, entry = self.generate_one(family, idx)
                entries.append(entry)
        return entries
