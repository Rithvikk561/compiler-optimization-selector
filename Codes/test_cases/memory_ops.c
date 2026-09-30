#define ARRAY_SIZE 50000

typedef struct {
  int id;
  double value;
  int *data;
} Node;

void process_array(int *arr, int size) {
  for (int i = 0; i < size; i++) {
    arr[i] = arr[i] * 3 + 1;
  }
}

void process_nodes(Node *nodes, int count) {
  for (int i = 0; i < count; i++) {
    nodes[i].value *= 1.5;
    if (nodes[i].data != (void *)0) {
      *(nodes[i].data) += 10;
    }
  }
}

// Statically allocate instead of malloc
int static_array[ARRAY_SIZE];
Node static_nodes[1000];

int main() {
  for (int i = 0; i < ARRAY_SIZE; i++) {
    static_array[i] = i;
  }

  process_array(static_array, ARRAY_SIZE);

  long long array_sum = 0;
  for (int i = 0; i < ARRAY_SIZE; i++) {
    array_sum += static_array[i];
  }

  for (int i = 0; i < 1000; i++) {
    static_nodes[i].id = i;
    static_nodes[i].value = (double)i * 0.1;
    static_nodes[i].data = &static_array[i];
  }

  process_nodes(static_nodes, 1000);

  double node_val_sum = 0.0;
  for (int i = 0; i < 1000; i++) {
    node_val_sum += static_nodes[i].value;
  }

  return (int)(array_sum) % 256 + (int)node_val_sum % 256;
}
