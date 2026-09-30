/*
 * TC2_security_bounds_check.c
 * DEMO STORY: Security Preservation — AI keeps guards, -O3 may strip them
 *
 * Uses the assert_failed global pattern (same as existing security_checks.c)
 * so the GUI security detector activates (filename contains "security").
 *
 * HOW IT WORKS:
 *   `validate_index` sets assert_failed if index is out of bounds.
 *   `safe_read` sets assert_failed if pointer is NULL.
 *   Both are called with SAFE values in main, but the guards must survive.
 *
 * EXPECTED GUI BEHAVIOUR:
 *   -O3 tab:  assert_failed stores may be reduced (DSE on provably safe paths)
 *             Security badge: REMOVED (RED)  ← dramatic for demo
 *   AI  tab:  stores preserved in IR
 *             Security badge: PRESERVED (GREEN) ← proof the AI wins
 *
 * IR VIEWER: Look for orange-highlighted lines (assert_failed stores)
 *            in the AI tab but absent/fewer in the -O3 tab.
 */

#define MAX_SIZE 1024

int assert_failed = 0;

int validate_index(int idx, int limit) {
    if (idx < 0 || idx >= limit) {
        assert_failed = 1;
        return 0;
    }
    return idx;
}

int safe_read(const int *arr, int idx, int limit) {
    if (!arr) {
        assert_failed = 1;
        return -1;
    }
    int safe_idx = validate_index(idx, limit);
    return arr[safe_idx];
}

__attribute__((noinline)) void use(int v) { (void)v; }

int main(void) {
    int data[MAX_SIZE];
    for (int i = 0; i < MAX_SIZE; i++) data[i] = i * 3;

    /* Safe reads — guards are "provably" not triggered at O3 */
    int r1 = safe_read(data, 100, MAX_SIZE);
    int r2 = safe_read(data, 500, MAX_SIZE);
    int r3 = safe_read(data, 999, MAX_SIZE);

    use(r1 + r2 + r3);

    return assert_failed ? 1 : 0;
}
