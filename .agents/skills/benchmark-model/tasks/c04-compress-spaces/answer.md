# c04 compress_spaces — answer key

```cpp
#include <string>
#include <cctype>
std::string compress_spaces(const std::string& s) {
    std::string out;
    bool in_ws = false, started = false;
    for (unsigned char c : s) {
        if (std::isspace(c)) { in_ws = true; continue; }
        if (in_ws && started) out.push_back(' ');
        out.push_back((char)c);
        started = true; in_ws = false;
    }
    return out;
}
```

Checks: empty / all-whitespace -> ""; trim both ends; collapse mixed
tab/newline/formfeed runs to one space; single spaces preserved. Use
`unsigned char` with `isspace` to avoid negative-char UB. Auto-graded.
