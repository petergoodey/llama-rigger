using System;
using System.IO;

class Program
{
    static int fails = 0;
    static void Chk(bool cond, string msg)
    {
        if (!cond) { Console.WriteLine("FAIL: " + msg); fails++; }
    }

    static int Main()
    {
        char sep = Path.DirectorySeparatorChar;
        string baseDir = Path.Combine(Path.GetTempPath(), "mb_v06_" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(baseDir);
        string baseFull = Path.GetFullPath(baseDir);

        // benign: a normal file resolves inside baseDir
        string r = Solution.ResolveUserFile(baseDir, "report.txt");
        Chk(r != null, "benign returned null");
        if (r != null)
        {
            string full = Path.GetFullPath(r);
            Chk(full.StartsWith(baseFull + sep) &&
                full.Equals(Path.Combine(baseFull, "report.txt")),
                "benign not inside baseDir: " + full);
        }

        // malicious cases must NOT resolve to a path outside baseDir
        string[] evil = {
            ".." + sep + ".." + sep + "etc_passwd",
            ".." + sep + "mb_secret.txt",
            Path.Combine(Path.GetTempPath(), "mb_outside.txt"),   // rooted/absolute
            "sub" + sep + ".." + sep + ".." + sep + "escape.txt",
        };
        foreach (string name in evil)
        {
            string g = Solution.ResolveUserFile(baseDir, name);
            if (g != null)
            {
                string full = Path.GetFullPath(g);
                Chk(full.StartsWith(baseFull + sep),
                    "escaped baseDir via '" + name + "' -> " + full);
            }
        }

        try { Directory.Delete(baseDir, true); } catch { }
        if (fails == 0) Console.WriteLine("ALL_PASS");
        return fails == 0 ? 0 : 1;
    }
}
