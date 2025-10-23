"""Tool result communication."""
import json
from concierge.communications.base import Communications
from concierge.core.results import ToolResult


class ToolResultMessage(Communications):
    """Message after tool execution - renders only the tool execution result"""
    
    def render(self, result: ToolResult) -> str:
        """Render only the tool execution result, without stage context"""
        # Format the result based on its type
        result_str = str(result.result)
        
        return f"Tool '{result.tool_name}' executed successfully.\n\nResult:\n{result_str}"

