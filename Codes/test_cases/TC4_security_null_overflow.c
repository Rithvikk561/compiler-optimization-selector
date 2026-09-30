/*
 * TC4_security_null_overflow.c
 * DEMO STORY: Multiple Security Guards — maximum security badge impact
 *
 * Uses assert_failed pattern (filename contains "security") with THREE
 * independent security checks so the IR clearly shows many stores.
 *
 * SCENARIO: A simple string processing function with:
 *   1. NULL pointer check
 *   2. Buffer overflow guard
 *   3. Integer overflow detection
 *
 * EXPECTED GUI BEHAVIOUR:
 *   -O3 tab:  LLVM inlines everything and may remove stores from
 *             "impossible" paths → fewer assert_failed stores → RED badge
 *   AI  tab:  Conservative -O2 keeps all guard stores → GREEN badge
 *
 * IR VIEWER HIGHLIGHT: Multiple orange-highlighted lines in AI tab
 *   showing `store i32 1, ptr @assert_failed` for each guard.
 */

#define BUFFER_CAP 128

int assert_failed = 0;

/* Guard 1: NULL pointer check */
void check_ptr(const char *p) {
    if (p == (void*)0) {
        assert_failed = 1;
    }
}

/* Guard 2: Buffer overflow check */
void check_length(int len, int capacity) {
    if (len < 0 || len >= capacity) {
        assert_failed = 1;
    }
}

/* Guard 3: Integer overflow sentinel */
void check_sum(int a, int b) {
    /* If adding a and b would overflow, flag it */
    if (a > 0 && b > 2147483647 - a) {
        assert_failed = 1;
    }
}

__attribute__((noinline)) int process(const char *msg, int len, int a, int b) {
    check_ptr(msg);
    check_length(len, BUFFER_CAP);
    check_sum(a, b);
    return a + b + len;
}

int main(void) {
    char msg[] = "Hello Security Check";

    /* All safe calls — but guards must remain in compiled code! */
    int result = process(msg, 20, 1000, 2000);
    result    += process(msg, 50,  500,  300);
    result    += process(msg,  5,  100,   99);

    return assert_failed ? 1 : (result > 0 ? 0 : -1);
}
