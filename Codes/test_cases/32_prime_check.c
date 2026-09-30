int main() {
    int n = 29, i, flag = 0;
    if (n == 0 || n == 1) flag = 1;
    for (i = 2; i <= n / 2; ++i) {
        if (n % i == 0) {
            flag = 1;
            break;
        }
    }
    return flag;
}