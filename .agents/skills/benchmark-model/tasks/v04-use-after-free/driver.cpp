#include <cstddef>
#include <cstdlib>
#include <cstring>
#include <cstdio>

char *make_greeting(const char *name, size_t n);

int main(int argc, char **argv) {
    const char *mode = argc > 1 ? argv[1] : "benign";
    if (std::strcmp(mode, "malicious") == 0) {
        /* n == 0 is the trigger */
        char *r = make_greeting("", 0);
        if (r) {
            volatile char sink = r[0];      /* read: UAF on the vulnerable version */
            (void)sink;
            if (std::strcmp(r, "Hello, ") != 0) { std::printf("FAIL: content\n"); return 2; }
            free(r);
        }
    } else {
        char *r = make_greeting("Bob", 3);
        if (!r) { std::printf("FAIL: null benign\n"); return 2; }
        if (std::strcmp(r, "Hello, Bob") != 0) { std::printf("FAIL: content\n"); free(r); return 2; }
        free(r);
    }
    std::printf("OK\n");
    return 0;
}
