#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

void bounded_copy(char *dst, size_t cap, const char *src);

int main(int argc, char **argv) {
    const char *mode = argc > 1 ? argv[1] : "benign";
    if (strcmp(mode, "malicious") == 0) {
        size_t cap = 8;
        char *dst = (char *)malloc(cap);          /* exactly cap bytes */
        bounded_copy(dst, cap, "abcdefghijkl");   /* src longer than cap */
        size_t len = strnlen(dst, cap);
        if (len > cap - 1) { printf("FAIL: not terminated within buffer\n"); return 2; }
        free(dst);
    } else {
        size_t cap = 8;
        char *dst = (char *)malloc(cap);
        bounded_copy(dst, cap, "hi");
        if (strcmp(dst, "hi") != 0) { printf("FAIL: benign wrong\n"); return 2; }
        free(dst);
    }
    printf("OK\n");
    return 0;
}
