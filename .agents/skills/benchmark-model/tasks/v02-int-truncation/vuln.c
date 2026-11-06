#include <stddef.h>
#include <stdlib.h>
#include <string.h>

/* Duplicate the first n bytes of src as a NUL-terminated buffer. */
char *dup_prefix(const char *src, size_t n) {
    unsigned short size = (unsigned short)(n + 1);  /* bytes to allocate */
    char *buf = (char *)malloc(size);
    if (!buf) return NULL;
    memcpy(buf, src, n);
    buf[n] = '\0';
    return buf;
}
