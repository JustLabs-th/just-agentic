# Adding a New Agent

Two ways to add an agent. Choose based on whether you want it persisted in the DB
or hardcoded in Python.

---

## Option A — Via API (recommended for production)

No code change required. Agent is persisted in the database and survives restarts.

### 1. Create the agent definition

```bash
curl -X POST http://localhost:8000/api/admin/agents \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "data_analyst",
    "display_name": "Data Analyst",
    "system_prompt": "You are a Data Analyst agent...",
    "allowed_tools": ["read_file", "execute_python", "query_db", "search_knowledge"],
    "department": "data"
  }'
```

**Constraints on `name`:** lowercase alphanumeric, underscores, dashes. Must start with a letter.

**Constraints on `allowed_tools`:** the final tool list is the intersection of this list
and the user's RBAC tools. Listing a tool here that the user's role doesn't have → silently removed.

### 2. Bind users to the agent (optional)

If not bound, users fall back to default agents (backend / devops / qa / developer).

```bash
curl -X POST http://localhost:8000/api/admin/agents/data_analyst/bindings \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "alice", "agent_name": "data_analyst"}'
```

### 3. The graph auto-reloads

`invalidate_graph_cache()` is called after every admin mutation. The next request
will rebuild the graph to include the new agent.

### Managing via frontend

Admin panel (`/admin`) → Agents tab → Create Agent form.

---

## Option B — Hardcoded Python node

Use this when you need custom logic that can't be expressed in a system prompt
(e.g. pre/post processing, custom tool sets, special routing).

### 1. Create the agent file

```python
# graph/agents/my_agent.py
from langchain_core.messages import AIMessage
from langgraph.prebuilt import create_react_agent

from config.prompts import MY_AGENT_SYSTEM_PROMPT   # add to config/prompts.py
from graph.state import AgentState
from llm.adapter import get_adapter
from tools import ALL_TOOLS, TOOL_MAP, set_role_context


def my_agent_node(state: AgentState) -> dict:
    set_role_context(state["user_role"])

    # Filter tools by user's RBAC intersection
    allowed = set(state.get("allowed_tools", []))
    tools = [t for t in ALL_TOOLS if t.name in allowed]

    llm = get_adapter()
    agent = create_react_agent(llm, tools, prompt=MY_AGENT_SYSTEM_PROMPT)

    result = agent.invoke({"messages": state["messages"]})
    new_msgs = result["messages"][len(state["messages"]):]

    tools_called = [
        tc.get("name", "")
        for msg in new_msgs
        if isinstance(msg, AIMessage)
        for tc in (getattr(msg, "tool_calls", None) or [])
    ]

    return {
        **state,
        "messages":     state["messages"] + new_msgs,
        "current_agent": "my_agent",
        "tools_called": state.get("tools_called", []) + tools_called,
    }
```

### 2. Add the system prompt

```python
# config/prompts.py
MY_AGENT_SYSTEM_PROMPT = """You are My Agent.

Focus: ...

Execution rules:
- Execute tasks immediately and directly
- ...
"""
```

### 3. Register in the graph

```python
# graph/secure_graph.py

from graph.agents.my_agent import my_agent_node

# Inside build_secure_graph():
graph.add_node("my_agent", my_agent_node)
graph.add_edge("my_agent", "supervisor")   # return to supervisor after each turn

# Add to conditional routing map in route_from_supervisor():
_AGENT_NODES = {"backend", "devops", "qa", "developer", "my_agent"}
```

### 4. Add to supervisor prompt

```python
# config/prompts.py → SUPERVISOR_SYSTEM_PROMPT

Available agents:
- backend   : ...
- devops    : ...
- qa        : ...
- developer : ...
- my_agent  : focus area of your new agent
```

### 5. Seed data (optional)

If you want the agent to appear in the DB (for bindings):

```python
# db/seed.py → _DEFAULT_AGENTS list
{
    "name": "my_agent",
    "display_name": "My Agent",
    "system_prompt": MY_AGENT_SYSTEM_PROMPT,
    "allowed_tools": [...],
    "department": "engineering",
}
```

---

## How Tools Are Filtered

The effective tool list for any agent call is:

```
effective_tools = agent.allowed_tools ∩ user.role.allowed_tools ∩ user.dept.permitted_tools
```

- `agent.allowed_tools` — declared in the agent definition (DB or hardcoded)
- `user.role.allowed_tools` — from the Role table (viewer/analyst/manager/admin)
- `user.dept.permitted_tools` — from the Department table

RBAC is always the floor. An agent cannot grant tools the user's role doesn't have.

---

## How the Supervisor Knows About Your Agent

The supervisor LLM reads a list of available agents from `state["agent_definitions"]`.
These are loaded by `graph/nodes/agent_resolver.py` from the DB on every request.

For hardcoded agents (Option B), you must also add an entry to the seed data or
create one via the admin API so `agent_resolver` can load it.
