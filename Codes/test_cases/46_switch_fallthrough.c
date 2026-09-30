int main() {
    int x = 2;
    int y = 0;
    switch(x) {
        case 1: y++;
        case 2: y++;
        case 3: y++; break;
        default: y--;
    }
    return y;
}