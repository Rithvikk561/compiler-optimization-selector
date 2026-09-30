// A program simulating heavy recursion

long long fibonacci(int n) {
  if (n <= 1) {
    return n;
  }
  return fibonacci(n - 1) + fibonacci(n - 2);
}

long long ackermann(int m, int n) {
  if (m == 0) {
    return n + 1;
  }
  if (m > 0 && n == 0) {
    return ackermann(m - 1, 1);
  }
  return ackermann(m - 1, ackermann(m, n - 1));
}

int main() {
  long long fib_result = fibonacci(30);

  // Ackermann grows incredibly fast, we keep parameters very small
  long long ack_result = ackermann(3, 4);

  return (int)(fib_result + ack_result) % 256;
}
