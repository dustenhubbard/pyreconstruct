- **Every trace now carries a stable in-memory id from the moment its series
  is opened, derived from the trace's own stored content.** Each `Series` owns
  one `TraceIDIssuer`, and `Section` joins the issuer's `tid-v1` derivation to
  the traces it builds at load, so two independent opens of the same file agree
  on every id with no save between — the property a random id minted at load
  cannot have, and the recorded reason legacy flags deduplicated wrongly.
  Traces created during a session still receive fresh opaque ids. Uniqueness
  is enforced across the whole series, not per section. Re-deriving a section
  (`loadSection` builds a fresh `Section` on every call) answers from the
  issuer's own record rather than re-hashing past its earlier answer, so a
  scroll cannot reissue a trace's id. **No byte of any `.jser` changes**: the
  id lives in the columnar store only, and a save is byte-identical to the
  previous build, compared by hashing every byte written. Measured on a real
  125,218-trace series, the derivation costs 15.7 microseconds per trace on
  first load (1.96 s for the whole series, inside a 5.66 s open) and 6.7
  microseconds per trace on re-load, flat in series size.
