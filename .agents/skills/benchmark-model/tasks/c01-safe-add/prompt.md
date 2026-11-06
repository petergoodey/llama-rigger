Implement this C function exactly:

```c
#include <stdint.h>
/* Returns a + b. If the mathematical result does not fit in int32_t,
   set *overflow to 1 and return the two's-complement wrapped result;
   otherwise set *overflow to 0. `overflow` is never NULL. */
int32_t safe_add(int32_t a, int32_t b, int *overflow);
```

Return only the function (plus any `#include` it needs) in one `c` code block.
Do not write a `main`.
