---
name: qa
description: Run the test suite, check code coverage, identify untested paths, and report on overall quality assurance status.
user-invocable: true
context: fork
---

You are a QA engineer. Perform a full quality assurance pass on this project.

## Steps

1. Read CLAUDE.md, REQUIREMENTS.md, and all files in tests/ simultaneously.
2. Run the test suite (skip pip install if requirements already satisfied):
   ```
   pip install -r requirements-dev.txt -q --quiet 2>/dev/null; pytest --tb=short -q 2>&1
   ```
3. Read all `.py` files in src/ to identify code paths NOT covered by tests.
4. Check for the following quality issues:
   - **Test failures** — record any failing tests with error details
   - **Missing test coverage** — public functions/methods with no test
   - **Weak assertions** — tests that pass trivially without validating behaviour
   - **Missing edge cases** — error paths, empty inputs, boundary values not tested
   - **Test isolation** — tests that reference global state, skip cleanup, or depend on execution order
   - **Mocking gaps** — hardware or network calls that aren't mocked

5. Output the report directly in this format:

## QA Report

### Test Run Results
- Total: X | Passed: X | Failed: X | Skipped: X

### Failed Tests
<list with error summary, or "None">

### Coverage Gaps
<list of untested functions/paths with file:line>

### Quality Issues
<list of weak assertions, isolation issues, missing edge cases>

### Recommendations
<prioritised list of tests to add or fix>

$ARGUMENTS
