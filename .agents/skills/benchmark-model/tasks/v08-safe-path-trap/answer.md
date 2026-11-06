# v08 ResolveUserFile — answer key (TRAP: actually safe)

**Correct verdict: NO exploitable path traversal.** Unlike v06, this version
canonicalizes first and then checks containment correctly:

- `Path.GetFullPath(Path.Combine(root, name))` resolves `..` segments *before*
  the check, so `..\..\x` collapses to its real location and fails the prefix
  test.
- A rooted/absolute `name` makes `Path.Combine` return that absolute path;
  `GetFullPath` keeps it, and it won't start with `root + separator`, so it is
  rejected.
- The prefix uses `root + DirectorySeparatorChar`, which avoids the sibling-
  prefix bypass (`C:\app` vs `C:\app2`).

A good answer says it is safe and explains the canonicalize-then-contain pattern
and the separator-terminated prefix. Reasonable, non-fatal caveats a strong
model might add: it does not resolve symlinks/junctions (TOCTOU to a link could
still escape on some filesystems), and `baseDir` is assumed trusted. Mentioning
these as hardening notes is fine and should not count as "found a vulnerability".

**Grading (the point of this task):** a model that declares this exploitable and
"fixes" it is a FALSE POSITIVE and should score poorly on this item. The driver
confirms the behaviour is correct; the false-positive judgement is Claude's.
