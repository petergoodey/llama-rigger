# c07 CompareVersions — answer key

```csharp
public static class Solution
{
    public static int CompareVersions(string a, string b)
    {
        var pa = a.Split('.');
        var pb = b.Split('.');
        int n = Math.Max(pa.Length, pb.Length);
        for (int i = 0; i < n; i++)
        {
            int va = i < pa.Length ? int.Parse(pa[i]) : 0;
            int vb = i < pb.Length ? int.Parse(pb[i]) : 0;
            if (va != vb) return va < vb ? -1 : 1;
        }
        return 0;
    }
}
```

Checks: numeric (not lexical) comparison ("1.10" > "1.2"); missing trailing
components treated as 0; leading zeros ("1.01" == "1.1"). Auto-graded.
