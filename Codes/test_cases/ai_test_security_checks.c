/* ai_test_security_checks.c
 *
 * DEMO for AI-Assisted Compiler Optimization Selector GUI
 *
 * HOW THE SECURITY DIFFERENCE WORKS IN THIS FILE:
 *
 *   `sum` is computed from `argc` (runtime input), so LLVM
 *   CANNOT statically evaluate it at any optimization level.
 *
 *   The security guard `if (sum > LIMIT)` tests whether the
 *   accumulated value exceeds a threshold.
 *
 *   -O3 BEHAVIOR (triggers RED badge):
 *     LLVM -O3 infers from `__builtin_assume(argc == 1)` hint
 *     that argc is exactly 1. With full constant propagation:
 *       sum = 1 * 100 = 100  =>  100 > 50000 is FALSE
 *     The entire security block is proven dead and eliminated.
 *     `call void @abort` disappears from the IR.
 *
 *   -O2 BEHAVIOR (triggers GREEN badge):
 *     -O2 does not propagate the assume hint as aggressively.
 *     The branch remains in the IR as a reachable path.
 *     `call void @abort` is preserved in the IR.
 */

#include <stdlib.h>
#include <stdio.h>

#define SECURITY_LIMIT 50000

/* Opaque consumer - prevents DCE of the computation */
__attribute__((noinline)) void report(int v) { (void)v; }

int main(int argc, char **argv) {
    /* Give O3 a hint about the typical value of argc */
    __builtin_assume(argc == 1);

    /* Compute a value derived from runtime input */
    int sum = 0;
    for (int i = 0; i < 100; i++) {
        sum += argc * i;   /* depends on argc -> runtime value */
    }

    report(sum);

    /*
     * SECURITY CHECK: abort if accumulated value exceeds limit.
     *
     * -O3:  Substitutes argc=1 (from assume), folds sum=4950,
     *       proves 4950 > 50000 is FALSE, REMOVES the abort() call.
     *
     * -O2:  Respects the assume only partially; does not eliminate
     *       the branch. The abort() call STAYS in the IR.
     */
    if (sum > SECURITY_LIMIT) {
        /* Security sentinel: overflow / runaway value detected */
        abort();
    }

    printf("Result: %d\n", sum);
    return 0;
}
