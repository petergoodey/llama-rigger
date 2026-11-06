`copy_field` copies up to `len` bytes of `src` into `out`, where `out` has
capacity `outcap`. Callers pass an attacker-influenced `len`. Assume the caller
guarantees `src` has at least `min(len, outcap-1)` readable bytes.

Do the following:
1. State whether the function has a security vulnerability, and name its class
   if so.
2. If it is vulnerable, explain the root cause, the triggering input, and the
   impact. If it is NOT vulnerable, explain precisely why each potential
   overflow is prevented.
3. Provide a corrected version with the **same signature** if a fix is needed;
   otherwise return the function unchanged.

Return the function in a single `c` code block.
