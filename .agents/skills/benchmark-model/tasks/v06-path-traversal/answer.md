# v06 ResolveUserFile — answer key (REAL vulnerability)

**Vulnerability:** path traversal (CWE-22). `Path.Combine(baseDir, name)` does
no containment check. `name = "..\..\etc_passwd"` climbs out of `baseDir`; and
if `name` is rooted/absolute (e.g. `C:\Windows\win.ini` or `/etc/passwd`),
`Path.Combine` discards `baseDir` entirely and returns the attacker's path.

**Impact:** read (or write, depending on caller) of arbitrary files outside the
intended directory — credential/secret disclosure, config tampering.

**Correct fix:** canonicalize, then verify containment against the full base
path plus a separator (to avoid the `C:\app` vs `C:\app2` prefix trap):

```csharp
using System.IO;
public static class Solution
{
    public static string ResolveUserFile(string baseDir, string name)
    {
        string root = Path.GetFullPath(baseDir);
        string full = Path.GetFullPath(Path.Combine(root, name));
        string prefix = root.EndsWith(Path.DirectorySeparatorChar.ToString())
            ? root : root + Path.DirectorySeparatorChar;
        return full.StartsWith(prefix, StringComparison.Ordinal) ? full : null;
    }
}
```

**Grading:** reasoning must name path traversal AND mention both `..` and the
rooted-path case (Path.Combine discarding baseDir) for full credit. The driver
(Program.cs) is the exploit test: benign resolves inside, every evil name must
return null or stay within baseDir. Auto PASS = build + all assertions pass.
