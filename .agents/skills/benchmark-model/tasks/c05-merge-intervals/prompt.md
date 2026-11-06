Implement this C++ function exactly:

```cpp
#include <vector>
#include <utility>
/* Each pair is a closed interval [first, second] with first <= second.
   Input is unsorted and may be empty. Return the minimal set of merged
   intervals, sorted ascending by start. Intervals that merely touch
   (e.g. [1,2] and [2,3]) count as overlapping and must merge into [1,3]. */
std::vector<std::pair<int,int>>
merge_intervals(std::vector<std::pair<int,int>> intervals);
```

Return only the function (plus any `#include` it needs) in one `cpp` code block.
Do not write a `main`.
