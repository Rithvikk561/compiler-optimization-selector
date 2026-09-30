struct Point {
    int x;
    int y;
};
int main() {
    struct Point p = {10, 20};
    return p.x + p.y;
}