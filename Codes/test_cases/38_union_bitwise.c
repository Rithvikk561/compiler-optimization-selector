union Bits { int val; struct { unsigned int b1:1, b2:1, b3:1; } flags; };
int main() {
    union Bits x;
    x.val = 0;
    x.flags.b1 = 1;
    x.flags.b3 = 1;
    return x.val;
}