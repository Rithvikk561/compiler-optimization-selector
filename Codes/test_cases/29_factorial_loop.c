int main() {
    int n = 5;
    long long fact = 1;
    for (int i = 1; i <= n; ++i) {
        fact *= i;
    }
    return (int)fact;
}