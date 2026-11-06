# v04 make_greeting — answer key (REAL vulnerability)

**Vulnerability:** use-after-free (CWE-416). When `n == 0` the function frees
`buf` and then returns that same freed pointer. Any caller read/write/free of
the result operates on freed memory.

**Trigger:** `n == 0`. **Impact:** UAF read/write — crash, info leak, or
exploitation via heap grooming (the freed chunk can be reallocated with
attacker data before the caller uses it); the caller's later `free(r)` is also
a double free.

**Correct fix:** don't return freed memory. Either drop the special case
entirely (the general path already produces `"Hello, "` for `n == 0`):

```cpp
char *make_greeting(const char *name, size_t n) {
    char *buf = (char *)malloc(7 + n + 1);
    if (!buf) return nullptr;
    std::memcpy(buf, "Hello, ", 7);
    std::memcpy(buf + 7, name, n);
    buf[7 + n] = '\0';
    return buf;
}
```

or `free(buf); return nullptr;` for the `n==0` case. (A NULL return is accepted
by the driver.) Note the original also omits the `malloc` NULL check.

**Grading:** reasoning must identify UAF and that `n==0` is the trigger. ASan
malicious run (n=0) reports heap-use-after-free on the vulnerable version.
Auto PASS requires benign correct + malicious clean.
