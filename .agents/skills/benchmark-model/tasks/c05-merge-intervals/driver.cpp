#include <vector>
#include <utility>
#include <cstdio>

std::vector<std::pair<int,int>>
merge_intervals(std::vector<std::pair<int,int>> intervals);

static int fails = 0;
using V = std::vector<std::pair<int,int>>;
static void chk(bool c, const char* m) { if (!c) { std::printf("FAIL: %s\n", m); fails++; } }
static bool eq(const V& a, const V& b) {
    if (a.size() != b.size()) return false;
    for (size_t i = 0; i < a.size(); i++) if (a[i] != b[i]) return false;
    return true;
}

int main() {
    chk(eq(merge_intervals({}), {}), "empty");
    chk(eq(merge_intervals({{1,3}}), {{1,3}}), "single");
    chk(eq(merge_intervals({{1,3},{2,6},{8,10},{15,18}}),
           {{1,6},{8,10},{15,18}}), "classic");
    chk(eq(merge_intervals({{1,2},{2,3}}), {{1,3}}), "touching");
    chk(eq(merge_intervals({{5,6},{1,2},{3,4}}), {{1,2},{3,4},{5,6}}), "unsorted disjoint");
    chk(eq(merge_intervals({{1,10},{2,3},{4,5}}), {{1,10}}), "nested");
    chk(eq(merge_intervals({{1,4},{4,4}}), {{1,4}}), "point inside");
    chk(eq(merge_intervals({{1,1},{2,2}}), {{1,1},{2,2}}), "disjoint points");
    if (fails == 0) std::printf("ALL_PASS\n");
    return fails ? 1 : 0;
}
