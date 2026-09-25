"""堆存记录业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "yardstore"
CONTAINER_MODULE = "container"
REQUIRED_FIELDS = ["堆存单号", "关联箱号", "箱区编号"]
STATUS_ORDER = ["待进场", "堆存中", "待提离", "已提离"]
# 与箱况统计共用同一口径：这两种状态视为箱体仍在堆场
ON_SITE_STATUS = ["堆存中", "待提离"]
ACTION_RULES = {"确认进场": "堆存中", "确认提离": "已提离", "撤销堆存": "待进场"}
NEGATIVE_ACTIONS = ["撤销堆存"]


class YardstoreService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("堆存单号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"堆存单 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于堆存记录可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"堆存单已{action}"

    def yard_stats(self) -> dict[str, Any]:
        """堆场台账统计：在场堆存、今日进场/提离，以及与箱况档案的对账。

        “在场堆存箱量”按箱号去重，与集装箱档案侧的在场判断同源
        （见 services/container.py 的 on_site_container_nos），两边对得上。
        """
        rows = store.rows(MODULE)
        status_breakdown = {status: 0 for status in STATUS_ORDER}
        on_site_nos: set[str] = set()
        today = date.today().isoformat()
        inbound_today = 0
        outbound_today = 0

        for row in rows:
            status = str(row.get("status") or "")
            if status in status_breakdown:
                status_breakdown[status] += 1
            container_no = str(row.get("关联箱号") or "").strip()
            if status in ON_SITE_STATUS and container_no:
                on_site_nos.add(container_no)
            if str(row.get("堆存开始") or "").strip() == today:
                inbound_today += 1
            if status == "已提离" and str(row.get("堆存结束") or "").strip() == today:
                outbound_today += 1

        archive_nos = {
            str(row.get("箱号") or "").strip()
            for row in store.rows(CONTAINER_MODULE)
            if str(row.get("箱号") or "").strip()
        }
        dangling = sorted(on_site_nos - archive_nos)

        return {
            "在场堆存箱量": len(on_site_nos),
            "今日进场箱量": inbound_today,
            "今日提离箱量": outbound_today,
            "各堆存状态单数": status_breakdown,
            "对账一致": not dangling,
            "台账挂账箱号": dangling,
        }
