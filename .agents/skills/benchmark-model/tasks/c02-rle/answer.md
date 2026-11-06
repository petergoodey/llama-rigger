# c02 rle_encode — answer key

```c
#include <stddef.h>
size_t rle_encode(const unsigned char *in, size_t n,
                  unsigned char *out, size_t outcap) {
    size_t w = 0, i = 0;
    while (i < n) {
        unsigned char v = in[i];
        size_t run = 1;
        while (i + run < n && in[i + run] == v && run < 255) run++;
        if (w + 2 > outcap) return (size_t)-1;
        out[w++] = (unsigned char)run;
        out[w++] = v;
        i += run;
    }
    return w;
}
```

Key points the driver checks: runs capped at 255 and split; capacity checked
*before* each 2-byte write (returns (size_t)-1, never writes past outcap);
n==0 returns 0; exact-fit capacity works. Auto-graded.
