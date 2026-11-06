# v02 dup_prefix — answer key (REAL vulnerability)

**Vulnerability:** integer truncation leading to undersized allocation and heap
buffer overflow (CWE-131 / CWE-190 / CWE-787). `n + 1` is computed in `size_t`
but cast to `unsigned short`, so for `n >= 65535` the allocation size wraps to a
small value (e.g. n=70000 -> size 4465, or n=65535 -> size 0). `memcpy` then
writes `n` bytes into the far-too-small buffer.

**Impact:** heap overflow with attacker-controlled length and contents — memory
corruption, potential RCE. `malloc(0)` returning NULL can also be mishandled.

**Correct fix** keeps the size in `size_t` and guards the `+1`:

```c
char *dup_prefix(const char *src, size_t n) {
    if (n == SIZE_MAX) return NULL;         /* n+1 would overflow */
    char *buf = (char *)malloc(n + 1);
    if (!buf) return NULL;
    memcpy(buf, src, n);
    buf[n] = '\0';
    return buf;
}
```

**Grading:** reasoning must identify the narrowing cast (not merely "check
malloc"). Fix must allocate `n+1` without truncation. ASan malicious run (n=70000)
catches any residual undersizing. Auto PASS requires benign correct + malicious
clean (returning NULL on the malicious case is also acceptable/clean).
