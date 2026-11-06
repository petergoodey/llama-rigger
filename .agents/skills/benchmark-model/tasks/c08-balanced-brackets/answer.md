# c08 IsBalanced — answer key

```csharp
using System.Collections.Generic;
public static class Solution
{
    public static bool IsBalanced(string s)
    {
        var st = new Stack<char>();
        foreach (char c in s)
        {
            if (c == '(' || c == '[' || c == '{') st.Push(c);
            else if (c == ')' || c == ']' || c == '}')
            {
                if (st.Count == 0) return false;
                char o = st.Pop();
                if ((c == ')' && o != '(') ||
                    (c == ']' && o != '[') ||
                    (c == '}' && o != '{')) return false;
            }
        }
        return st.Count == 0;
    }
}
```

Checks: empty; nesting; type mismatch `(]`; crossed `([)]`; unclosed/extra;
non-bracket characters ignored. Auto-graded.
