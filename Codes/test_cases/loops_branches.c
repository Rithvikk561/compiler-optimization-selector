#define SIZE 10000

int main() {
  int data[SIZE];
  long long sum = 0;
  int max_val = 0;

  // Initialization loop
  for (int i = 0; i < SIZE; i++) {
    data[i] = (i * 17) % 256;
  }

  // Complex loop with branches
  for (int i = 0; i < SIZE; i++) {
    if (data[i] % 2 == 0) {
      sum += data[i] * 2;
    } else if (data[i] % 3 == 0) {
      sum -= data[i];
    } else {
      sum += data[i] / 2;
    }

    if (data[i] > max_val) {
      max_val = data[i];
    }
  }

  // Nested loops for matrix-like operations
  int matrix[100][100];
  for (int i = 0; i < 100; i++) {
    for (int j = 0; j < 100; j++) {
      matrix[i][j] = (i + j) % 10;
    }
  }

  long long matrix_sum = 0;
  for (int i = 0; i < 100; i++) {
    for (int j = 0; j < 100; j++) {
      if (i == j) {
        matrix_sum += matrix[i][j] * 5;
      } else {
        matrix_sum += matrix[i][j];
      }
    }
  }

  // Return something based on computations so they aren't completely optimized
  // away
  return (int)(sum + max_val + matrix_sum) % 256;
}
