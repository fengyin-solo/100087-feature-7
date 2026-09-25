<template>
  <section class="page" data-module="container">
    <header class="page-head">
      <div>
        <h2>集装箱档案管理</h2>
        <p class="page-desc">维护集装箱，围绕箱号、箱型、箱况等级、所属船公司做登记、筛选与状态流转；支持勾选多个箱号批量改箱况。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记集装箱</button>
        <button class="btn" type="button" @click="exportRows">导出集装箱档案清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in statsCards" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value" :class="item.tone">{{ item.value }}</strong>
        <span v-if="item.hint" class="stat-hint" :class="item.tone">{{ item.hint }}</span>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <label class="filter-item">
        <span>箱体状态</span>
        <select v-model="statusFilter">
          <option value="">全部</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <div v-if="selectedIds.size" class="batch-bar">
      <span>已勾选 <strong>{{ selectedIds.size }}</strong> 个箱号</span>
      <button class="btn primary" type="button" @click="openBatch">批量改箱况</button>
      <button class="btn ghost" type="button" @click="selectedIds.clear()">清空勾选</button>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th class="check-col">
            <input
              type="checkbox"
              :checked="pageAllSelected"
              :indeterminate.prop="pageSomeSelected && !pageAllSelected"
              @change="togglePageAll"
            />
          </th>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>在场情况</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td class="check-col">
            <input type="checkbox" :checked="selectedIds.has(Number(row.id))" @change="toggleRow(Number(row.id))" />
          </td>
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>
            <span class="tag" :class="row.在场 ? 'tag-green' : 'tag-gray'">{{ row.在场 ? '在场' : '不在场' }}</span>
          </td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 3" class="empty-state">暂无集装箱档案数据，可先登记集装箱</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条集装箱档案记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 批量改箱况弹窗 -->
    <div v-if="batchOpen" class="modal-mask" @click.self="closeBatch">
      <div class="modal">
        <h3>批量改箱况</h3>

        <!-- 第一步：选目标箱况与检验日期 -->
        <template v-if="batchStep === 'form'">
          <p class="modal-tip">已勾选 <strong>{{ selectedIds.size }}</strong> 个箱号，提交前会先剔除已报废和不在场的箱。</p>
          <div class="form-grid">
            <label class="form-item">
              <span>目标箱况 <em>*</em></span>
              <select v-model="batchForm.targetStatus">
                <option value="" disabled>请选择</option>
                <option v-for="status in batchTargetStatuses" :key="status" :value="status">{{ status }}</option>
              </select>
            </label>
            <label class="form-item">
              <span>检验日期 <em>*</em></span>
              <input v-model="batchForm.inspectDate" type="date" :max="today" />
            </label>
            <label class="form-item">
              <span>箱况等级（可选，不改保留原值）</span>
              <select v-model="batchForm.conditionGrade">
                <option value="">不改等级</option>
                <option v-for="grade in conditionGrades" :key="grade" :value="grade">{{ grade }}</option>
              </select>
            </label>
          </div>

          <div class="modal-foot">
            <span v-if="batchError" class="error-text">{{ batchError }}</span>
            <span class="spacer"></span>
            <button class="btn" type="button" @click="closeBatch">取消</button>
            <button class="btn primary" type="button" :disabled="previewing" @click="previewBatch">
              {{ previewing ? '校验中…' : '预检并继续' }}
            </button>
          </div>
        </template>

        <!-- 第二步：预检结果，确认只处理能改的 -->
        <template v-else-if="batchStep === 'confirm'">
          <p class="modal-tip">
            预检完成：<strong class="ok-text">{{ preview.eligible_count }}</strong> 个可修改，
            <strong class="error-text">{{ preview.blocked_count }}</strong> 个已被挑出不处理。
          </p>
          <div v-if="preview.eligible_count" class="result-block">
            <h4>本次将处理（{{ preview.eligible_count }}）</h4>
            <ul class="no-list">
              <li v-for="item in preview.eligible" :key="item.id">
                {{ item.箱号 }} <span class="muted">当前：{{ item.当前箱况 }}</span>
              </li>
            </ul>
          </div>
          <div v-if="preview.blocked_count" class="result-block">
            <h4>不处理（{{ preview.blocked_count }}）</h4>
            <ul class="no-list blocked-list">
              <li v-for="item in preview.blocked" :key="item.id">
                <span>{{ item.箱号 }}</span>
                <span class="muted">{{ item.当前箱况 }} · {{ item.原因 }}</span>
              </li>
            </ul>
          </div>
          <div class="modal-foot">
            <span class="spacer"></span>
            <button class="btn" type="button" @click="batchStep = 'form'">返回修改</button>
            <button
              class="btn primary"
              type="button"
              :disabled="!preview.eligible_count || submitting"
              @click="submitBatch(preview.eligible.map((item) => item.id))"
            >
              {{ submitting ? '提交中…' : `只提交可改的 ${preview.eligible_count} 个` }}
            </button>
          </div>
        </template>

        <!-- 第三步：提交结果，可只重试卡住的 -->
        <template v-else>
          <p class="modal-tip">
            提交完成：成功 <strong class="ok-text">{{ result.success_count }}</strong> 个，
            失败 <strong :class="result.fail_count ? 'error-text' : 'ok-text'">{{ result.fail_count }}</strong> 个。
            成功的箱已生效，不会因重试被回滚。
          </p>
          <div v-if="result.succeeded.length" class="result-block">
            <h4>已改好（{{ result.succeeded.length }}）</h4>
            <ul class="no-list">
              <li v-for="item in result.succeeded" :key="item.id">
                {{ item.箱号 }} <span class="muted">现为：{{ item.当前箱况 }}</span>
              </li>
            </ul>
          </div>
          <div v-if="result.failed.length" class="result-block">
            <h4>卡住未处理（{{ result.failed.length }}）</h4>
            <ul class="no-list blocked-list">
              <li v-for="item in result.failed" :key="item.id">
                <span>{{ item.箱号 }}</span>
                <span class="muted">{{ item.当前箱况 ?? '—' }} · {{ item.原因 }}</span>
              </li>
            </ul>
          </div>
          <div v-if="result.duplicate_count" class="modal-tip muted">
            另有 {{ result.duplicate_count }} 个重复勾选的箱号已自动去重。
          </div>
          <div class="modal-foot">
            <span v-if="batchError" class="error-text">{{ batchError }}</span>
            <span class="spacer"></span>
            <button class="btn" type="button" @click="closeBatch">关闭</button>
            <button
              v-if="result.failed.length"
              class="btn primary"
              type="button"
              :disabled="submitting"
              @click="retryFailed"
            >
              {{ submitting ? '重试中…' : `只重试这 ${result.failed.length} 个` }}
            </button>
          </div>
        </template>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>

