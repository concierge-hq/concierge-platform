"""
Simple stock exchange example - demonstrates Concierge basics.
Focus is on showing the framework, not real stock logic.
"""
import asyncio
from pydantic import BaseModel, Field
from concierge.core import construct, State, tool, stage, Workflow


# Define constructs
@construct()
class Stock(BaseModel):
    """Stock selection"""
    symbol: str = Field(description="Stock symbol like AAPL, GOOGL")
    quantity: int = Field(ge=1, description="Number of shares")


@construct()
class Transaction(BaseModel):
    """Transaction result"""
    order_id: str = Field(description="Order ID")
    status: str = Field(description="Transaction status")


# Stage 1: Browse stocks
@stage(name="browse", prerequisites=[])
class BrowseStage:
    """Browse and search stocks"""
    
    @tool()
    def search(self, state: State, symbol: str) -> dict:
        """Search for a stock"""
        return {"result": f"Found {symbol}: $150.00"}
    
    @tool()
    def view_history(self, state: State, symbol: str) -> dict:
        """View stock price history"""
        return {"result": f"{symbol} history: [100, 120, 150]"}


# Stage 2: Transact (buy/sell)
@stage(name="transact", prerequisites=[Stock])
class TransactStage:
    """Buy or sell stocks"""
    
    @tool(output=Transaction)
    def buy(self, state: State) -> dict:
        """Buy the selected stock"""
        stock = state.get("symbol")
        qty = state.get("quantity")
        return {"order_id": "ORD123", "status": f"Bought {qty} shares of {stock}"}
    
    @tool(output=Transaction)
    def sell(self, state: State) -> dict:
        """Sell the selected stock"""
        stock = state.get("symbol")
        qty = state.get("quantity")
        return {"order_id": "ORD456", "status": f"Sold {qty} shares of {stock}"}


# Stage 3: Portfolio
@stage(name="portfolio", prerequisites=[])
class PortfolioStage:
    """View portfolio and profits"""
    
    @tool()
    def view_holdings(self, state: State) -> dict:
        """View current holdings"""
        return {"result": "Holdings: AAPL: 10 shares, GOOGL: 5 shares"}
    
    @tool()
    def view_profit(self, state: State) -> dict:
        """View profit/loss"""
        return {"result": "Total profit: +$1,234.56"}


# Build workflow
def build_workflow() -> Workflow:
    workflow = Workflow("stock_exchange", "Simple stock trading")
    
    # Add stages
    browse = BrowseStage._stage
    browse.transitions = ["transact", "portfolio"]
    
    transact = TransactStage._stage
    transact.transitions = ["portfolio", "browse"]
    
    portfolio = PortfolioStage._stage
    portfolio.transitions = ["browse"]
    
    workflow.add_stage(browse, initial=True)
    workflow.add_stage(transact)
    workflow.add_stage(portfolio)
    
    return workflow


# Demo
async def main():
    print("=== Simple Stock Exchange ===\n")
    
    workflow = build_workflow()
    session = workflow.create_session()
    
    print(f"Current stage: {session.current_stage}\n")
    
    # 1. Browse stage
    print("1. Searching for stock...")
    result = await session.process_action({
        "action": "tool",
        "tool": "search",
        "args": {"symbol": "AAPL"}
    })
    print(f"   {result}\n")
    
    # 2. Try to transition to transact (will fail - missing prerequisites)
    print("2. Trying to transition to 'transact'...")
    session.state = session.state.set("symbol", "AAPL").set("quantity", 10)
    
    result = await session.process_action({
        "action": "transition",
        "stage": "transact"
    })
    print(f"   {result['type']}: {result.get('from', '')} → {result.get('to', '')}\n")
    
    # 3. Buy stock
    print("3. Buying stock...")
    result = await session.process_action({
        "action": "tool",
        "tool": "buy",
        "args": {}
    })
    print(f"   {result}\n")
    
    # 4. Go to portfolio
    print("4. Transitioning to portfolio...")
    result = await session.process_action({
        "action": "transition",
        "stage": "portfolio"
    })
    print(f"   {result['type']}\n")
    
    # 5. View holdings
    print("5. Viewing holdings...")
    result = await session.process_action({
        "action": "tool",
        "tool": "view_holdings",
        "args": {}
    })
    print(f"   {result}\n")
    
    # Show session info
    print("Final session state:")
    print(f"  Current stage: {session.current_stage}")
    print(f"  State data: {session.state.data}")


if __name__ == "__main__":
    asyncio.run(main())

