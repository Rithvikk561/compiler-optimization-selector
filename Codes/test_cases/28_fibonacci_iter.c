int main() {
    int n = 10, t1 = 0, t2 = 1, nextTerm;
    for (int i = 1; i <= n; ++i) {
        nextTerm = t1 + t2;
        t1 = t2;
        t2 = nextTerm;
    }
    return t1;
}