from fastapi import APIRouter
router = APIRouter(prefix="/api/evolution", tags=["evolution"])

@router.get("/targets")
async def list_targets():
    return {"targets": [
        {"target_type": "prompt", "target_id": "design_agent"},
        {"target_type": "prompt", "target_id": "guardian_agent"},
        {"target_type": "graph", "target_id": "atr_closed_loop"},
        {"target_type": "tool", "target_id": "printer_bridge"},
        {"target_type": "report", "target_id": "analysis_agent"},
        {"target_type": "policy", "target_id": "recovery_policy"},
    ]}

@router.post("/tasks")
async def create_task(payload: dict):
    return {"task_id": "evo-task-demo", "status": "draft", "payload": payload}

@router.post("/tasks/{task_id}/run")
async def run_task(task_id: str):
    return {"task_id": task_id, "status": "running"}

@router.get("/tasks/{task_id}/variants")
async def list_variants(task_id: str):
    return {"task_id": task_id, "variants": []}

@router.post("/variants/{variant_id}/validate")
async def validate_variant(variant_id: str):
    return {"variant_id": variant_id, "gates": []}

@router.post("/variants/{variant_id}/approve")
async def approve_variant(variant_id: str):
    return {"variant_id": variant_id, "status": "approved"}

@router.post("/variants/{variant_id}/activate")
async def activate_variant(variant_id: str):
    return {"variant_id": variant_id, "status": "active_next_run"}

@router.post("/variants/{variant_id}/rollback")
async def rollback_variant(variant_id: str):
    return {"variant_id": variant_id, "status": "rolled_back"}
