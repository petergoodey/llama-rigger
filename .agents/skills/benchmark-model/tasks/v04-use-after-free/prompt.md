`make_greeting` returns a newly allocated, NUL-terminated string
`"Hello, <name>"` that the caller must `free`. `name` has `n` bytes (not
necessarily NUL-terminated). `n` may be 0.

Do the following:
1. State whether the function has a security vulnerability, and name its class.
2. Explain the root cause and the exact input that triggers it, and what an
   attacker could achieve.
3. Provide a corrected version with the **same signature**. The returned
   pointer must always be either a valid heap buffer the caller can read and
   `free`, or `NULL` — never a dangling pointer.

If the code is actually safe, say so and explain why. Return the corrected (or
unchanged) function in a single `cpp` code block.
