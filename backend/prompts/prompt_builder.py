"""
prompt_builder.py — Assembles final prompt strings from parts and runtime context.

Provides a PromptBuilder class that combines static template strings
(from planner.py / architect.py) with dynamic context values at call time.
"""

from typing import Any


class PromptBuilder:
    """
    Assembles a final prompt string by interpolating context variables
    into a template string, and optionally appending extra context sections.

    Usage:
        builder = PromptBuilder(template=PLANNER_USER_TEMPLATE)
        prompt  = builder.build(requirement="Build a REST API...")

    The template string uses standard Python str.format() placeholders,
    e.g. "{requirement}", "{plan_json}".
    """

    def __init__(self, template: str) -> None:
        """
        Store the template for later interpolation.

        Args:
            template: A string with {placeholder} style format variables.
        """
        self._template = template

    def build(self, **context: Any) -> str:
        """
        Interpolate context variables into the stored template.

        Args:
            **context: Keyword arguments matching the {placeholder} names
                       in the template.

        Returns:
            The fully assembled prompt string.

        Raises:
            KeyError: If a required placeholder is missing from context.
        """
        return self._template.format(**context)

    @staticmethod
    def join_sections(*sections: str, separator: str = "\n\n") -> str:
        """
        Concatenate multiple prompt sections with a separator.

        Useful for building a system prompt from ROLE + TASK + FORMAT + EXAMPLE blocks.

        Args:
            *sections:  One or more prompt section strings.
            separator:  String placed between sections (default: double newline).

        Returns:
            A single string with all sections joined.
        """
        return separator.join(s.strip() for s in sections if s.strip())
