#include <stddef.h>
#include <stdio.h>

long bsearch_first(const int *a, size_t n, int key);

static int fails = 0;
static void chk(int cond, const char *msg) {
    if (!cond) { printf("FAIL: %s\n", msg); fails++; }
}

int main(void) {
    int a[] = {1, 2, 2, 2, 3, 5, 5, 9};
    size_t n = sizeof a / sizeof a[0];
    chk(bsearch_first(a, n, 2) == 1, "first 2 at 1");
    chk(bsearch_first(a, n, 5) == 5, "first 5 at 5");
    chk(bsearch_first(a, n, 1) == 0, "1 at 0");
    chk(bsearch_first(a, n, 9) == 7, "9 at 7");
    chk(bsearch_first(a, n, 4) == -1, "4 missing");
    chk(bsearch_first(a, n, 0) == -1, "0 missing");
    chk(bsearch_first(a, n, 10) == -1, "10 missing");
    chk(bsearch_first(a, 0, 1) == -1, "empty");

    int one[] = {7};
    chk(bsearch_first(one, 1, 7) == 0, "single hit");
    chk(bsearch_first(one, 1, 8) == -1, "single miss");

    static int big[100000];
    for (size_t i = 0; i < 100000; i++) big[i] = (int)(i / 2); /* dups */
    chk(bsearch_first(big, 100000, 25000) == 50000, "big first occurrence");
    chk(bsearch_first(big, 100000, 49999) == 99998, "big last value");

    if (fails == 0) printf("ALL_PASS\n");
    return fails ? 1 : 0;
}
