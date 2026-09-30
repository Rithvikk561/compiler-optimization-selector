struct Student { int id; int score; };
int main() {
    struct Student class[3] = {{1, 90}, {2, 85}, {3, 88}};
    int sum = 0;
    for(int i = 0; i < 3; i++) sum += class[i].score;
    return sum;
}