"""
Node 2: Data Classification
- Filters state.context by user clearance_level
- Stores visible chunks in state.visible_context
- Records which classification levels were stripped
"""

from security.classification import filter_by_clearance
from graph.state import AgentState


def data_classification_node(state: AgentState) -> AgentState:
    clearance = state.get("clearance_level", 1)
    raw_context = state.get("context", [])

    visible, stripped = filter_by_clearance(raw_context, clearance)

    # Track which classification levels were actually accessed (visible ones)
    accessed = sorted({chunk.classification for chunk in visible})

    return {
        **state,
        "visible_context": visible,
        "stripped_levels": stripped,
        "data_classifications_accessed": accessed,
    }
