/*
 * TC5_recursive_fibonacci.c
 * DEMO STORY: Structural Transformation — recursive vs iterative form in IR
 *
 * WHY THIS WORKS IN THE GUI:
 *   Recursive Fibonacci is the classic compiler demo target.
 *   -O3  converts tail-call recursion to iteration AND performs memoization
 *        through loop transformations. The IR looks completely different
 *        from the source — dramatic structural transformation visible.
 *   AI (-O2)  applies fewer transformations; the recursive call structure
 *        is partially preserved, showing a middle ground in the IR.
 *
 * EXPECTED GUI BEHAVIOUR:
 *   Unoptimized tab: MANY blocks (~20+), branches (~15+), call instructions
 *   -O3 tab:         Block count SLASHED (green -15), recursive calls gone
 *   AI  tab:         Moderate reduction — some call instructions remain
 *
 *   This creates visually dramatic feature panel changes for the recording.
 *   Great for explaining: "See how -O3 eliminates the recursive structure
 *   entirely? The AI keeps enough to ensure correctness."
 */

#include <stdio.h>

/* Non-inlinable wrapper to prevent compiler from optimizing fib(n) at call site */
__attribute__((noinline)) long long fib(int n) {
    if (n <= 0) return 0;
    if (n == 1) return 1;
    return fib(n - 1) + fib(n - 2);
}

__attribute__((noinline)) void display(long long v) {
    /* Opaque — prevents DCE of the fib computation */
    (void)v;
}

int main(void) {
    /* Compute first 15 Fibonacci numbers */
    long long total = 0;
    for (int i = 0; i < 15; i++) {
        long long f = fib(i);
        display(f);
        total += f;
    }

    return (total > 0) ? 0 : 1;
}
