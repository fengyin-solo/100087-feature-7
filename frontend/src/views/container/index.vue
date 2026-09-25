<template>
  <section class="page" data-module="container">
    <header class="page-head">
      <div>
        <h2>集装箱档案管理</h2>
        <p class="page-desc">维护集装箱，围绕箱号、箱型、箱况等级、所属船公司做登记、筛选与状态流转；支持勾选多箱整组改箱况。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" :disabled="!selectedIds.length" @click="openBatch">
          批量改箱况{{ selectedIds.length ? `（已选 ${selectedIds.length} 箱）` : '' }}
        </button>
        <button class="btn" type="button" @click="openCreate">登记集装箱</button>
        <button class="btn" type="button" @click="exportRows">导出集装箱档案清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <div v-if="summary" class="reconcile-bar" :class="{ mismatch: !summary['对账一致'] }">
      <span>箱况统计在场 {{ summary['在场箱量'] }} 箱 ↔ 堆场台账在场 {{ summary['台账在场记录数'] }} 条</span>
      <strong v-if="summary['对账一致']">数字一致</strong>
      <template v-else>
        <strong>数字对不上，差异箱：</strong>
        <span v-for="item in summary['差异明细']" :key="`${item['箱号']}-${item['问题']}`" class="mismatch-item">
          {{ item['箱号'] || '（空箱号）' }}{{ item['问题'] }}
        </span>
      </template>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <div v-if="batchOpen" class="batch-panel">
      <header class="batch-head">
        <strong>批量箱况维护</strong>
        <span class="batch-sub">已选 {{ selectedIds.length }} 箱，整组统一箱况等级与检验日期；已报废、不在场的箱会自动挑出</span>
        <button class="link" type="button" @click="closeBatch">收起</button>
      </header>

      <div class="batch-form">
        <label class="filter-item">
          <span>目标箱况等级</span>
          <select v-model="batchGrade">
            <option v-for="grade in grades" :key="grade" :value="grade">{{ grade }}</option>
          </select>
        </label>
        <label class="filter-item">
          <span>检验日期（整组统一）</span>
          <input v-model="batchDate" type="date" :max="today" />
        </label>
        <button class="btn primary" type="button" :disabled="submitting || !selectedIds.length" @click="submitBatch(selectedIds)">
          {{ submitting ? '提交中…' : `提交整组（${selectedIds.length} 箱）` }}
        </button>
      </div>

      <div v-if="precheck" class="precheck-result">
        <p class="group-title ok-text">能改 {{ precheck.changeable.length }} 箱</p>
        <div class="chip-row">
          <span v-for="item in precheck.changeable" :key="String(item.id)" class="chip">{{ item['箱号'] }}</span>
        </div>
        <template v-if="precheck.blocked.length">
          <p class="group-title bad-text">暂不能改 {{ precheck.blocked.length }} 箱（提交时自动跳过，不影响其他箱）</p>
          <ul class="block-list">
            <li v-for="item in precheck.blocked" :key="item.id">
              <strong>{{ item['箱号'] || `#${item.id}` }}</strong>：{{ item.reason }}
            </li>
          </ul>
        </template>
      </div>

      <div v-if="batchResult" class="batch-result">
        <template v-if="batchResult.updated.length">
          <p class="group-title ok-text">已改好 {{ batchResult.updated.length }} 箱（已生效，不会回滚）</p>
          <div class="chip-row">
            <span v-for="item in batchResult.updated" :key="String(item.id)" class="chip ok">{{ item['箱号'] }}</span>
          </div>
        </template>
        <template v-if="batchResult.blocked.length">
          <p class="group-title bad-text">卡住 {{ batchResult.blocked.length }} 箱</p>
          <ul class="block-list">
            <li v-for="item in batchResult.blocked" :key="item.id">
              <strong>{{ item['箱号'] || `#${item.id}` }}</strong>：{{ item.reason }}
            </li>
          </ul>
          <button class="btn" type="button" :disabled="submitting || !retryIds.length" @click="retryBlocked">
            修好问题后仅重试卡住的 {{ retryIds.length }} 箱
          </button>
        </template>
      </div>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th class="check-col">
            <input type="checkbox" :checked="allChecked" @change="toggleAll" />
          </th>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td class="check-col">
            <input type="checkbox" :checked="selectedIds.includes(Number(row.id))" @change="toggleOne(Number(row.id))" />
          </td>
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
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
          <td :colspan="columns.length + 2" class="empty-state">暂无集装箱档案数据，可先登记集装箱</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条集装箱档案记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
