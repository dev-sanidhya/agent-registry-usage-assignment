from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, field_validator
from typing import Optional
import re

app = FastAPI(title="Agent Registry", description="Mini Agent Discovery + Usage platform")

# --- In-memory storage ---
agents: dict[str, dict] = {}       # name -> agent record
usage_logs: dict[str, dict] = {}   # request_id -> log record (idempotency)

# --- Models ---
class AgentIn(BaseModel):
    name: str
    description: str
    endpoint: str

    @field_validator("name", "description", "endpoint")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("field must not be empty")
        return v.strip()

class UsageIn(BaseModel):
    caller: str
    target: str
    units: int
    request_id: str

    @field_validator("caller", "target", "request_id")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("field must not be empty")
        return v.strip()

    @field_validator("units")
    @classmethod
    def positive_units(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("units must be a positive integer")
        return v


# --- REQ 4 (Bonus – Option B): keyword extraction ---
_STOPWORDS = {
    "a", "an", "the", "and", "or", "for", "of", "in", "to", "from",
    "that", "this", "with", "by", "is", "are", "be", "can", "it",
    "on", "at", "as", "into", "via", "using",
}

def extract_tags(description: str) -> list[str]:
    """Return meaningful lowercase keywords from a description string."""
    words = re.findall(r"[a-zA-Z]+", description.lower())
    seen: set[str] = set()
    tags: list[str] = []
    for w in words:
        if w not in _STOPWORDS and len(w) > 2 and w not in seen:
            seen.add(w)
            tags.append(w)
    return tags


# --- REQ 1: Agent Registry ---

@app.post("/agents", status_code=201)
def add_agent(agent: AgentIn):
    """Register a new agent. Name must be unique."""
    if agent.name in agents:
        raise HTTPException(status_code=409, detail=f"Agent '{agent.name}' already exists")
    record = {
        "name": agent.name,
        "description": agent.description,
        "endpoint": agent.endpoint,
        "tags": extract_tags(agent.description),
    }
    agents[agent.name] = record
    return record


@app.get("/agents")
def list_agents():
    """Return all registered agents."""
    return list(agents.values())


@app.get("/search")
def search_agents(q: str = Query(..., description="Search term (case-insensitive)")):
    """Search agents by name or description (case-insensitive substring match)."""
    term = q.lower()
    results = [
        a for a in agents.values()
        if term in a["name"].lower() or term in a["description"].lower()
    ]
    return results


# --- REQ 2: Usage Logging ---

@app.post("/usage", status_code=200)
def log_usage(usage: UsageIn):
    """
    Log a usage event between agents.
    Idempotent: duplicate request_id is silently ignored.
    """
    if usage.target not in agents:
        raise HTTPException(
            status_code=404,
            detail=f"Target agent '{usage.target}' not found. Register it first.",
        )

    if usage.request_id in usage_logs:
        return {"status": "duplicate", "message": "request_id already processed, ignored"}

    usage_logs[usage.request_id] = usage.model_dump()
    return {"status": "logged"}


@app.get("/usage-summary")
def usage_summary():
    """Return total units consumed per target agent."""
    summary: dict[str, int] = {}
    for log in usage_logs.values():
        target = log["target"]
        summary[target] = summary.get(target, 0) + log["units"]
    return summary
