# c06 split_csv — answer key

```cpp
#include <string>
#include <vector>
std::vector<std::string> split_csv(const std::string& line) {
    std::vector<std::string> out;
    std::string cur;
    size_t i = 0, n = line.size();
    while (true) {
        cur.clear();
        if (i < n && line[i] == '"') {           // quoted field
            ++i;
            while (i < n) {
                if (line[i] == '"') {
                    if (i + 1 < n && line[i+1] == '"') { cur.push_back('"'); i += 2; }
                    else { ++i; break; }
                } else cur.push_back(line[i++]);
            }
            while (i < n && line[i] != ',') ++i;  // skip to delimiter
        } else {                                  // unquoted field
            while (i < n && line[i] != ',') cur.push_back(line[i++]);
        }
        out.push_back(cur);
        if (i < n && line[i] == ',') { ++i; continue; }
        break;
    }
    return out;
}
```

Checks: empty line -> {""}; empty fields (leading/middle/trailing); quoted
comma; doubled-quote escaping; empty quoted field. Auto-graded.
