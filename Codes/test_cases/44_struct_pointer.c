struct Node { int data; };
int main() {
    struct Node n;
    n.data = 42;
    struct Node *p = &n;
    p->data = 100;
    return n.data;
}