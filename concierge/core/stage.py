"""
Stage: Represents a logical grouping of tools and state.
"""
from typing import Dict, List, Optional, Callable, Type, Any
from dataclasses import dataclass, field
import inspect

from concierge.core.state import State
from concierge.core.construct import is_construct, validate_construct
from concierge.core.tool import Tool, tool


@dataclass
class Context:
    """Context holds global state and metadata."""
    global_state: State = field(default_factory=State)


@dataclass
class Stage:
    """
    A stage represents a logical grouping of tools and state.
    Analogous to a page in a web application.
    
    Each stage has its own local state that is shared by all tools within the stage.
    """
    name: str
    description: str
        
    # Components
    tools: Dict[str, Tool] = field(default_factory=dict)
    
    # Stage-local state (shared by all tools in this stage)
    local_state: State = field(default_factory=State)
    
    # Navigation
    transitions: List[str] = field(default_factory=list)  # Valid next stages
    prerequisites: List[Type] = field(default_factory=list)  # Constructs defining required state

    # Hierarchy
    substages: Dict[str, 'Stage'] = field(default_factory=dict)
    parent: Optional['Stage'] = None
    
    def __post_init__(self):
        """Validate prerequisites are constructs and initialize local state"""
        for prereq in self.prerequisites:
            validate_construct(prereq, f"Stage '{self.name}' prerequisite {prereq.__name__}")
    
    def __hash__(self):
        """Make Stage hashable (for use as dict keys)"""
        return hash(self.name)
    
    def __eq__(self, other):
        """Stage equality based on name"""
        if not isinstance(other, Stage):
            return False
        return self.name == other.name
    
    def add_tool(self, tool: Tool) -> 'Stage':
        """Add a tool to this stage"""
        self.tools[tool.name] = tool
        return self
    
    def add_substage(self, substage: 'Stage') -> 'Stage':
        """Add a substage"""
        substage.parent = self
        self.substages[substage.name] = substage
        return self
    
    def get_available_tools(self, state: State) -> List[Tool]:
        """Get all tools in this stage. All tools are always available."""
        return list(self.tools.values())
    
    def can_transition_to(self, target_stage: str) -> bool:
        """Check if transition to target stage is allowed"""
        return target_stage in self.transitions
    
    def get_missing_prerequisites(
        self, 
        state: State, 
        source_state: Optional[State] = None,
        propagation_config: Optional[Any] = None
    ) -> List[str]:
        """
        Get missing prerequisites for entering this stage (Pydantic models only).
        
        Args:
            state: The global state to check against
            source_state: The source stage's local state (for transitions)
            propagation_config: State propagation config - "all", "none", or list of field names
        
        Returns:
            List of missing field names that won't be satisfied by state propagation
        """
        propagated_fields = set()
        if source_state is not None and propagation_config is not None:
            if propagation_config == "all":
                propagated_fields = set(source_state._data.keys())
            elif propagation_config == "none":
                propagated_fields = set()
            elif isinstance(propagation_config, list):
                propagated_fields = {
                    field for field in propagation_config 
                    if source_state.has(field)
                }
        
        missing = []
        for prereq in self.prerequisites:
            for field_name in prereq.model_fields:
                if not state.has(field_name) and field_name not in propagated_fields:
                    missing.append(field_name)
        
        return missing


# Decorator
class stage:
    """
    Mark a class as a Stage. Methods with @tool become tools.
    
    Args:
        name: Stage name (defaults to class name)
        prerequisites: List of Pydantic constructs required to enter this stage
    
    Note: Transitions are defined in the @workflow decorator, not here!
    """
    
    def __init__(
        self,
        name: Optional[str] = None,
        prerequisites: Optional[List[Type]] = None
    ):
        self.name = name
        self.prerequisites = prerequisites or []
    
    def __call__(self, cls: Type) -> Type:
        stage_name = self.name or cls.__name__.lower()
        stage_desc = inspect.getdoc(cls) or ""
        
        stage_obj = Stage(
            name=stage_name,
            description=stage_desc,
            prerequisites=self.prerequisites
        )
        
        instance = cls()
        
        for attr_name, attr_value in cls.__dict__.items():
            tool_obj = getattr(attr_value, '_concierge_tool', None)
            if tool_obj is not None:
                tool_obj.func = getattr(instance, attr_name)
                stage_obj.add_tool(tool_obj)
        
        stage_obj._original_class = cls
        stage_obj._instance = instance
        return stage_obj