interface PreviewItem {
  id: number
  箱号: string
  当前箱况: string | null
  原因?: string
}

interface BatchResult {
  succeeded: PreviewItem[]
  failed: PreviewItem[]
  success_count: number
  fail_count: number
  duplicate_count: number
}

const ENDPOINT = '/api/container'
const columns = ["箱号", "箱型", "箱况等级", "所属船公司", "尺寸规格", "自重", "检验到期日", "箱体状态"]
const actions = ["登记检验", "标记可周转", "报废箱体"]
const statuses = ["待检", "可周转", "待修", "已报废"]
// 批量只允许改这三种；报废走单箱“报废箱体”动作
const batchTargetStatuses = ["待检", "可周转", "待修"]
const conditionGrades = ["A", "B", "C"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const statusFilter = ref('')
const filterFields = columns.slice(0, 3)
const selectedIds = ref<Set<number>>(new Set())

const stats = ref<Record<string, any>>({})
const statsCards = computed(() => {
  const breakdown = stats.value['各箱况箱量'] ?? {}
  const reconciled = stats.value['对账一致']
  return [
    { label: '在册箱量', value: stats.value['在册箱量'] ?? 0 },
    { label: '在场箱量（台账口径）', value: stats.value['在场箱量'] ?? 0 },
    {
      label: '待检 / 可周转 / 待修 / 报废',
      value: [breakdown['待检'] ?? 0, breakdown['可周转'] ?? 0, breakdown['待修'] ?? 0, breakdown['已报废'] ?? 0].join(' / '),
    },
    { label: '检验到期箱量', value: stats.value['检验到期箱量'] ?? 0 },
    {
      label: '台账在场堆存箱量',
      value: stats.value['台账在场堆存箱量'] ?? 0,
      hint: reconciled === undefined ? '' : reconciled ? '与箱况统计对得上' : `对不上：${(stats.value['台账挂账箱号'] ?? []).join('、')}`,
      tone: reconciled === false ? 'error-text' : 'ok-text',
    },
  ]
})

const pageAllSelected = computed(() => rows.value.length > 0 && rows.value.every((row) => selectedIds.value.has(Number(row.id))))
const pageSomeSelected = computed(() => rows.value.some((row) => selectedIds.value.has(Number(row.id))))

function toggleRow(id: number) {
  const next = new Set(selectedIds.value)
  if (next.has(id)) {
    next.delete(id)
  } else {
    next.add(id)
  }
  selectedIds.value = next
}

function togglePageAll(event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  const next = new Set(selectedIds.value)
  for (const row of rows.value) {
    const id = Number(row.id)
    if (checked) {
      next.add(id)
    } else {
      next.delete(id)
    }
  }
  selectedIds.value = next
}

function resetFilters() {
  filters.value = {}
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '集装箱登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message ?? '集装箱档案动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '集装箱档案操作失败'
  }
}

