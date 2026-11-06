#include <stddef.h>
#include <stdio.h>
#include <string.h>

size_t rle_encode(const unsigned char *in, size_t n,
                  unsigned char *out, size_t outcap);

static int fails = 0;
static void chk(int cond, const char *msg) {
    if (!cond) { printf("FAIL: %s\n", msg); fails++; }
}

int main(void) {
    unsigned char out[600];

    chk(rle_encode((const unsigned char*)"", 0, out, sizeof out) == 0, "empty");

    const unsigned char a[] = {'a','a','a','b'};
    size_t w = rle_encode(a, 4, out, sizeof out);
    chk(w == 4, "aaab len");
    chk(out[0]==3 && out[1]=='a' && out[2]==1 && out[3]=='b', "aaab bytes");

    const unsigned char s[] = {5,5};
    chk(rle_encode(s, 2, out, sizeof out) == 2 && out[0]==2 && out[1]==5, "two 5s");

    /* run of 300 -> split 255 + 45 */
    static unsigned char big[300];
    memset(big, 7, sizeof big);
    w = rle_encode(big, 300, out, sizeof out);
    chk(w == 4, "300 run len");
    chk(out[0]==255 && out[1]==7 && out[2]==45 && out[3]==7, "300 run split");

    /* insufficient capacity -> (size_t)-1, no OOB (ASan-clean build would catch) */
    chk(rle_encode(a, 4, out, 3) == (size_t)-1, "too small cap");

    /* exact capacity */
    chk(rle_encode(a, 4, out, 4) == 4, "exact cap");

    if (fails == 0) printf("ALL_PASS\n");
    return fails ? 1 : 0;
}
