from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, Field


class RunCreate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    task_description: str
    scenario_id: str = 'demo-scenario'
    status: str = 'running'
    agent_version: str = 'demo-agent-v1'
    model_provider: str = 'local-demo'
    model_identifier: str = 'demo-agent'
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EventCreate(BaseModel):
    event_type: str
    status: str = 'success'
    input_payload: Dict[str, Any] = Field(default_factory=dict)
    output_payload: Dict[str, Any] = Field(default_factory=dict)
    artifact_references: List[str] = Field(default_factory=list)


class ReplayRequest(BaseModel):
    correction: Dict[str, Any]
    allowlist: List[str] = Field(default_factory=list)


class RunCompare(BaseModel):
    original_run_id: str
    replay_run_id: str
    verification_status: str
    assertion_results: Dict[str, Any]
    state_diff: Dict[str, Any]
