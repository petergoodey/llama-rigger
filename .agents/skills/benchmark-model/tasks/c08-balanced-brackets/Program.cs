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
        Chk(Solution.IsBalanced("") == true, "empty");
        Chk(Solution.IsBalanced("()") == true, "simple");
        Chk(Solution.IsBalanced("()[]{}") == true, "sequence");
        Chk(Solution.IsBalanced("([{}])") == true, "nested");
        Chk(Solution.IsBalanced("(]") == false, "mismatch");
        Chk(Solution.IsBalanced("([)]") == false, "crossed");
        Chk(Solution.IsBalanced("(") == false, "unclosed");
        Chk(Solution.IsBalanced(")") == false, "lone close");
        Chk(Solution.IsBalanced("a(b)c[d]{e}") == true, "ignore others");
        Chk(Solution.IsBalanced("int f(int a[]) { return a[0]; }") == true, "code-like");
        Chk(Solution.IsBalanced("{{}") == false, "extra open");
        if (fails == 0) Console.WriteLine("ALL_PASS");
        return fails == 0 ? 0 : 1;
    }
}
