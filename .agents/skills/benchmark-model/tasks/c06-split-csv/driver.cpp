#include <string>
#include <vector>
#include <cstdio>

std::vector<std::string> split_csv(const std::string& line);

static int fails = 0;
using V = std::vector<std::string>;
static void chk(bool c, const char* m) { if (!c) { std::printf("FAIL: %s\n", m); fails++; } }
static bool eq(const V& a, const V& b) {
    if (a.size() != b.size()) return false;
    for (size_t i = 0; i < a.size(); i++) if (a[i] != b[i]) return false;
    return true;
}

int main() {
    chk(eq(split_csv(""), {""}), "empty -> one empty");
    chk(eq(split_csv("a,b,c"), {"a","b","c"}), "plain");
    chk(eq(split_csv("a,,c"), {"a","","c"}), "empty middle");
    chk(eq(split_csv(",x"), {"","x"}), "leading empty");
    chk(eq(split_csv("x,"), {"x",""}), "trailing empty");
    chk(eq(split_csv("\"a,b\",c"), {"a,b","c"}), "quoted comma");
    chk(eq(split_csv("\"he said \"\"hi\"\"\",y"), {"he said \"hi\"","y"}), "escaped quotes");
    chk(eq(split_csv("\"\",z"), {"","z"}), "empty quoted");
    chk(eq(split_csv("\"plain\""), {"plain"}), "single quoted");
    if (fails == 0) std::printf("ALL_PASS\n");
    return fails ? 1 : 0;
}
