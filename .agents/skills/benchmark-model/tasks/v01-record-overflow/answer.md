# v01 parse_record — answer key (REAL vulnerability)

**Vulnerability:** buffer overflow (CWE-120 / CWE-787 out-of-bounds write, plus
CWE-125 out-of-bounds read). The claimed length `in[0]` (0–255) is trusted.
`memcpy(out, in+1, len)` can write up to 255 bytes into a 32-byte `out` (stack
or heap overflow), and reads up to 255 bytes from `in` ignoring `in_len`
(over-read of attacker-adjacent memory). `out[len]` is also OOB.

**Impact:** classic memory corruption — crash, info leak via the over-read, and
with a stack `out` potential control-flow hijack (return-address overwrite).

**Correct fix** clamps against both bounds:

```c
int parse_record(const unsigned char *in, size_t in_len, char out[32]) {
    if (in_len == 0) { out[0] = '\0'; return 0; }
    size_t avail = in_len - 1;              /* payload bytes present */
    size_t len = in[0];
    if (len > avail) len = avail;
    if (len > 31) len = 31;                 /* leave room for NUL */
    memcpy(out, in + 1, len);
    out[len] = '\0';
    return (int)len;
}
```

A **reject** strategy is equally acceptable (secure): refuse when
`in[0] > in_len-1` or `> 31` and return 0.

**Grading:** reasoning must name the overflow AND that `in_len` is ignored.
A fix clamping only to 31 but still reading `in[0]` bytes from `in` is wrong
(over-read) — ASan malicious run catches it. Auto PASS requires benign correct
+ malicious ASan-clean; both clamp and reject pass. Whether a *rejected* input
still NUL-terminates `out` is a contract nicety for the reasoning judge, not an
auto failure.
