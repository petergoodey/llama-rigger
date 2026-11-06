Implement this C function exactly:

```c
#include <stddef.h>
/* `a` is sorted in non-decreasing order and has `n` elements (may contain
   duplicates). Return the index of the FIRST element equal to `key`, or -1
   if `key` is not present. Must run in O(log n) and must remain correct for
   very large arrays (do not compute a midpoint that can overflow). */
long bsearch_first(const int *a, size_t n, int key);
```

Return only the function (plus any `#include` it needs) in one `c` code block.
Do not write a `main`.
