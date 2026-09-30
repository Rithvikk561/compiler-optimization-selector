/*
 * TC1_loop_heavy.c
 * DEMO STORY: Performance Win — AI produces smaller code than -O3
 *
 * WHY THIS WORKS IN THE GUI:
 *   -O3  physically unrolls and auto-vectorizes both loops into SIMD
 *        instructions, making the binary MUCH larger (code size bloat).
 *   AI (-O2)  keeps the loop structure compact, producing a smaller binary.
 *
 * EXPECTED GUI BEHAVIOUR:
 *   Feature tab: Insts and Blocks drop significantly in both -O3 and AI tabs
 *                compared to Unoptimized (shown in green).
 *   Metrics table: Code Size for AI < Code Size for -O3
 *   Security: N/A (not a security file, no badge change)
 */

void sink(int x);   /* prevent full DCE */

int main(void) {
    int arr[512];
    int sum = 0;

    /* Loop 1: heavy accumulation — O3 will vectorize with SIMD */
    for (int i = 0; i < 512; i++) {
        arr[i] = (i * 31) ^ (i >> 3);
    }

    /* Loop 2: dependent reduction — O3 unrolls aggressively */
    for (int i = 0; i < 512; i++) {
        sum += arr[i] * (i % 7 + 1);
    }

    sink(sum);
    return 0;
}

/* Out-of-line to prevent inlining and force actual code emission */
__attribute__((noinline)) void sink(int x) { (void)x; }
