Implement this C function exactly:

```c
#include <stddef.h>
/* Run-length encode `n` bytes from `in` into `out` (capacity `outcap`).
   Output is a sequence of (count, value) byte pairs. A run is at most 255
   long; a longer run of the same byte is split into multiple pairs.
   Returns the number of bytes written to `out`. If the encoding would not
   fit in `outcap`, writes nothing meaningful and returns (size_t)-1.
   For n == 0, writes nothing and returns 0.
   Must never write past out[outcap-1]. */
size_t rle_encode(const unsigned char *in, size_t n,
                  unsigned char *out, size_t outcap);
```

Return only the function (plus any `#include` it needs) in one `c` code block.
Do not write a `main`.
