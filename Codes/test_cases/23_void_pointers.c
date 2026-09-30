int main() {
    int x = 10;
    void *ptr = &x;
    return *(int*)ptr;
}