# c01 safe_add — answer key

Correct approach: detect overflow before/without relying on signed overflow UB.

```c
#include <stdint.h>
int32_t safe_add(int32_t a, int32_t b, int *overflow) {
    int64_t r = (int64_t)a + (int64_t)b;
    *overflow = (r < INT32_MIN || r > INT32_MAX) ? 1 : 0;
    return (int32_t)r;  /* wraps to two's complement on narrowing */
}
```

Also acceptable: `__builtin_add_overflow` / checking signs. The wrapped return
value must equal two's-complement `(int32_t)((uint32_t)a + (uint32_t)b)`.

Common failures: computing `a + b` in `int32_t` first (signed overflow is UB;
also can't then recover the flag reliably), or getting the INT_MIN edge wrong.

Auto-graded by driver.c; no reasoning grade for coding tasks.
