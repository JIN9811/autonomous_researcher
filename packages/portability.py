"""Shared recursive portability policy for detached package declarations."""

from __future__ import annotations

import ipaddress
import re
from typing import Any


MAX_DEPTH = 40
PRIVATE_KEYS = {
    "password", "token", "api_key", "access_token", "access_code", "secret",
    "credentials", "authorization", "connection", "connections", "host", "hostname",
    "ip", "ip_address", "port", "base_url", "endpoint", "serial_number",
    "runtime_state", "runtime_snapshot", "run_state", "run_id", "events", "history",
}
OWNER_PLAN_PRIVATE_KEYS = {"session_id", "user_id"}
EXECUTABLE_KEYS = {
    "code", "python", "script", "scripts", "command", "commands", "command_template",
    "executable", "executable_path", "entrypoint", "factory", "imports", "files",
    "file_contents", "attachments", "environment", "env", "shell", "callback", "function",
}
WORKSPACE_ROUTES = {
    "/printer", "/lerobot", "/windows-equipment", "/equipment/windows", "/cae", "/plc", "/live",
}


def _local_ui_reference(value: Any) -> bool:
    return isinstance(value, str) and (
        value in WORKSPACE_ROUTES
        or bool(re.fullmatch(r"/api/[a-zA-Z0-9_/{}/.-]+", value)) and ".." not in value
    )


def portable_value(
    value: Any,
    *,
    exporting: bool,
    depth: int = 0,
    owner_plan: bool = False,
) -> Any:
    """Copy portable data, stripping only ordinary export-private fields."""
    if depth > MAX_DEPTH:
        raise ValueError("Package nesting exceeds limit")
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            normalized = re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower().replace("-", "_")
            child_owner_plan = owner_plan or normalized == "owner_plan"
            private = normalized in PRIVATE_KEYS or any(
                token in normalized
                for token in ("password", "credential", "secret", "access_token", "api_key", "connection")
            )
            private = private or normalized.endswith(("_host", "_ip", "_port", "_address", "_url"))
            private = private or (owner_plan and normalized in OWNER_PLAN_PRIVATE_KEYS)
            if normalized == "endpoint" and _local_ui_reference(child):
                private = False
            if private:
                if exporting:
                    if owner_plan:
                        raise ValueError("Owner plan contains private runtime or scope fields")
                    continue
                raise ValueError("Package contains private connection or runtime fields")
            if normalized in EXECUTABLE_KEYS or normalized.endswith(
                ("_code", "_command", "_script", "_executable")
            ):
                raise ValueError("Package contains unsupported executable or file-inclusion fields")
            result[key] = portable_value(
                child,
                exporting=exporting,
                depth=depth + 1,
                owner_plan=child_owner_plan,
            )
        return result
    if isinstance(value, list):
        return [
            portable_value(item, exporting=exporting, depth=depth + 1, owner_plan=owner_plan)
            for item in value
        ]
    if isinstance(value, str):
        if _local_ui_reference(value):
            return value
        try:
            ipaddress.ip_address(value)
        except ValueError:
            pass
        else:
            raise ValueError("Package contains a machine connection address")
        if re.fullmatch(r"[a-zA-Z0-9_.-]+\.(local|lan)", value):
            raise ValueError("Package contains a machine connection address")
        if (
            value.startswith(("/", "~", "\\"))
            or re.search(r"(^|[\s\"'])[/](home|Users|tmp|etc|mnt|var)/", value)
            or re.search(r"(^|[/\\])\.\.([/\\]|$)", value)
            or re.search(r"[A-Za-z]:[/\\]", value)
            or re.search(r"(?:https?|file|ssh|mqtt|ftp)://", value, re.I)
        ):
            raise ValueError("Package contains a machine-local path or connection URL")
    return value
