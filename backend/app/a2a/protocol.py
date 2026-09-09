"""A2A 协议数据结构：Agent Card 与 Task。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

A2A_PROTOCOL_VERSION = "0.3.0"


@dataclass
class AgentCard:
    """A2A Agent Card —— agent 的「能力名片」，供主控 agent 动态发现。"""

    name: str
    description: str
    url: str  # JSON-RPC 端点，如 http://127.0.0.1:8001/
    version: str = "1.0.0"
    protocol_version: str = A2A_PROTOCOL_VERSION
    preferred_transport: str = "JSONRPC"
    capabilities: Dict[str, Any] = field(default_factory=lambda: {
        "streaming": False,
        "pushNotifications": False,
        "stateTransitionHistory": True,
    })
    default_input_modes: List[str] = field(default_factory=lambda: ["text/plain", "application/json"])
    default_output_modes: List[str] = field(default_factory=lambda: ["text/plain", "application/json"])
    skills: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "url": self.url,
            "version": self.version,
            "protocolVersion": self.protocol_version,
            "preferredTransport": self.preferred_transport,
            "capabilities": self.capabilities,
            "defaultInputModes": self.default_input_modes,
            "defaultOutputModes": self.default_output_modes,
            "skills": self.skills,
        }
