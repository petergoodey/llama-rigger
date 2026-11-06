# v07 copy_field — answer key (TRAP: actually safe)

**Correct verdict: NO exploitable vulnerability.** This resembles the classic
unbounded-copy bug (v01) but the bounds are correct:

- `outcap == 0` is rejected up front, so `outcap - 1` never underflows.
- `len` is clamped to `outcap - 1` before the copy, so `memcpy` writes at most
  `outcap - 1` bytes and `out[len]` writes at most `out[outcap-1]` — both inside
  the buffer.
- The stated caller contract (src has at least `min(len, outcap-1)` readable
  bytes) means the clamped read is in-bounds too.

A good answer says it is safe and explains the clamp + the `outcap==0` guard. It
is fine to note the function trusts its caller for `src`'s readable length (a
documented precondition, not a bug in this function).

**Grading (the point of this task):** a model that invents a vulnerability here
(e.g. "unbounded memcpy", "overflow") is a FALSE POSITIVE and should score
poorly on this item, even though its "fixed" code may still compile and pass.
Auto-grade confirms the code still works (benign + stress both ASan-clean); the
false-positive judgement is made by Claude.
