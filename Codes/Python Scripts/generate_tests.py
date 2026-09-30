import os

def create_test_cases(output_dir="test_cases"):
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    test_cases = {
        "01_hello_world.c": """
int printf(const char *, ...);
int main() {
    printf("Hello, Compiler!\\n");
    return 0;
}
""",
        "02_arithmetic.c": """
int main() {
    int a = 10, b = 20;
    int sum = a + b;
    int diff = a - b;
    int prod = a * b;
    int quot = b / a;
    return sum;
}
""",
        "03_if_else.c": """
int main() {
    int x = 10;
    if (x > 5) {
        return 1;
    } else {
        return 0;
    }
}
""",
        "04_while_loop.c": """
int main() {
    int i = 0;
    int sum = 0;
    while (i < 10) {
        sum += i;
        i++;
    }
    return sum;
}
""",
        "05_for_loop.c": """
int main() {
    int sum = 0;
    for (int i = 0; i < 10; i++) {
        sum += i;
    }
    return sum;
}
""",
        "06_nested_loops.c": """
int main() {
    int count = 0;
    for (int i = 0; i < 5; i++) {
        for (int j = 0; j < 5; j++) {
            count++;
        }
    }
    return count;
}
""",
        "07_functions.c": """
int add(int a, int b) {
    return a + b;
}
int main() {
    return add(5, 7);
}
""",
        "08_recursion.c": """
int factorial(int n) {
    if (n <= 1) return 1;
    return n * factorial(n - 1);
}
int main() {
    return factorial(5);
}
""",
        "09_arrays.c": """
int main() {
    int arr[5] = {1, 2, 3, 4, 5};
    return arr[2];
}
""",
        "10_pointers.c": """
int main() {
    int x = 10;
    int *p = &x;
    return *p;
}
""",
        "11_array_pointers.c": """
int main() {
    int arr[3] = {10, 20, 30};
    int *p = arr;
    return *(p + 1);
}
""",
        "12_structs.c": """
struct Point {
    int x;
    int y;
};
int main() {
    struct Point p = {10, 20};
    return p.x + p.y;
}
""",
        "13_nested_structs.c": """
struct Point { int x, y; };
struct Rect { struct Point p1, p2; };
int main() {
    struct Rect r = {{0,0}, {10,10}};
    return r.p2.x;
}
""",
        "14_switch_case.c": """
int main() {
    int x = 2;
    switch(x) {
        case 1: return 10;
        case 2: return 20;
        default: return 0;
    }
}
""",
        "15_ternary_op.c": """
int main() {
    int x = 10;
    return (x > 5) ? 1 : 0;
}
""",
        "16_bitwise_ops.c": """
int main() {
    int a = 5, b = 3;
    return (a & b) | (a ^ b);
}
""",
        "17_float_arithmetic.c": """
int main() {
    float a = 5.5, b = 2.2;
    float res = a * b;
    return (int)res;
}
""",
        "18_type_casting.c": """
int main() {
    double d = 3.14;
    int i = (int)d;
    return i;
}
""",
        "19_global_vars.c": """
int g_x = 100;
int main() {
    return g_x + 5;
}
""",
        "20_static_vars.c": """
int counter() {
    static int c = 0;
    c++;
    return c;
}
int main() {
    counter();
    return counter();
}
""",
        "21_unions.c": """
union Data {
    int i;
    float f;
};
int main() {
    union Data d;
    d.i = 10;
    return d.i;
}
""",
        "22_enums.c": """
enum Color { RED, GREEN, BLUE };
int main() {
    enum Color c = GREEN;
    return (int)c;
}
""",
        "23_void_pointers.c": """
int main() {
    int x = 10;
    void *ptr = &x;
    return *(int*)ptr;
}
""",
        "24_do_while.c": """
int main() {
    int i = 0;
    do {
        i++;
    } while (i < 5);
    return i;
}
""",
        "25_complex_expression.c": """
int main() {
    int a = 1, b = 2, c = 3, d = 4;
    return (a + b) * (c - d) / (a + d);
}
""",
        "26_bubble_sort.c": """
void bubbleSort(int arr[], int n) {
    int i, j, temp;
    for (i = 0; i < n-1; i++)      
        for (j = 0; j < n-i-1; j++)
            if (arr[j] > arr[j+1]) {
                temp = arr[j];
                arr[j] = arr[j+1];
                arr[j+1] = temp;
            }
}
int main() {
    int arr[] = {64, 34, 25, 12, 22, 11, 90};
    int n = 7;
    bubbleSort(arr, n);
    return arr[0];
}
""",
        "27_binary_search.c": """
int binarySearch(int arr[], int l, int r, int x) {
    while (l <= r) {
        int m = l + (r - l) / 2;
        if (arr[m] == x) return m;
        if (arr[m] < x) l = m + 1;
        else r = m - 1;
    }
    return -1;
}
int main() {
    int arr[] = {2, 3, 4, 10, 40};
    int n = 5;
    int x = 10;
    return binarySearch(arr, 0, n - 1, x);
}
""",
        "28_fibonacci_iter.c": """
int main() {
    int n = 10, t1 = 0, t2 = 1, nextTerm;
    for (int i = 1; i <= n; ++i) {
        nextTerm = t1 + t2;
        t1 = t2;
        t2 = nextTerm;
    }
    return t1;
}
""",
        "29_factorial_loop.c": """
int main() {
    int n = 5;
    long long fact = 1;
    for (int i = 1; i <= n; ++i) {
        fact *= i;
    }
    return (int)fact;
}
""",
        "30_matrix_add.c": """
int main() {
    int a[2][2] = {{1,2},{3,4}};
    int b[2][2] = {{5,6},{7,8}};
    int sum[2][2];
    for(int i=0;i<2;++i)
        for(int j=0;j<2;++j)
            sum[i][j] = a[i][j] + b[i][j];
    return sum[1][1];
}
""",
        "31_palindrome_check.c": """
int main() {
    int n = 1001, reversed = 0, remainder, original;
    original = n;
    while (n != 0) {
        remainder = n % 10;
        reversed = reversed * 10 + remainder;
        n /= 10;
    }
    if (original == reversed) return 1;
    else return 0;
}
""",
        "32_prime_check.c": """
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
""",
        "33_pointer_arithmetic.c": """
int main() {
    int arr[] = {10, 20, 30};
    int *p = arr;
    p++;
    *p = 50;
    return arr[1];
}
""",
        "34_dynamic_memory_sim.c": """
int main() {
    int arr[10];
    int *ptr = arr;
    for(int i = 0; i < 10; i++) {
        ptr[i] = i * i;
    }
    int sum = 0;
    for(int i = 0; i < 10; i++) {
        sum += ptr[i];
    }
    return sum;
}
""",
        "35_string_length.c": """
int main() {
    char str[] = "Compiler Design";
    int length = 0;
    while(str[length] != '\\0') {
        length++;
    }
    return length;
}
""",
        "36_string_copy.c": """
int main() {
    char target[20];
    char source[] = "Copy This";
    int i = 0;
    while(source[i] != '\\0') {
        target[i] = source[i];
        i++;
    }
    target[i] = '\\0';
    return target[0];
}
""",
        "37_struct_array.c": """
struct Student { int id; int score; };
int main() {
    struct Student class[3] = {{1, 90}, {2, 85}, {3, 88}};
    int sum = 0;
    for(int i = 0; i < 3; i++) sum += class[i].score;
    return sum;
}
""",
        "38_union_bitwise.c": """
union Bits { int val; struct { unsigned int b1:1, b2:1, b3:1; } flags; };
int main() {
    union Bits x;
    x.val = 0;
    x.flags.b1 = 1;
    x.flags.b3 = 1;
    return x.val;
}
""",
        "39_multi_dimensional_array.c": """
int main() {
    int arr[2][2][2] = {{{1,2},{3,4}},{{5,6},{7,8}}};
    int sum = 0;
    for(int i=0;i<2;i++)
       for(int j=0;j<2;j++)
           for(int k=0;k<2;k++)
               sum += arr[i][j][k];
    return sum;
}
""",
        "40_gcd.c": """
int gcd(int n1, int n2) {
    if (n2 != 0) return gcd(n2, n1 % n2);
    else return n1;
}
int main() {
    return gcd(366, 60);
}
""",
        "41_lcm.c": """
int main() {
    int n1 = 15, n2 = 20, max;
    max = (n1 > n2) ? n1 : n2;
    while (1) {
        if ((max % n1 == 0) && (max % n2 == 0)) return max;
        ++max;
    }
}
""",
        "42_bit_shift_mult.c": """
int main() {
    int x = 4;
    return (x << 3) + (x << 1); 
}
""",
        "43_float_accumulator.c": """
int main() {
    float sum = 0.0;
    for(int i=0; i<100; i++) sum += 0.1f * i;
    return (int)sum;
}
""",
        "44_struct_pointer.c": """
struct Node { int data; };
int main() {
    struct Node n;
    n.data = 42;
    struct Node *p = &n;
    p->data = 100;
    return n.data;
}
""",
        "45_func_pointer.c": """
int add(int a, int b) { return a + b; }
int main() {
    int (*fp)(int, int) = add;
    return fp(10, 20);
}
""",
        "46_switch_fallthrough.c": """
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
""",
        "47_nested_if.c": """
int main() {
    int a = 10, b = 20, c = 30;
    if (a < b) {
        if (b < c) return c;
        else return b;
    } else return a;
}
""",
        "48_recursive_sum.c": """
int sum(int n) {
    if (n != 0) return n + sum(n - 1);
    else return n;
}
int main() {
    return sum(20);
}
""",
        "49_array_reversal.c": """
int main() {
    int arr[] = {1, 2, 3, 4, 5};
    int temp;
    for(int i = 0; i < 5/2; i++) {
        temp = arr[i];
        arr[i] = arr[4-i];
        arr[4-i] = temp;
    }
    return arr[0];
}
""",
        "50_complex_math_sim.c": """
float square(float x) { return x * x; }
float my_abs(float x) { return x < 0 ? -x : x; }
int main() {
    float a = -5.5;
    float res = square(my_abs(a));
    return (int)res;
}
"""
    }

    print(f"Generating {len(test_cases)} test cases in '{output_dir}'...")
    for filename, content in test_cases.items():
        with open(os.path.join(output_dir, filename), "w") as f:
            f.write(content.strip())
        print(f"Created {filename}")
    print("Done.")

if __name__ == "__main__":
    create_test_cases()
