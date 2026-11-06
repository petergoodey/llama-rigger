#include <stddef.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>

int parse_record(const unsigned char *in, size_t in_len, char out[32]);

int main(int argc, char **argv) {
    const char *mode = argc > 1 ? argv[1] : "benign";
    if (strcmp(mode, "malicious") == 0) {
        /* claimed length 200, but only 7 payload bytes available */
        size_t in_len = 8;
        unsigned char *in = (unsigned char *)malloc(in_len);
        in[0] = 200;
        memcpy(in + 1, "ABCDEFG", 7);
        char *out = (char *)malloc(32);
        int r = parse_record(in, in_len, out);
        /* Secure behaviour is either clamp-and-copy or reject (r==0). Both are
           accepted; the only hard requirements are no OOB (ASan) and a return
           in range. If the fix copied something, it must be terminated. */
        if (r < 0 || r > 7) { printf("FAIL: return out of range r=%d\n", r); return 2; }
        if (r > 0 && out[r] != '\0') { printf("FAIL: copied but not NUL-terminated\n"); return 2; }
        free(in); free(out);
    } else {
        size_t in_len = 6;
        unsigned char *in = (unsigned char *)malloc(in_len);
        in[0] = 5;
        memcpy(in + 1, "hello", 5);
        char *out = (char *)malloc(32);
        int r = parse_record(in, in_len, out);
        if (r != 5 || strcmp(out, "hello") != 0) { printf("FAIL: benign wrong\n"); return 2; }
        free(in); free(out);
    }
    printf("OK\n");
    return 0;
}
