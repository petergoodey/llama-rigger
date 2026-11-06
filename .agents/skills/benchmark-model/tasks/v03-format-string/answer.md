# v03 render_log — answer key (REAL vulnerability; judge-graded)

**Vulnerability:** uncontrolled format string (CWE-134). `snprintf(line,
sizeof line, user)` uses attacker-controlled `user` as the format. Specifiers
like `%x`/`%p`/`%s` read and leak stack/memory; `%s` on a bogus pointer crashes;
`%n` **writes** the number of bytes printed to an address taken from the
varargs — a classic write primitive.

**Impact:** information disclosure (stack/memory leak) and, via `%n`, an
arbitrary or semi-arbitrary memory write that can lead to code execution.

**Correct fix:** pass a constant format and the user data as an argument:

```c
void render_log(char *dst, size_t cap, const char *user) {
    snprintf(dst, cap, "[log] %s", user);
}
```

(Or keep the two-step form but `snprintf(line, sizeof line, "%s", user);`.)

**Grading (Claude):** full credit requires naming it a format-string bug AND
explaining `%n`/`%s` specifically (not just "user input is unsafe"). The fix
must stop treating `user` as a format. Auto-grade is build-only.
