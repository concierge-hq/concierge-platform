"""
Test server layer with stock exchange workflow.
Demonstrates server managing sessions and routing to language engines.
"""
import asyncio
from pydantic import BaseModel, Field
from concierge import State, tool, stage, workflow, construct, Server


@construct()
class Stock(BaseModel):
    """Stock selection"""
    symbol: str = Field(description="Stock symbol like AAPL, GOOGL")
    quantity: int = Field(ge=1, description="Number of shares")


@stage(name="browse", prerequisites=[])
class BrowseStage:
    """Browse and search stocks"""
    
    @tool()
    def search(self, state: State, symbol: str = Field(description="Stock ticker", examples=["AAPL"])) -> dict:
        """Search for a stock"""
        return {"result": f"Found {symbol}: $150.00", "symbol": symbol, "price": 150.00}
    
    @tool()
    def add_to_cart(
        self, 
        state: State, 
        symbol: str = Field(description="Stock ticker", examples=["AAPL"]), 
        quantity: int = Field(description="Number of shares", examples=[10])
    ) -> dict:
        """Add stock to cart"""
        state.set("symbol", symbol)
        state.set("quantity", quantity)
        return {"result": f"Added {quantity} shares of {symbol}"}


@stage(name="portfolio", prerequisites=[])
class PortfolioStage:
    """View portfolio"""
    
    @tool()
    def view_holdings(self, state: State) -> dict:
        """View current holdings"""
        return {"result": "Holdings: AAPL: 10 shares"}


@workflow(name="stock_exchange", description="Simple stock trading")
class StockWorkflow:
    """Stock exchange workflow"""
    
    browse = BrowseStage
    portfolio = PortfolioStage
    
    transitions = {
        browse: [portfolio],
        portfolio: [browse]
    }


def test_server_create_session():
    """Test creating a new session"""
    workflow = StockWorkflow._workflow
    server = Server(workflow)
    
    session_id = "user-alice"
    handshake = server.create_session(session_id)
    
    assert "stock_exchange" in handshake
    assert "browse" in handshake
    assert "Available tools:" in handshake
    assert session_id in server.get_active_sessions()


def test_server_handle_tool_request():
    """Test handling tool execution request"""
    workflow = StockWorkflow._workflow
    server = Server(workflow)
    
    session_id = "user-test"
    server.create_session(session_id)
    
    response = asyncio.run(server.handle_request(session_id, {
        "action": "method_call",
        "tool": "search",
        "args": {"symbol": "AAPL"}
    }))
    
    assert "search" in response
    assert "AAPL" in response
    assert "150.00" in response


def test_server_handle_transition():
    """Test handling stage transition"""
    workflow = StockWorkflow._workflow
    server = Server(workflow)
    
    session_id = "user-test"
    server.create_session(session_id)
    
    response = asyncio.run(server.handle_request(session_id, {
        "action": "stage_transition",
        "stage": "portfolio"
    }))
    
    assert "portfolio" in response
    assert "Successfully transitioned" in response


def test_server_multiple_sessions():
    """Test managing multiple concurrent sessions"""
    workflow = StockWorkflow._workflow
    server = Server(workflow)
    
    session_1 = "user-alice"
    session_2 = "user-bob"
    
    server.create_session(session_1)
    server.create_session(session_2)
    
    active = server.get_active_sessions()
    assert session_1 in active
    assert session_2 in active
    assert len(active) == 2


def test_server_terminate_session():
    """Test terminating a session"""
    workflow = StockWorkflow._workflow
    server = Server(workflow)
    
    session_id = "user-test"
    server.create_session(session_id)
    
    result = server.terminate_session(session_id)
    assert "terminated" in result
    assert session_id not in server.get_active_sessions()


def test_server_session_isolation():
    """Test that sessions are isolated from each other"""
    async def run_test():
        workflow = StockWorkflow._workflow
        server = Server(workflow)
        
        session_1 = "user-alice"
        session_2 = "user-bob"
        
        server.create_session(session_1)
        server.create_session(session_2)
        
        response_1 = await server.handle_request(session_1, {
            "action": "method_call",
            "tool": "add_to_cart",
            "args": {"symbol": "AAPL", "quantity": 10}
        })
        
        assert '"symbol": "AAPL"' in response_1
        assert '"quantity": 10' in response_1
        
        response_2 = await server.handle_request(session_2, {
            "action": "method_call",
            "tool": "add_to_cart",
            "args": {"symbol": "GOOGL", "quantity": 5}
        })
        
        assert '"symbol": "GOOGL"' in response_2
        assert '"quantity": 5' in response_2
        
        assert server.get_active_sessions() == [session_1, session_2]
    
    asyncio.run(run_test())

