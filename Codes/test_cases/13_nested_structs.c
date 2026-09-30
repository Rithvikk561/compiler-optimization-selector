struct Point { int x, y; };
struct Rect { struct Point p1, p2; };
int main() {
    struct Rect r = {{0,0}, {10,10}};
    return r.p2.x;
}