interface BlockedItem {
  id: number
  箱号?: string
  code?: string
  reason?: string
}
interface PrecheckResult {
  changeable: Row[]
  blocked: BlockedItem[]
}
interface BatchResult {
  updated: Row[]
  blocked: BlockedItem[]
}
type Summary = Record<string, any>

const ENDPOINT = '/api/container'
const columns = ["箱号", "箱型", "箱况等级", "所属船公司", "尺寸规格", "自重", "检验日期", "检验到期日", "箱体状态"]
const actions = ["登记检验", "标记可周转", "报废箱体"]
const grades = ["良好", "一般", "待修"]
const today = new Date().toISOString().slice(0, 10)

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const stats = ref([
  { label: '在册箱量', value: 0 },
  { label: '在场箱量', value: 0 },
  { label: '待修箱量', value: 0 },
  { label: '检验到期箱量', value: 0 },
])
const summary = ref<Summary | null>(null)

const selectedIds = ref<number[]>([])
const batchOpen = ref(false)
const batchGrade = ref('良好')
const batchDate = ref(today)
const precheck = ref<PrecheckResult | null>(null)
const batchResult = ref<BatchResult | null>(null)
const submitting = ref(false)

const allChecked = computed(() => rows.value.length > 0 && rows.value.every((row) => selectedIds.value.includes(Number(row.id))))
const retryIds = computed(() =>
  (batchResult.value?.blocked ?? []).filter((item) => item.code !== 'missing').map((item) => item.id),
)

function toggleOne(id: number) {
  selectedIds.value = selectedIds.value.includes(id)
    ? selectedIds.value.filter((item) => item !== id)
    : [...selectedIds.value, id]
  if (batchOpen.value) {
    void runPrecheck()
  }
}

function toggleAll() {
  const pageIds = rows.value.map((row) => Number(row.id))
  selectedIds.value = allChecked.value
    ? selectedIds.value.filter((id) => !pageIds.includes(id))
    : Array.from(new Set([...selectedIds.value, ...pageIds]))
  if (batchOpen.value) {
    void runPrecheck()
  }
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '集装箱登记入口尚未接入审批流'
}

function openBatch() {
  batchOpen.value = true
  batchResult.value = null
  void runPrecheck()
}

function closeBatch() {
  batchOpen.value = false
  batchResult.value = null
  precheck.value = null
}

async function runPrecheck() {
  if (!selectedIds.value.length) {
    precheck.value = null
    return
  }
  try {
    const response = await request(`${ENDPOINT}/condition/precheck`, {
      method: 'POST',
      body: JSON.stringify({ ids: selectedIds.value }),
    })
    if (!response.ok) {
      throw new Error('批量预检请求失败')
    }
    precheck.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '批量预检失败'
  }
}

async function submitBatch(ids: number[]) {
  if (!ids.length || submitting.value) {
    return
  }
  submitting.value = true
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/condition/batch`, {
      method: 'POST',
      body: JSON.stringify({ ids, grade: batchGrade.value, inspect_date: batchDate.value }),
    })
    const payload = await response.json()
    if (!payload.entry) {
      throw new Error(payload.message || '批量箱况维护未生效')
    }
    batchResult.value = payload.entry
    // 已改好的从勾选里移除，卡住的留着，修好问题后可只重试这几箱
    const doneIds = new Set((payload.entry.updated ?? []).map((item: Row) => Number(item.id)))
    selectedIds.value = selectedIds.value.filter((id) => !doneIds.has(id))
    await Promise.all([reload(), loadSummary()])
    await runPrecheck()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '批量箱况维护失败'
  } finally {
    submitting.value = false
  }
}

function retryBlocked() {
  void submitBatch(retryIds.value)
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('集装箱档案动作未生效，请稍后重试')
    }
    await Promise.all([reload(), loadSummary()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '集装箱档案操作失败'
  }
}

async function loadSummary() {
  try {
    const response = await request(`${ENDPOINT}/condition/summary`)
    if (!response.ok) {
      throw new Error('箱况统计读取失败')
    }
    const payload = await response.json()
    summary.value = payload
    stats.value = [
      { label: '在册箱量', value: payload['在册箱量'] ?? 0 },
      { label: '在场箱量', value: payload['在场箱量'] ?? 0 },
      { label: '待修箱量', value: payload['待修箱量'] ?? 0 },
      { label: '检验到期箱量', value: payload['检验到期箱量'] ?? 0 },
    ]
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '箱况统计读取失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('集装箱列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '集装箱档案列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadSummary()
})
</script>
