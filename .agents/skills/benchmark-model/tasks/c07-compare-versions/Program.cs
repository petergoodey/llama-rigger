using System;

class Program
{
    static int fails = 0;
    static void Chk(bool cond, string msg)
    {
        if (!cond) { Console.WriteLine("FAIL: " + msg); fails++; }
    }

    static int Main()
    {
        Chk(Solution.CompareVersions("1.0", "1.0") == 0, "equal");
        Chk(Solution.CompareVersions("1.0", "1") == 0, "trailing zero == missing");
        Chk(Solution.CompareVersions("1", "1.0.0") == 0, "missing == zeros");
        Chk(Solution.CompareVersions("1.2", "1.10") == -1, "numeric not lexical");
        Chk(Solution.CompareVersions("1.10", "1.2") == 1, "numeric not lexical rev");
        Chk(Solution.CompareVersions("2.0", "1.9.9") == 1, "major wins");
        Chk(Solution.CompareVersions("1.0.1", "1") == 1, "extra component");
        Chk(Solution.CompareVersions("0", "0.0") == 0, "zeros");
        Chk(Solution.CompareVersions("1.01", "1.1") == 0, "leading zeros numeric");
        if (fails == 0) Console.WriteLine("ALL_PASS");
        return fails == 0 ? 0 : 1;
    }
}
