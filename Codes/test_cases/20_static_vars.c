int counter() {
    static int c = 0;
    c++;
    return c;
}
int main() {
    counter();
    return counter();
}