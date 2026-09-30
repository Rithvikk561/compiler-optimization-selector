float square(float x) { return x * x; }
float my_abs(float x) { return x < 0 ? -x : x; }
int main() {
    float a = -5.5;
    float res = square(my_abs(a));
    return (int)res;
}