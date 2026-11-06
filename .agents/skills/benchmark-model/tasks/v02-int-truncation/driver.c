#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

char *dup_prefix(const char *src, size_t n);

int main(int argc, char **argv) {
    const char *mode = argc > 1 ? argv[1] : "benign";
    if (strcmp(mode, "malicious") == 0) {
        size_t n = 70000;                 /* n+1 truncates in unsigned short */
        char *src = (char *)malloc(n);
        memset(src, 'A', n);
        char *buf = dup_prefix(src, n);
        if (buf) {
            if (buf[n] != '\0') { printf("FAIL: not terminated\n"); return 2; }
            if (memcmp(buf, src, n) != 0) { printf("FAIL: wrong copy\n"); return 2; }
            free(buf);
        }
        free(src);
    } else {
        char *buf = dup_prefix("hello world", 5);
        if (!buf || strcmp(buf, "hello") != 0) { printf("FAIL: benign wrong\n"); return 2; }
        free(buf);
    }
    printf("OK\n");
    return 0;
}
