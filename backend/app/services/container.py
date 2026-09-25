"""集装箱档案业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "container"
YARD_MODULE = "yardstore"
REQUIRED_FIELDS = ["箱号", "箱型", "箱况等级"]
STATUS_ORDER = ["待检", "可周转", "待修", "已报废"]
ACTION_RULES = {"登记检验": "可周转", "标记可周转": "待修", "报废箱体": "已报废"}
NEGATIVE_ACTIONS = []

# 批量箱况维护：可选的箱况等级，以及检验后推导出的箱体状态
CONDITION_GRADES = ["良好", "一般", "待修"]
GRADE_STATUS = {"良好": "可周转", "一般": "可周转", "待修": "待修"}
# 台账里算"在场"的堆存状态：堆存中、待提离；待进场与已提离都不算在场
ONSITE_YARD_STATUSES = {"堆存中", "待提离"}


def _onsite_numbers() -> dict[str, int]:
    """按箱号统计堆场台账里的在场记录数，作为"箱是否在场"的唯一口径。"""
    counts: dict[str, int] = {}
    for row in store.rows(YARD_MODULE):
        if row.get("status") in ONSITE_YARD_STATUSES:
            number = str(row.get("关联箱号") or "").strip()
            if number:
                counts[number] = counts.get(number, 0) + 1
    return counts


def _block_reason(entry: dict[str, Any], onsite: dict[str, int]) -> tuple[str, str] | None:
    """判断单箱能否参与批量改箱况；能改返回 None，否则返回 (拦下代码, 拦下原因)。"""
    if entry.get("status") == "已报废":
        return "scrapped", "已报废箱不参与批量改箱况"
    number = str(entry.get("箱号") or "").strip()
    if onsite.get(number, 0) == 0:
        return "offsite", "当前不在场（台账中没有堆存中或待提离记录）"
    return None


class ContainerService:
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
            rows = [row for row in rows if keyword in str(row.get("箱号", ""))]
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
            return None, f"集装箱 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于集装箱档案可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["箱体状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"集装箱已{action}"

    def precheck_condition(self, ids: list[int]) -> dict[str, Any]:
        """提交前预检：把已报废、不在场、不存在的箱挑出来，只留能改的。"""
        onsite = _onsite_numbers()
        changeable: list[dict[str, Any]] = []
        blocked: list[dict[str, Any]] = []
        for entry_id in ids:
            entry = store.find(MODULE, entry_id)
            if entry is None:
                blocked.append({"id": entry_id, "箱号": "", "code": "missing", "reason": "档案不存在或已归档"})
                continue
            reason = _block_reason(entry, onsite)
            if reason is None:
                changeable.append({
                    "id": entry_id,
                    "箱号": entry.get("箱号"),
                    "箱况等级": entry.get("箱况等级"),
                    "箱体状态": entry.get("status"),
                })
            else:
                code, text = reason
                blocked.append({"id": entry_id, "箱号": entry.get("箱号"), "code": code, "reason": text})
        return {"changeable": changeable, "blocked": blocked}

    def apply_condition_batch(
        self,
        ids: list[int],
        grade: str,
        inspect_date: str,
    ) -> tuple[dict[str, Any] | None, str]:
        """整组改箱况：能改的立即生效且不回滚，改不了的逐箱说明箱号与原因。

        重复提交同一组等级与日期是幂等的，已改好的箱再次提交不会产生副作用。
        """
        grade = grade.strip()
        if grade not in CONDITION_GRADES:
            return None, f"箱况等级「{grade}」不在可选范围：{'、'.join(CONDITION_GRADES)}"
        try:
            inspected = date.fromisoformat(inspect_date.strip())
        except ValueError:
            return None, f"检验日期「{inspect_date}」格式应为 YYYY-MM-DD"
        if inspected > date.today():
            return None, f"检验日期「{inspect_date}」晚于今天，检验日期不能预填未来日期"
        if not ids:
            return None, "请先勾选要维护的箱号"

        onsite = _onsite_numbers()
        target_status = GRADE_STATUS[grade]
        updated: list[dict[str, Any]] = []
        blocked: list[dict[str, Any]] = []
        for entry_id in ids:
            entry = store.find(MODULE, entry_id)
            if entry is None:
                blocked.append({"id": entry_id, "箱号": "", "code": "missing", "reason": "档案不存在或已归档"})
                continue
            reason = _block_reason(entry, onsite)
            if reason is not None:
                code, text = reason
                blocked.append({"id": entry_id, "箱号": entry.get("箱号"), "code": code, "reason": text})
                continue
            entry["箱况等级"] = grade
            entry["检验日期"] = inspect_date.strip()
            entry["status"] = target_status
            entry["箱体状态"] = target_status
            entry["pending"] = target_status == "待修"
            entry["abnormal"] = target_status == "待修"
            updated.append({
                "id": entry_id,
                "箱号": entry.get("箱号"),
                "箱况等级": grade,
                "检验日期": entry["检验日期"],
                "箱体状态": target_status,
            })

        result = {"updated": updated, "blocked": blocked, "summary": self.condition_summary()}
        if blocked:
            detail = "、".join(f"{item['箱号'] or item['id']}（{item['reason']}）" for item in blocked)
            return result, f"已改好 {len(updated)} 箱，{len(blocked)} 箱被拦下：{detail}"
        return result, f"已改好 {len(updated)} 箱，箱况等级统一为「{grade}」，检验日期 {inspect_date.strip()}"

    def condition_summary(self) -> dict[str, Any]:
        """箱况统计：在册、在场、待修与检验到期口径，并与堆场台账逐箱对账。"""
        rows = store.rows(MODULE)
        onsite = _onsite_numbers()
        today = date.today().isoformat()
        by_status = {status: 0 for status in STATUS_ORDER}
        by_grade: dict[str, int] = {}
        overdue = 0
        onsite_rows: list[dict[str, Any]] = []
        for row in rows:
            status = str(row.get("status") or "")
            by_status[status] = by_status.get(status, 0) + 1
            grade = str(row.get("箱况等级") or "未定")
            by_grade[grade] = by_grade.get(grade, 0) + 1
            due = str(row.get("检验到期日") or "")
            if due and due <= today and status != "已报废":
                overdue += 1
            if onsite.get(str(row.get("箱号") or "").strip(), 0) > 0:
                onsite_rows.append(row)

        yard_active = [row for row in store.rows(YARD_MODULE) if row.get("status") in ONSITE_YARD_STATUSES]
        by_number = {str(row.get("箱号") or "").strip(): row for row in rows}
        mismatches: list[dict[str, str]] = []
        seen: dict[str, int] = {}
        for record in yard_active:
            number = str(record.get("关联箱号") or "").strip()
            entry = by_number.get(number)
            if entry is None:
                mismatches.append({"箱号": number, "问题": "台账在场但档案缺失"})
            elif entry.get("status") == "已报废":
                mismatches.append({"箱号": number, "问题": "台账在场但档案已报废"})
            seen[number] = seen.get(number, 0) + 1
            if seen[number] > 1:
                mismatches.append({"箱号": number, "问题": "同一箱号存在多条在场台账"})

        return {
            "在册箱量": len(rows),
            "在场箱量": len(onsite_rows),
            "待修箱量": by_status.get("待修", 0),
            "检验到期箱量": overdue,
            "状态分布": by_status,
            "箱况分布": by_grade,
            "台账在场记录数": len(yard_active),
            "对账一致": len(onsite_rows) == len(yard_active) and not mismatches,
            "差异明细": mismatches,
        }
