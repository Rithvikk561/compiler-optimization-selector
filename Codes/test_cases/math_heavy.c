// A program to generate math-heavy floating point operations
// without standard library headers

#define ITERS 10000

double compute_formula(double x, double y) {
  double result = 0.0;
  for (int i = 0; i < 50; i++) {
    // Approximating complex math to give the optimizer work
    result += (x * x) / (y + 1.5) - (y * 0.5);
    x += 0.01;
    y -= 0.01;
  }
  return result;
}

int main() {
  double total = 0.0;
  double start_x = 1.0;
  double start_y = 100.0;

  for (int i = 0; i < ITERS; i++) {
    if (i % 2 == 0) {
      total += compute_formula(start_x, start_y);
    } else {
      total -= compute_formula(start_y, start_x);
    }

    start_x += 0.5;
    start_y += 0.5;
  }

  // Return to prevent complete dead code elimination
  return (int)total % 256;
}