async function reloadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (response.ok) {
      stats.value = await response.json()
    }
  } catch {
    // 统计读不出来不阻塞列表操作
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(filters.value)) {
    if (value) {
      query.set(key, value)
    }
  }
  if (statusFilter.value) {
    query.set('status', statusFilter.value)
  }
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('集装箱列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    // 清掉已经不在当前列表里的勾选，避免误提交
    const pageIds = new Set(rows.value.map((row) => Number(row.id)))
    selectedIds.value = new Set([...selectedIds.value].filter((id) => pageIds.has(id)))
    await reloadStats()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '集装箱档案列表读取失败'
  }
}

// ------------------------------------------------------------------
// 批量改箱况
// ------------------------------------------------------------------

const today = new Date().toISOString().slice(0, 10)
const batchOpen = ref(false)
const batchStep = ref<'form' | 'confirm' | 'result'>('form')
const previewing = ref(false)
const submitting = ref(false)
const batchError = ref('')
const batchForm = reactive({ targetStatus: '', inspectDate: today, conditionGrade: '' })
const preview = ref<{ eligible: PreviewItem[]; blocked: PreviewItem[]; eligible_count: number; blocked_count: number }>({
  eligible: [],
  blocked: [],
  eligible_count: 0,
  blocked_count: 0,
})
const result = ref<BatchResult>({ succeeded: [], failed: [], success_count: 0, fail_count: 0, duplicate_count: 0 })

function openBatch() {
  batchError.value = ''
  batchStep.value = 'form'
  batchOpen.value = true
}

function closeBatch() {
  batchOpen.value = false
}

async function previewBatch() {
  batchError.value = ''
  if (!batchForm.targetStatus) {
    batchError.value = '请选择目标箱况'
    return
  }
  if (!batchForm.inspectDate) {
    batchError.value = '请填写检验日期'
    return
  }
  if (batchForm.inspectDate > today) {
    batchError.value = '检验日期不能晚于今天'
    return
  }
  previewing.value = true
  try {
    const response = await request(`${ENDPOINT}/batch/preview`, {
      method: 'POST',
      body: JSON.stringify({
        entry_ids: [...selectedIds.value],
        target_status: batchForm.targetStatus,
        inspect_date: batchForm.inspectDate,
        condition_grade: batchForm.conditionGrade || null,
      }),
    })
    if (!response.ok) {
      const detail = (await response.json().catch(() => null))?.detail
      throw new Error(detail ?? '预检失败，请检查勾选项')
    }
    preview.value = await response.json()
    batchStep.value = 'confirm'
  } catch (error) {
    batchError.value = error instanceof Error ? error.message : '预检失败'
  } finally {
    previewing.value = false
  }
}

async function submitBatch(ids: number[], keepResultMode = false) {
  batchError.value = ''
  submitting.value = true
  try {
    const response = await request(`${ENDPOINT}/batch/condition`, {
      method: 'POST',
      body: JSON.stringify({
        entry_ids: ids,
        target_status: batchForm.targetStatus,
        inspect_date: batchForm.inspectDate,
        condition_grade: batchForm.conditionGrade || null,
      }),
    })
    if (!response.ok) {
      const detail = (await response.json().catch(() => null))?.detail
      throw new Error(detail ?? '整组提交未受理，请稍后重试')
    }
    result.value = await response.json()
    batchStep.value = 'result'
    // 已改好的从勾选中去掉，只保留仍卡住的，方便继续在列表上处理
    const successIds = new Set(result.value.succeeded.map((item) => item.id))
    selectedIds.value = new Set([...selectedIds.value].filter((id) => !successIds.has(id)))
    await reload()
    if (keepResultMode && result.value.failed.length === 0) {
      batchOpen.value = false
    }
  } catch (error) {
    batchError.value = error instanceof Error ? error.message : '批量提交失败'
  } finally {
    submitting.value = false
  }
}

// 只重试卡住的那几个：后端逐箱独立处理，已改好的箱不在请求里，不会被回滚
function retryFailed() {
  void submitBatch(result.value.failed.map((item) => item.id), true)
}

onMounted(reload)
</script>
