union Data {
    int i;
    float f;
};
int main() {
    union Data d;
    d.i = 10;
    return d.i;
}