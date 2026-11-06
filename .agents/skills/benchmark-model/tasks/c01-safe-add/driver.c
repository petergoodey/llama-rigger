#include <stdint.h>
#include <stdio.h>

int32_t safe_add(int32_t a, int32_t b, int *overflow);

static int fails = 0;
static void chk(int cond, const char *msg) {
    if (!cond) { printf("FAIL: %s\n", msg); fails++; }
}

int main(void) {
    int ovf;
    chk(safe_add(2, 3, &ovf) == 5 && ovf == 0, "2+3");
    chk(safe_add(-7, 4, &ovf) == -3 && ovf == 0, "-7+4");
    chk(safe_add(0, 0, &ovf) == 0 && ovf == 0, "0+0");
    chk(safe_add(2147483647, 0, &ovf) == 2147483647 && ovf == 0, "INT_MAX+0");
    safe_add(2147483647, 1, &ovf); chk(ovf == 1, "INT_MAX+1 overflow flag");
    safe_add(-2147483647 - 1, -1, &ovf); chk(ovf == 1, "INT_MIN-1 overflow flag");
    chk(safe_add(2000000000, 2000000000, &ovf) == (int32_t)(2000000000u + 2000000000u) && ovf == 1, "2e9+2e9 wrap+flag");
    safe_add(-2000000000, -2000000000, &ovf); chk(ovf == 1, "-2e9+-2e9 overflow flag");
    chk(safe_add(-2147483647 - 1, 2147483647, &ovf) == -1 && ovf == 0, "INT_MIN+INT_MAX");
    if (fails == 0) printf("ALL_PASS\n");
    return fails ? 1 : 0;
}
