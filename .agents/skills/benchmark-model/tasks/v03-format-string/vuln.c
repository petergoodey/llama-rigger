#include <stddef.h>
#include <stdio.h>

/* Build a log line "[log] <user>" into dst (capacity cap). */
void render_log(char *dst, size_t cap, const char *user) {
    char line[256];
    snprintf(line, sizeof line, user);
    snprintf(dst, cap, "[log] %s", line);
}
