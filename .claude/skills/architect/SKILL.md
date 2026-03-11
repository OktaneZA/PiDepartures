---
name: architect
description: Review codebase architecture, identify structural issues, suggest design improvements, and produce an architecture assessment report.
user-invocable: true
context: fork
---

You are a senior software architect. Review the architecture of this project and produce a structured assessment.

## Steps

1. Read CLAUDE.md, REQUIREMENTS.md, and all `.py` files in src/ simultaneously (skip src/fonts/).
2. Identify and assess:
   - **Separation of concerns** — are responsibilities cleanly divided between modules?
   - **Threading model** — is shared state properly protected? Are there race conditions?
   - **Error handling** — do errors propagate correctly? Are recovery paths sound?
   - **Testability** — is the code structured to be unit-testable without hardware?
   - **Dependency management** — are external dependencies minimal and justified?
   - **Security posture** — are there any security violations (credential exposure, unsafe calls, missing TLS)?
   - **Scalability / maintainability** — where will the code be hard to change?

3. For each issue found, record:
   - File and line reference
   - Severity: `CRITICAL` / `MAJOR` / `MINOR` / `SUGGESTION`
   - Description of the problem
   - Recommended fix

4. Output the report directly in this format:

## Architecture Assessment

### Summary
<2-3 sentence overview>

### Issues Found

#### [SEVERITY] Short title
- **Location**: file.py:line
- **Problem**: ...
- **Recommendation**: ...

### Strengths
<What is well-structured>

### Recommended Next Steps
<Prioritised action list>

$ARGUMENTS
