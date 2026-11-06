#include <stddef.h>

/* Copy at most cap-1 chars of src into dst and NUL-terminate.
   dst points to exactly cap bytes. */
void bounded_copy(char *dst, size_t cap, const char *src) {
    size_t i;
    for (i = 0; i <= cap - 1 && src[i] != '\0'; i++)
        dst[i] = src[i];
    dst[i] = '\0';
}
