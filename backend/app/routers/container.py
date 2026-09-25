"""集装箱档案接口：维护集装箱，覆盖登记检验、标记可周转、报废箱体等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, BatchConditionPayload, EntryPayload, PageResult
from app.services.container import ContainerService

router = APIRouter(prefix="/api/container", tags=["集装箱档案"])

service = ContainerService()

LIST_FIELDS = ["箱号", "箱型", "箱况等级", "所属船公司", "尺寸规格", "自重", "检验到期日", "箱体状态"]
STATUSES = ["待检", "可周转", "待修", "已报废"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按箱号检索"),
    status: str | None = Query(default=None, description="待检、可周转、待修、已报废"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按箱号与状态过滤集装箱档案列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/stats", response_model=dict)
def condition_stats() -> dict[str, Any]:
    """箱况统计：各箱况箱量、在场箱量与堆场台账对账结果。"""
    return service.condition_stats()


@router.post("/batch/preview", response_model=dict)
def preview_batch(payload: BatchConditionPayload) -> dict[str, Any]:
    """批量改箱况提交前预校验：把已报废、不在场等不能改的箱单独挑出来。

    不落库，只返回本次勾选中可改与不可改两组，前端据此只提交可改的那几个。
    """
    eligible: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for entry_id in dict.fromkeys(payload.entry_ids):  # 去重但保留顺序
        entry, reason = service.check_batch_eligibility(entry_id)
        container_no = str(entry.get("箱号", f"#{entry_id}")) if entry is not None else f"#{entry_id}"
        item = {
            "id": entry_id,
            "箱号": container_no,
            "当前箱况": entry.get("status") if entry is not None else None,
        }
        if reason:
            item["原因"] = reason
            blocked.append(item)
        else:
            eligible.append(item)
    return {
        "eligible": eligible,
        "blocked": blocked,
        "eligible_count": len(eligible),
        "blocked_count": len(blocked),
    }


@router.post("/batch/condition", response_model=dict)
def batch_update_condition(payload: BatchConditionPayload) -> dict[str, Any]:
    """批量改箱况并统一填检验日期：逐箱处理，部分成功不回滚。

    返回每个箱的成功/失败结果与失败原因；调用方修好数据后可用失败箱号原样重试。
    """
    try:
        return service.batch_update_condition(
            payload.entry_ids,
            target_status=payload.target_status,
            inspect_date=payload.inspect_date,
            condition_grade=payload.condition_grade,
        )
    except ValueError as exc:
        # 入参层面的整体错误（空选择、非法状态/日期）：一个箱都不会落库
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条集装箱明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"集装箱 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条集装箱，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="集装箱已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条集装箱执行登记检验、标记可周转、报废箱体；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出集装箱档案清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "container", "total": total, "items": items}
