# v05 bounded_copy — answer key (REAL vulnerability)

**Vulnerability:** off-by-one out-of-bounds write (CWE-193 / CWE-787). The loop
guard `i <= cap - 1` lets `i` reach `cap-1` inclusive and fill `dst[0..cap-1]`
(the whole buffer). After the loop `i == cap`, so `dst[i]` writes the NUL at
`dst[cap]` — one byte past the `cap`-byte buffer, whenever `strlen(src) >= cap`.
Additionally, `cap == 0` makes `cap - 1` wrap to `SIZE_MAX`, turning it into an
unbounded overflow.

**Impact:** single-NUL-byte (or large) overflow past the buffer — adjacent heap
metadata / variable corruption, a well-known exploitation primitive; the
`cap==0` case is a full overflow.

**Correct fix:**

```c
void bounded_copy(char *dst, size_t cap, const char *src) {
    if (cap == 0) return;
    size_t i;
    for (i = 0; i + 1 < cap && src[i] != '\0'; i++)
        dst[i] = src[i];
    dst[i] = '\0';
}
```

**Grading:** reasoning must pinpoint the terminator write at `dst[cap]` (not a
vague "buffer overflow"); bonus for catching `cap == 0`. ASan malicious run
catches the overflow. Auto PASS requires benign correct + malicious clean.
