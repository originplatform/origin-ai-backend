"""Shopping and Booking Provider Adapters and Tools."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from app.tools.base import BaseTool, RiskLevel, ToolResult


class ShoppingProviderAdapter(ABC):
    @abstractmethod
    async def search_products(self, query: str) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    async def place_order(self, items: List[Dict[str, Any]], address: Dict[str, Any]) -> Dict[str, Any]:
        pass


class MovieBookingAdapter(ABC):
    @abstractmethod
    async def search_showtimes(self, movie_title: str, location: str) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    async def book_seats(self, showtime_id: str, seats: List[str], payment_details: Dict[str, Any]) -> Dict[str, Any]:
        pass


class UnconfiguredShoppingProvider(ShoppingProviderAdapter):
    async def search_products(self, query: str) -> List[Dict[str, Any]]:
        raise NotImplementedError("Grocery / Shopping provider integration is not configured.")

    async def place_order(self, items: List[Dict[str, Any]], address: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError("Shopping checkout integration is not configured. Real transactions require connected merchant APIs.")


class UnconfiguredMovieProvider(MovieBookingAdapter):
    async def search_showtimes(self, movie_title: str, location: str) -> List[Dict[str, Any]]:
        raise NotImplementedError("Cinema showtime provider integration is not configured.")

    async def book_seats(self, showtime_id: str, seats: List[str], payment_details: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError("Movie ticket booking integration is not configured.")


shopping_provider: ShoppingProviderAdapter = UnconfiguredShoppingProvider()
movie_provider: MovieBookingAdapter = UnconfiguredMovieProvider()


# --- Tools ---

class SearchProductsInput(BaseModel):
    query: str = Field(description="Product or grocery item to search")


class SearchProductsTool(BaseTool):
    tool_id = "search_products"
    name = "Search Products"
    description = "Searches for products or groceries across configured merchants."
    input_schema = SearchProductsInput
    risk_level = RiskLevel.LOW_RISK
    timeout_seconds = 20

    async def run(self, input_params: SearchProductsInput, context: Optional[Dict[str, Any]] = None) -> ToolResult:
        try:
            items = await shopping_provider.search_products(input_params.query)
            return ToolResult(success=True, data={"products": items})
        except NotImplementedError as nie:
            return ToolResult(success=False, error=str(nie), metadata={"configured": False})


class BookMovieTicketsInput(BaseModel):
    showtime_id: str = Field(description="Selected showtime identifier")
    seats: List[str] = Field(description="List of seat identifiers")
    max_price: float = Field(description="Maximum price authorized")


class BookMovieTicketsTool(BaseTool):
    tool_id = "book_movie_tickets"
    name = "Book Movie Tickets"
    description = "Books cinema tickets. Financial transaction requiring explicit human approval."
    input_schema = BookMovieTicketsInput
    risk_level = RiskLevel.REQUIRES_APPROVAL
    timeout_seconds = 30
    required_permissions = ["commerce.movie.book", "payment.authorize"]

    async def run(self, input_params: BookMovieTicketsInput, context: Optional[Dict[str, Any]] = None) -> ToolResult:
        try:
            result = await movie_provider.book_seats(
                input_params.showtime_id, input_params.seats, {"max_price": input_params.max_price}
            )
            return ToolResult(success=True, data=result)
        except NotImplementedError as nie:
            return ToolResult(success=False, error=str(nie), metadata={"configured": False})

