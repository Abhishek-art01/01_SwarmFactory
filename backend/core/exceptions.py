"""
core/exceptions.py
------------------
All custom exception types for Swarm Factory.
Import these instead of raising bare Exception so errors are typed and catchable.
"""


class SwarmFactoryError(Exception):
    """Base exception for all Swarm Factory errors."""


class JobNotFoundError(SwarmFactoryError):
    """Raised when a job_id does not exist in Redis."""
    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        super().__init__(f"Job not found: {job_id}")


class AgentError(SwarmFactoryError):
    """Raised when an agent fails after all retries."""
    def __init__(self, agent_name: str, reason: str) -> None:
        self.agent_name = agent_name
        super().__init__(f"Agent '{agent_name}' failed: {reason}")


class QualityGateError(SwarmFactoryError):
    """Raised when the quality gate blocks a low-quality output."""
    def __init__(self, score: int, issues: list) -> None:
        self.score = score
        self.issues = issues
        super().__init__(f"Quality gate failed: score {score}/10")


class StorageError(SwarmFactoryError):
    """Raised on Redis or disk storage failures."""


class DeploymentError(SwarmFactoryError):
    """Raised when GitHub push or Azure deployment fails."""
