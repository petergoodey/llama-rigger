Implement this C++ function exactly:

```cpp
#include <string>
#include <vector>
/* Split one line of RFC4180-style CSV into fields.
   - Fields are separated by commas.
   - A field may be wrapped in double quotes; inside a quoted field a comma
     is literal and a doubled quote "" denotes a single literal quote.
   - Quotes are only special at the start of a field.
   - An empty line yields one empty field: {""}.
   Return the field values with surrounding quotes removed and "" unescaped. */
std::vector<std::string> split_csv(const std::string& line);
```

Return only the function (plus any `#include` it needs) in one `cpp` code block.
Do not write a `main`.
