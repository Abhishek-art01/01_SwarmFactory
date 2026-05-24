"""
agents/agent_instances.py
--------------------------
INTEGRATION FIX: Creates singleton agent instances.

swarm_controller.py and parallel_runner.py were written expecting:
    from agents.planner_agent import planner_agent  (instance)

But agents are defined as classes. This module creates instances
so the existing import pattern works without touching friend's code.
"""
from agents.planner_agent import PlannerAgent
from agents.architect_agent import ArchitectAgent
from agents.coder_agent import CoderAgent
from agents.test_agent import TestAgent
from agents.reviewer_agent import ReviewerAgent
from agents.mediator_agent import MediatorAgent
from agents.devops_agent import DevOpsAgent

# Singleton instances — imported by orchestrator
planner_agent   = PlannerAgent()
architect_agent = ArchitectAgent()
coder_agent     = CoderAgent()
test_agent      = TestAgent()
reviewer_agent  = ReviewerAgent()
mediator_agent  = MediatorAgent()
devops_agent    = DevOpsAgent()
