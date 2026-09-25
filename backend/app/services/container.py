"""集装箱档案业务规则：状态流转、字段校验与筛选口径都收在这里。

批量改箱况的口径：
- 已报废箱为终态，不允许再改；
- 不在场箱（堆存台账里没有“堆存中/待提离”记录）不允许在本功能里改；
- 逐箱校验、逐箱落库，单个箱失败不影响其它箱，也不回滚已经改好的箱；
- 箱况统计里的“在场箱”与堆场台账里的在场堆存按同一口径取数，两边必须对得上。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "container"
YARDSTORE_MODULE = "yardstore"
REQUIRED_FIELDS = ["箱号", "箱型", "箱况等级"]
STATUS_ORDER = ["待检", "可周转", "待修", "已报废"]
SCRAPPED_STATUS = "已报废"
# 台账里处于这两种状态的堆存单，视为箱体此刻仍在堆场
ON_SITE_LEDGER_STATUS = ["堆存中", "待提离"]
ACTION_RULES = {"登记检验": "可周转", "标记可周转": "待修", "报废箱体": "已报废"}
NEGATIVE_ACTIONS = []

# 批量改箱况允许落到的箱况：报废只能走单箱“报废箱体”动作，不在批量范围内
BATCH_TARGET_STATUSES = ["待检", "可周转", "待修"]
CONDITION_GRADES = ["A", "B", "C"]


def _container_no(entry: dict[str, Any]) -> str:
    return str(entry.get("箱号") or "").strip()


def on_site_container_nos() -> set[str]:
    """在场箱号集合：以堆场台账中仍未提离的堆存单为准（同一箱号去重）。"""
    return {
        str(row.get("关联箱号") or "").strip()
        for row in store.rows(YARDSTORE_MODULE)
        if row.get("status") in ON_SITE_LEDGER_STATUS and str(row.get("关联箱号") or "").strip()
    }


def is_container_on_site(entry: dict[str, Any], on_site_nos: set[str] | None = None) -> bool:
    """判断单个箱是否在场，口径与 on_site_container_nos 保持一致。"""
    if on_site_nos is None:
        on_site_nos = on_site_container_nos()
    return _container_no(entry) in on_site_nos


def _with_presence(entry: dict[str, Any], on_site_nos: set[str]) -> dict[str, Any]:
    """给列表行补一个“是否在场”派生字段，供前端勾选前预判；不改原始台账。"""
    row = dict(entry)
    row["在场"] = _container_no(entry) in on_site_nos
    return row


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
        on_site_nos = on_site_container_nos()
        page_rows = [_with_presence(row, on_site_nos) for row in rows[start:start + size]]
        return page_rows, total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        return _with_presence(entry, on_site_container_nos())

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
        entry["检验日期"] = None
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
        entry["pending"] = target != SCRAPPED_STATUS
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"集装箱已{action}"

    # ------------------------------------------------------------------
    # 批量改箱况
    # ------------------------------------------------------------------

    def check_batch_eligibility(self, entry_id: int) -> tuple[dict[str, Any] | None, str]:
        """逐箱预判：返回 (箱体记录, 不可改原因)。原因为空表示本次可以改。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, "箱体不存在或已归档"
        if entry.get("status") == SCRAPPED_STATUS:
            return entry, "已报废箱为终态，不能再改箱况"
        if not is_container_on_site(entry):
            return entry, "箱体不在场（堆场台账无在场堆存记录），不能改箱况"
        return entry, ""

    def batch_update_condition(
        self,
        entry_ids: list[int],
        *,
        target_status: str,
        inspect_date: str,
        condition_grade: str | None = None,
    ) -> dict[str, Any]:
        """批量改箱况：逐箱独立校验、独立落库。

        - 入参层面的整体错误（空选择、非法状态/日期）抛 ValueError，由路由层转 400；
        - 单箱层面的错误收进 failures，绝不回滚已成功的箱；
        - 重试时只传仍失败的箱即可，已改好的箱不在列表里，自然不会被重复处理。
        """
        if not entry_ids:
            raise ValueError("请至少勾选一个箱号")
        if target_status not in BATCH_TARGET_STATUSES:
            raise ValueError(
                f"目标箱况「{target_status}」不允许批量修改，"
                f"可选：{'、'.join(BATCH_TARGET_STATUSES)}（报废请走单箱报废动作）"
            )
        try:
            parsed_date = date.fromisoformat(inspect_date)
        except (ValueError, TypeError):
            raise ValueError("检验日期格式不正确，应为 YYYY-MM-DD")
        if parsed_date > date.today():
            raise ValueError("检验日期不能晚于今天")
        grade = (condition_grade or "").strip() or None
        if grade is not None and grade not in CONDITION_GRADES:
            raise ValueError(f"箱况等级「{grade}」不合法，可选：{'、'.join(CONDITION_GRADES)}")

        date_text = parsed_date.isoformat()
        # 同一次请求里重复勾选同一箱号，只处理一次并提示
        seen: set[int] = set()
        succeeded: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        skipped_duplicates: list[int] = []

        for entry_id in entry_ids:
            if entry_id in seen:
                skipped_duplicates.append(entry_id)
                continue
            seen.add(entry_id)

            entry, reason = self.check_batch_eligibility(entry_id)
            if reason:
                container_no = _container_no(entry) if entry is not None else f"#{entry_id}"
                failed.append({
                    "id": entry_id,
                    "箱号": container_no,
                    "当前箱况": entry.get("status") if entry is not None else None,
                    "原因": reason,
                })
                continue

            entry["status"] = target_status
            entry["pending"] = True  # 批量可落的状态都不是报废终态
            entry["abnormal"] = False
            entry["检验日期"] = date_text
            if grade is not None:
                entry["箱况等级"] = grade
            succeeded.append({
                "id": entry_id,
                "箱号": _container_no(entry),
                "当前箱况": target_status,
            })

        return {
            "succeeded": succeeded,
            "failed": failed,
            "success_count": len(succeeded),
            "fail_count": len(failed),
            "duplicate_count": len(skipped_duplicates),
            "target_status": target_status,
            "inspect_date": date_text,
        }

    # ------------------------------------------------------------------
    # 箱况统计（与堆场台账共用在场口径）
    # ------------------------------------------------------------------

    def condition_stats(self) -> dict[str, Any]:
        """箱况统计：在册、各箱况、在场/不在场、检验到期。

        “在场箱量”按堆场台账在场堆存单口径计算，
        与 /api/yardstore/stats 的在场堆存箱量同源，两边数字必须一致。
        """
        rows = store.rows(MODULE)
        ledger_nos = on_site_container_nos()
        archive_nos = {_container_no(row) for row in rows if _container_no(row)}
        status_breakdown = {status: 0 for status in STATUS_ORDER}
        on_site = 0
        off_site = 0
        today = date.today().isoformat()
        inspection_due = 0

        for row in rows:
            status = str(row.get("status") or "")
            if status in status_breakdown:
                status_breakdown[status] += 1
            if _container_no(row) in ledger_nos:
                on_site += 1
            else:
                off_site += 1
            due = str(row.get("检验到期日") or "").strip()
            if due and due <= today and status != SCRAPPED_STATUS:
                inspection_due += 1

        # 在场口径直接来自堆场台账，唯一可能的差异是台账引用了档案里不存在的箱号
        dangling = sorted(ledger_nos - archive_nos)
        reconciled = not dangling

        return {
            "在册箱量": len(rows),
            "各箱况箱量": status_breakdown,
            "在场箱量": on_site,
            "不在场箱量": off_site,
            "台账在场堆存箱量": len(ledger_nos),
            "检验到期箱量": inspection_due,
            "对账一致": reconciled,
            "台账挂账箱号": dangling,
        }
