#include <stddef.h>
#include <stdio.h>
#include <string.h>

void render_log(char *dst, size_t cap, const char *user);

/* Build-check driver only (task is judge_only). A correct fix prints the
   literal text including any '%' rather than interpreting it. */
int main(void) {
    char out[128];
    render_log(out, sizeof out, "hello");
    render_log(out, sizeof out, "100%% done %s %n");
    printf("%s\n", out);
    return 0;
}
