# c05 merge_intervals — answer key

```cpp
#include <vector>
#include <utility>
#include <algorithm>
std::vector<std::pair<int,int>>
merge_intervals(std::vector<std::pair<int,int>> intervals) {
    std::sort(intervals.begin(), intervals.end());
    std::vector<std::pair<int,int>> out;
    for (auto& iv : intervals) {
        if (!out.empty() && iv.first <= out.back().second)
            out.back().second = std::max(out.back().second, iv.second);
        else
            out.push_back(iv);
    }
    return out;
}
```

Checks: empty; sort-before-merge (unsorted input); touching intervals merge
(`<=`, not `<`); nested intervals; point intervals. Auto-graded.
