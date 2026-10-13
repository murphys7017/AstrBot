from typing import Any, Generic

from pydantic import Field
from pydantic.dataclasses import dataclass
from typing_extensions import TypeVar

from .message import Message

TContext = TypeVar("TContext", default=Any)


@dataclass
class ContextWrapper(Generic[TContext]):
    """A context for running an agent, which can be used to pass additional data or state."""

    context: TContext
    messages: list[Message] = Field(default_factory=list)
    """This field stores the llm message context for the agent run, agent runners will maintain this field automatically."""
    tool_call_timeout: int = 120  # Default tool call timeout in seconds
    tool_execution_surface: str = "core"
    """Execution surface currently running this tool loop."""
    # Position metadata for one model response's tool-call batch.  The runner
    # updates these fields before lifecycle hooks so progress observers can
    # distinguish an intermediate result from the end of the batch.
    tool_call_batch_index: int | None = None
    tool_call_batch_size: int | None = None


NoContext = ContextWrapper[None]
