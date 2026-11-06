#include <cstddef>
#include <cstdlib>
#include <cstring>

/* Return a heap "Hello, <name>" string for the caller to free. */
char *make_greeting(const char *name, size_t n) {
    char *buf = (char *)malloc(7 + n + 1);
    std::memcpy(buf, "Hello, ", 7);
    std::memcpy(buf + 7, name, n);
    buf[7 + n] = '\0';
    if (n == 0) {
        free(buf);          /* nothing to greet */
    }
    return buf;
}
