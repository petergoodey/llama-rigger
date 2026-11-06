#include <string>
#include <cstdio>

std::string compress_spaces(const std::string& s);

static int fails = 0;
static void chk(bool cond, const char* msg) {
    if (!cond) { std::printf("FAIL: %s\n", msg); fails++; }
}

int main() {
    chk(compress_spaces("") == "", "empty");
    chk(compress_spaces("   ") == "", "all spaces");
    chk(compress_spaces("hello") == "hello", "no change");
    chk(compress_spaces("  hello  ") == "hello", "trim");
    chk(compress_spaces("a   b") == "a b", "collapse middle");
    chk(compress_spaces("a\t\t b\n\nc") == "a b c", "mixed ws");
    chk(compress_spaces(" \t a \r\n b \f ") == "a b", "lead/trail mixed");
    chk(compress_spaces("one two three") == "one two three", "single spaces kept");
    if (fails == 0) std::printf("ALL_PASS\n");
    return fails ? 1 : 0;
}
