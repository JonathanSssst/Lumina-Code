from __future__ import annotations

from dataclasses import dataclass

from lumina.types import Usage


@dataclass
class BudgetSnapshot:
    total_tokens: int
    max_tokens: int
    iterations: int
    max_iterations: int
    tool_calls: int
    exhausted: bool


class TokenBudget:
    """Tracks token consumption and iteration limits; stops runaway agents."""

    def __init__(self, max_tokens: int, max_iterations: int) -> None:
        self.max_tokens = max_tokens
        self.max_iterations = max_iterations
        self.iterations = 0
        self.tool_calls = 0
        self.usage = Usage()

    def record(self, usage: Usage, tool_calls: int = 0) -> None:
        self.usage = self.usage + usage
        self.iterations += 1
        self.tool_calls += tool_calls

    @property
    def total_tokens(self) -> int:
        return self.usage.total_tokens

    @property
    def exhausted(self) -> bool:
        return self.iterations >= self.max_iterations or (
            self.max_tokens > 0 and self.total_tokens >= self.max_tokens
        )

    def snapshot(self) -> BudgetSnapshot:
        return BudgetSnapshot(
            total_tokens=self.total_tokens,
            max_tokens=self.max_tokens,
            iterations=self.iterations,
            max_iterations=self.max_iterations,
            tool_calls=self.tool_calls,
            exhausted=self.exhausted,
        )
