/*
 * TC3_math_intensive.c
 * DEMO STORY: Feature Reduction — watch Insts and Math counts drop in both views
 *
 * WHY THIS WORKS IN THE GUI:
 *   The unoptimized IR has every intermediate variable stored to the stack
 *   (alloca/store/load chains). Both O3 and AI eliminate these via mem2reg,
 *   instcombine, and constant folding — producing visually dramatic
 *   reductions in the feature panel numbers (large green diffs).
 *
 * EXPECTED GUI BEHAVIOUR:
 *   Unoptimized tab: HIGH counts for Memory (~60), Insts (~150), Math (~40)
 *   -O3 tab:         Memory drops heavily (green -50), Insts drops (green -90)
 *   AI  tab:         Similar reductions but slightly more conservative
 *   Both tabs show the optimizer working hard on arithmetic code.
 */

#include <math.h>

__attribute__((noinline)) void output(double v) { (void)v; }

int main(void) {
    double x = 1.5, y = 2.7, z = 3.14159;
    double result = 0.0;

    /* Chain of floating-point ops — lots of IR instructions at O0 */
    for (int i = 1; i <= 200; i++) {
        double fi = (double)i;
        result += (x * fi + y / (fi + 1.0)) * (z - fi * 0.01);
        result -= (result * 0.001);   /* feedback to prevent pure const folding */
    }

    /* Transcendental ops — rich instruction mix in IR */
    result = result + x * y - z / (x + 0.1);
    result = result * result / (result + 1.0);

    output(result);
    return (result > 0.0) ? 0 : 1;
}
