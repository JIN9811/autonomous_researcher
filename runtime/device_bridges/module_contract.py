"""Code-owned, declarative device bridge metadata. No transport factories."""
from dataclasses import dataclass
import json
import re
from typing import Any


@dataclass(frozen=True)
class BridgeModule:
    module_id: str
    version: str
    descriptor_json: str

    def __post_init__(self):
        if not re.fullmatch(r"[a-z][a-z0-9_]*", self.module_id):
            raise ValueError("Invalid bridge ID")
        if not re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", self.version):
            raise ValueError("Bridge version must be exact major.minor.patch")
        data = json.loads(self.descriptor_json)
        if not isinstance(data, dict) or {"schema", "id", "version", "kind"} & data.keys():
            raise ValueError("Invalid bridge metadata or identity override")

    def describe(self) -> dict[str, Any]:
        return {**json.loads(self.descriptor_json), "schema": "ax4lab.bridge_module.v1",
                "kind": "device_bridge", "id": self.module_id, "version": self.version}
