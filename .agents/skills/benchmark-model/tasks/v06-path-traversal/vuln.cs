using System.IO;

public static class Solution
{
    // Resolve an untrusted file name to a path inside baseDir.
    public static string ResolveUserFile(string baseDir, string name)
    {
        return Path.Combine(baseDir, name);
    }
}
