int main() {
    int a = 10, b = 20, c = 30;
    if (a < b) {
        if (b < c) return c;
        else return b;
    } else return a;
}