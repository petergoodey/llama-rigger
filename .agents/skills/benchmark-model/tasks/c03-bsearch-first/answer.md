# c03 bsearch_first — answer key

```c
#include <stddef.h>
long bsearch_first(const int *a, size_t n, int key) {
    size_t lo = 0, hi = n;          /* half-open [lo, hi) */
    long res = -1;
    while (lo < hi) {
        size_t mid = lo + (hi - lo) / 2;   /* overflow-safe midpoint */
        if (a[mid] < key) lo = mid + 1;
        else { if (a[mid] == key) res = (long)mid; hi = mid; }
    }
    return res;
}
```

Checks: returns the FIRST index on duplicates (not any match); -1 when absent;
empty array; single element; and large array (100k) with duplicates. The
midpoint must be `lo + (hi-lo)/2`, not `(lo+hi)/2`. Auto-graded.
