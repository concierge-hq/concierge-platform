"""
Simple server that routes requests to language engine.
Acts as a gateway between users and the workflow orchestration.
"""
import json
from typing import Dict, Optional
from concierge.core.workflow import Workflow
from concierge.engine.orchestrator import Orchestrator
from concierge.engine.language_engine import LanguageEngine
from concierge.communications import StageMessage


class Server:
    """
    Server manages sessions and delegates requests to language engines.
    Each session gets its own orchestrator and language engine instance.
    """
    
    def __init__(self, workflow: Workflow):
        self.workflow = workflow
        self.sessions: Dict[str, LanguageEngine] = {}
    
    def create_session(self, session_id: str) -> str:
        """Create a new session and return initial stage message"""
        if session_id in self.sessions:
            return json.dumps({"error": f"Session {session_id} already exists"})
        
        # Create orchestrator and language engine for this session
        orchestrator = Orchestrator(self.workflow, session_id)
        language_engine = LanguageEngine(orchestrator)
        self.sessions[session_id] = language_engine
        
        # Return initial stage message
        stage = orchestrator.get_current_stage()
        state = stage.local_state
        return StageMessage().render(stage, self.workflow, state)
    
    async def handle_request(self, session_id: str, message: dict) -> str:
        """
        Handle incoming request for a session.
        Routes to language engine and returns formatted response.
        """
        # Get or create session
        if session_id not in self.sessions:
            return json.dumps({"error": f"Session {session_id} not found. Create session first."})
        
        language_engine = self.sessions[session_id]
        
        # Delegate to language engine
        try:
            response = await language_engine.process(message)
            return response
        except Exception as e:
            return json.dumps({"error": str(e)})
    
    def terminate_session(self, session_id: str) -> str:
        """Terminate a session and clean up resources"""
        if session_id in self.sessions:
            del self.sessions[session_id]
            return json.dumps({"status": "terminated", "session_id": session_id})
        return json.dumps({"error": f"Session {session_id} not found"})
    
    def get_active_sessions(self) -> list[str]:
        """Return list of active session IDs"""
        return list(self.sessions.keys())

