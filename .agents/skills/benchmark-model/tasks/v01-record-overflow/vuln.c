#include <stddef.h>
#include <string.h>

/* Parse a length-prefixed record. in[0] is the claimed payload length;
   the payload follows. out is a 32-byte buffer. Returns payload length. */
int parse_record(const unsigned char *in, size_t in_len, char out[32]) {
    unsigned char len = in[0];
    memcpy(out, in + 1, len);
    out[len] = '\0';
    return (int)len;
}
