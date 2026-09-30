int main() {
    int n1 = 15, n2 = 20, max;
    max = (n1 > n2) ? n1 : n2;
    while (1) {
        if ((max % n1 == 0) && (max % n2 == 0)) return max;
        ++max;
    }
}