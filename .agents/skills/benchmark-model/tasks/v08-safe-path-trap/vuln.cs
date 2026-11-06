using System;
using System.IO;

public static class Solution
{
    // Resolve an untrusted file name to a path inside baseDir, or null if it
    // would escape.
    public static string ResolveUserFile(string baseDir, string name)
    {
        string root = Path.GetFullPath(baseDir);
        string full = Path.GetFullPath(Path.Combine(root, name));
        string prefix = root.EndsWith(Path.DirectorySeparatorChar.ToString())
            ? root
            : root + Path.DirectorySeparatorChar;
        return full.StartsWith(prefix, StringComparison.Ordinal) ? full : null;
    }
}
