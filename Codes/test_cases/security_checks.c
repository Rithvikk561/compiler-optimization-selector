#define BUFFER_SIZE 256

// Use int returns for assertions instead of assert() macros.
int assert_failed = 0;

void safe_copy(char *dest, const char *src, unsigned long long n) {
  if (dest == (void *)0 || src == (void *)0) {
    assert_failed = 1;
    return;
  }

  for (unsigned long long i = 0; i < n; i++) {
    if (i >= BUFFER_SIZE) {
      assert_failed = 1; // Bounds check failed
      break;
    }
    dest[i] = src[i];
    if (src[i] == '\0') {
      break;
    }
  }
}

int calculate_safe_index(int base_index, int offset) {
  int index = base_index + offset;

  // Explicit bounds check
  if (index < 0 || index >= BUFFER_SIZE) {
    assert_failed = 1; // Security Alert
    return 0;
  }
  return index;
}

int main() {
  char dest_buffer[BUFFER_SIZE];
  char source_string[] =
      "This is a test string to check safe copying and assertions.";

  // Normal case
  safe_copy(dest_buffer, source_string, sizeof(source_string));

  // Intentional bounds check trigger in calculation
  int safe_idx1 = calculate_safe_index(100, 50);
  int safe_idx2 = calculate_safe_index(200, 100);

  // Another assertion test
  int test_val = 5;
  if (!(test_val > 0)) {
    assert_failed = 1;
  }

  return assert_failed; // Will return non-zero if any assertion failed
}
