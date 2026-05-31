"""tests/unit/test_agents.py — base_agent, agents inherit BaseAgent"""
import sys, pytest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

class TestBaseAgent:
    def test_base_agent_is_abstract(self):
        from agents.base_agent import BaseAgent
        with pytest.raises(TypeError):
            BaseAgent()

    def test_all_agents_have_run_method(self):
        from agents.planner_agent   import PlannerAgent
        from agents.architect_agent import ArchitectAgent
        from agents.coder_agent     import CoderAgent
        from agents.reviewer_agent  import ReviewerAgent
        from agents.mediator_agent  import MediatorAgent
        from agents.devops_agent    import DevOpsAgent
        for Cls in [PlannerAgent,ArchitectAgent,CoderAgent,ReviewerAgent,MediatorAgent,DevOpsAgent]:
            assert callable(getattr(Cls, "run", None))

    def test_agents_inherit_base(self):
        from agents.base_agent      import BaseAgent
        from agents.planner_agent   import PlannerAgent
        from agents.architect_agent import ArchitectAgent
        from agents.coder_agent     import CoderAgent
        for Cls in [PlannerAgent, ArchitectAgent, CoderAgent]:
            assert issubclass(Cls, BaseAgent)
