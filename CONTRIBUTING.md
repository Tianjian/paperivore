# Contributing to Paperivore

The best contribution is **a new paper on the bench**. Code fixes are welcome too, but a
case that survives a real paper is worth more than a refactor.

## Bring prey (add a benchmark case)

A paper qualifies if it has:

1. **numbers**, not only contour plots — something a solver can be compared against;
2. **complete geometry and boundary conditions** — a benchmark you have to guess is not a
   benchmark;
3. an **open licence**, so the PDF may live in `papers/`;
4. **internal consistency** — check the paper's own tables against each other before you
   spend a day modelling it.

Then open a PR with:

```
docs/<case>-report.md        parameters · method · result · verdict · limits
scripts/<case>_*.py          the runnable pipeline (argparse, --job <dir>)
results/<case>/              result.json + key png/csv/step (no meshes, no .frd)
papers/<paper>.pdf           + one row in papers/README.md
tests/test_<case>.py         golden values, pure python, no solver required
```

### Report template

```markdown
# <case>

## 0. 结论速览        (ledger table: what was compared, paper value, local value, error, verdict)
## 1. 论文与参数      (full citation, DOI, every extracted parameter)
## 2. 模型与边界条件   (what you built, unit system, assumptions)
## 3. 验证结果        (per-point comparison, not just the aggregate)
## 4. 发现的问题      (solver bug / reference bug / paper bug — with evidence)
## 5. 2D/3D 输出      (which files, what they show)
## 6. 局限            (what this case does NOT prove)
## 7. 复现命令        (exact command block)
```

## House rules

1. **Three verdicts**: `pass`, `fail`, `not verifiable`. No fourth category.
2. **Never tune to match.** If a constant is adjusted until the error closes, the case is
   worthless. Physical justifications must be re-validated independently.
3. **Audit the paper.** Reference models get the same scrutiny as the solver.
4. **Keep the failure.** A failed case stays in the ledger with its numbers.
5. **Every fix gets a regression** in `tests/` or in `skill/cad-cae/SKILL.md`.

## Code style

- Python 3.11+, `from __future__ import annotations`, no global state between scripts.
- Every script takes `--job <dir>` and writes only inside that directory.
- Structural cases use `mm – N – MPa – t`; thermal cases use SI. Say which in the header.
- Keep the pure-python core importable without the CAD/solver stack — CI depends on it.

## Running the checks

```powershell
pip install numpy scipy pytest
pytest -q
python -m compileall -q scripts
```

## Reporting a bad paper (not a bug)

If a paper's tables cannot be reproduced by *any* consistent interpretation, open an issue
with the numbers and the arithmetic that fails. Those findings are part of the product —
three of the six rounds ended this way.
