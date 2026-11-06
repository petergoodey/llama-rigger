#include <stddef.h>
#include <string.h>

/* Copy up to len bytes of src into out (capacity outcap), NUL-terminated.
   Returns the number of bytes copied. */
int copy_field(char *out, size_t outcap, const char *src, size_t len) {
    if (outcap == 0) return -1;
    if (len > outcap - 1) len = outcap - 1;   /* clamp to leave room for NUL */
    memcpy(out, src, len);
    out[len] = '\0';
    return (int)len;
}
