# What this PR does

<!-- one or two lines -->

## Type

- [ ] new prey (benchmark case)
- [ ] toolchain fix
- [ ] reference-model fix (the *validator* was wrong, not the solver)
- [ ] documentation / result artefact
- [ ] CI or packaging

## If it is a new case

- [ ] report in `docs/` follows the template in CONTRIBUTING.md
- [ ] `results/<case>/result.json` contains `fea`, `theory` and `error`
- [ ] paper added to `papers/` **and** one row in `papers/README.md` (with licence)
- [ ] golden values pinned in `tests/test_<case>.py` (pure python)
- [ ] verdict is `pass`, `fail` or `not verifiable` — no fourth option

## Honesty checklist

- [ ] no constant was tuned until the error closed
- [ ] if the paper's own numbers are inconsistent, the arithmetic is in the report
- [ ] the limitation section says what this does **not** prove
- [ ] failing numbers are kept, not removed

## Numbers

| quantity | reference | this PR | error |
|---|---|---|---|
| | | | |
