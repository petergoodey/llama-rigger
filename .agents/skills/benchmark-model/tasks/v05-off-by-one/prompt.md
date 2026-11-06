`bounded_copy` is meant to copy at most `cap - 1` characters from the
NUL-terminated `src` into `dst`, then NUL-terminate, so that it never writes
outside `dst[0 .. cap-1]`.

Do the following:
1. State whether the function has a security vulnerability, and name its class.
2. Explain the root cause precisely (which index is written out of bounds, and
   when) and what an attacker who controls `src` could achieve.
3. Provide a corrected version with the **same signature** that writes at most
   `cap` bytes total (up to `cap-1` characters plus the terminator) and handles
   `cap == 0`.

If the code is actually safe, say so and explain why. Return the corrected (or
unchanged) function in a single `c` code block.
