int main() {
    int arr[] = {10, 20, 30};
    int *p = arr;
    p++;
    *p = 50;
    return arr[1];
}