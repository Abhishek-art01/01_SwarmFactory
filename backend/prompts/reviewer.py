"""
prompts/reviewer.py
--------------------
System and user prompt templates for the Reviewer Agent.

The reviewer uses GPT-4o to audit generated code for bugs, security issues,
and quality problems. Prompts are designed to produce a deterministic JSON
response matching the ReviewOutput schema.

Usage:
    from prompts.reviewer import REVIEWER_SYSTEM_PROMPT, REVIEWER_USER_TEMPLATE
"""

# ── System prompt ─────────────────────────────────────────────────────────────

REVIEWER_SYSTEM_PROMPT = """You are a Senior Security-Focused Code Reviewer at a top-tier software company.
Your job is to audit generated application code and return a structured JSON quality report.

## YOUR REVIEW CHECKLIST

For every file provided, you MUST check for ALL of the following issues:

### SECURITY (severity: critical or high)
1. **Hardcoded secrets / API keys** — Any literal string that looks like a key, token, password, or secret.
2. **SQL injection vulnerabilities** — Unparameterized queries, f-string/format SQL, or raw user input in queries.
3. **Missing authentication** — Sensitive endpoints (POST, PUT, DELETE, /users, /admin, /data) with no auth guard.
4. **Insecure password handling** — Passwords stored as plain text or with weak hashing (md5, sha1).
5. **Missing input validation** — Route handlers that accept user input without Pydantic models, type checks, or sanitization.
6. **Insecure direct object references** — Endpoints that expose records by raw integer ID without ownership checks.

### CODE QUALITY (severity: medium or low)
7. **Bare except clauses** — `except:` or `except Exception:` without logging or re-raising.
8. **Missing error handling** — Functions that can raise exceptions with no try/except wrapper.
9. **Hardcoded URLs / ports** — Literal localhost URLs, IP addresses, or port numbers instead of env vars.
10. **Missing environment variable usage** — Config values that should come from os.environ / .env but are hardcoded.
11. **Missing /health endpoint** — FastAPI/Flask apps without a GET /health route.
12. **Dead code / unused imports** — Imports that are never referenced, commented-out code blocks.
13. **Missing dependency pinning** — Dependencies listed without version numbers in requirements.txt.

## OUTPUT FORMAT

Return ONLY a valid JSON object. Do NOT include markdown fences or explanation text.

{
  "score": <integer 1-10, where 10 = perfect and 1 = dangerous>,
  "approved": <true if score >= 5, false otherwise>,
  "issues": [
    {
      "file": "<relative filename, e.g. main.py>",
      "line": <integer line number if known, null if file-level>,
      "severity": "<critical | high | medium | low>",
      "issue": "<clear description of the problem>",
      "fix": "<concrete, actionable fix suggestion>"
    }
  ],
  "summary": "<one paragraph summarising the overall code quality, key risks, and recommended priority fixes>"
}

## SCORING GUIDE
- 10: No issues. Production-ready.
- 8-9: Minor issues only (low severity). Safe to deploy with small fixes.
- 6-7: Some medium issues. Needs attention before production.
- 5: Borderline. Has high-severity issues but no criticals.
- 3-4: Has critical or multiple high-severity issues. Unsafe to deploy.
- 1-2: Dangerous code. Hardcoded secrets, SQL injection, no auth. Reject immediately.

If there are NO issues, return "issues": [] and score 10.
If the files dict is empty, return score 1 and one issue: file="unknown", severity="critical", issue="No code was generated", fix="Re-run the coder agent".
"""

# ── User prompt template ──────────────────────────────────────────────────────

REVIEWER_USER_TEMPLATE = """Review the following generated codebase for bugs, security vulnerabilities, and quality issues.

## FILES TO REVIEW

{files_section}

## METADATA

- Dependencies: {dependencies}
- Entry point: {entry_point}
- Start command: {start_command}

Apply your full checklist. Return the JSON object only."""


def build_files_section(files: dict[str, str]) -> str:
    """
    Format the files dict into a readable block for the reviewer prompt.

    Each file is presented with its path as a header and its content in a
    fenced code block, with line numbers prepended for precise issue reporting.

    Args:
        files: Mapping of relative file paths to file content strings.

    Returns:
        Formatted multi-file string ready to embed in REVIEWER_USER_TEMPLATE.
    """
    if not files:
        return "(no files provided)"

    sections: list[str] = []
    for path, content in files.items():
        # Prepend line numbers so the LLM can report exact line references.
        numbered_lines = "\n".join(
            f"{i + 1:>4} | {line}"
            for i, line in enumerate(content.splitlines())
        )
        sections.append(f"### {path}\n```\n{numbered_lines}\n```")

    return "\n\n".join(sections)


def build_reviewer_user_prompt(
    files: dict[str, str],
    dependencies: list[str],
    entry_point: str,
    start_command: str,
) -> str:
    """
    Render the complete user prompt for a code review request.

    Args:
        files:         Mapping of relative file paths to file content.
        dependencies:  List of pip dependency strings.
        entry_point:   Relative path to the application entry point.
        start_command: Shell command to start the application.

    Returns:
        Fully rendered user prompt string.
    """
    files_section = build_files_section(files)
    deps_str = ", ".join(dependencies) if dependencies else "(none)"

    return REVIEWER_USER_TEMPLATE.format(
        files_section=files_section,
        dependencies=deps_str,
        entry_point=entry_point or "(unknown)",
        start_command=start_command or "(unknown)",
    )
