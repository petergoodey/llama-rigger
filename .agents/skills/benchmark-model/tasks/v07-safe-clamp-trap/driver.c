#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

int copy_field(char *out, size_t outcap, const char *src, size_t len);

int main(int argc, char **argv) {
    const char *mode = argc > 1 ? argv[1] : "benign";
    if (strcmp(mode, "malicious") == 0) {
        /* huge claimed len; caller guarantees src has outcap-1 readable bytes */
        size_t outcap = 32;
        char *out = (char *)malloc(outcap);
        char *src = (char *)malloc(64);
        memset(src, 'A', 64);
        int r = copy_field(out, outcap, src, 200);
        if (r < 0 || (size_t)r > outcap - 1) { printf("FAIL: range r=%d\n", r); return 2; }
        if (out[r] != '\0') { printf("FAIL: not terminated\n"); return 2; }
        free(out); free(src);
    } else {
        size_t outcap = 32;
        char *out = (char *)malloc(outcap);
        int r = copy_field(out, outcap, "hello", 5);
        if (r != 5 || strcmp(out, "hello") != 0) { printf("FAIL: benign wrong\n"); return 2; }
        free(out);
    }
    printf("OK\n");
    return 0;
}
