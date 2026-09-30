int main() {
    int arr[10];
    int *ptr = arr;
    for(int i = 0; i < 10; i++) {
        ptr[i] = i * i;
    }
    int sum = 0;
    for(int i = 0; i < 10; i++) {
        sum += ptr[i];
    }
    return sum;
}