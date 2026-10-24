# Atlas — Definition of Done

A story is complete only when the relevant items below are satisfied.

## Requirements
- [ ] Story ID and acceptance criteria are known.
- [ ] Implementation matches the approved scope.
- [ ] Edge cases and failure behavior are defined.
- [ ] No silent requirement changes were made.

## Code
- [ ] Changes are small and focused.
- [ ] Public interfaces have suitable type hints.
- [ ] Errors are handled without hiding unexpected failures.
- [ ] No unnecessary abstraction or dependency was added.
- [ ] No secrets or sensitive values are embedded.

## Tests and verification
- [ ] Relevant tests were added or updated.
- [ ] Targeted tests were executed.
- [ ] Broader tests were executed when appropriate.
- [ ] Lint/format/type checks required by the sprint were executed.
- [ ] Results and exit codes were inspected.
- [ ] Live tests and mocked tests are clearly distinguished.
- [ ] Unverified criteria are listed honestly.

## Security
- [ ] Tool permissions are enforced in application code.
- [ ] Untrusted inputs and retrieved content are validated.
- [ ] Resource limits are applied where relevant.
- [ ] Logs and error messages do not expose secrets.
- [ ] Security-related requirements have meaningful tests.

## Documentation and handoff
- [ ] User-facing behavior is documented.
- [ ] Relevant technical documentation is updated.
- [ ] Backlog and status reflect actual state.
- [ ] Known limitations and defects are recorded.
- [ ] Diff was reviewed.
- [ ] Next action is clear.
- [ ] Work stops at the approved sprint boundary.

A generated implementation without verification is `IMPLEMENTED, NOT VERIFIED`, not `VERIFIED`.
