`ResolveUserFile` turns an untrusted file `name` into a path inside `baseDir`,
which the server will then open. The intent is that the returned path can never
be outside `baseDir`.

Do the following:
1. State whether the method has a security vulnerability, and name its class.
2. Explain the root cause and give concrete `name` values an attacker would use
   to read files outside `baseDir`, and what they could achieve.
3. Provide a corrected version inside a class named `Solution`, with the **same
   signature**: it must return the resolved absolute path when it stays within
   `baseDir`, and `null` when `name` would escape (including `..` segments and
   absolute/rooted paths).

If the code is actually safe, say so and explain why. Return the `Solution`
class in one `csharp` code block. Do not write a `Main`.
