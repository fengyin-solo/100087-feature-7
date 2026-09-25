<template>
  <section class="page" data-module="yardstore">
    <header class="page-head">
      <div>
        <h2>堆存记录管理</h2>
        <p class="page-desc">维护堆存单，围绕堆存单号、关联箱号、箱区编号、贝位号做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记堆存单</button>
        <button class="btn" type="button" @click="exportRows">导出堆存记录清单</button>
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
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
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
          <td :colspan="columns.length + 1" class="empty-state">暂无堆存记录数据，可先登记堆存单</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条堆存记录记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/yardstore'
const columns = ["堆存单号", "关联箱号", "箱区编号", "贝位号", "堆存开始", "堆存结束", "堆存天数", "堆存状态"]
const actions = ["确认进场", "确认提离", "撤销堆存"]
const statuses = ["待进场", "堆存中", "待提离", "已提离"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const stats = ref<Record<string, any>>({})

const statsCards = computed(() => [
  { label: '堆存中箱量（在场，按箱号去重）', value: stats.value['在场堆存箱量'] ?? 0 },
  { label: '今日进场箱量', value: stats.value['今日进场箱量'] ?? 0 },
  { label: '今日提离箱量', value: stats.value['今日提离箱量'] ?? 0 },
  {
    label: '与箱况统计对账',
    value: stats.value['对账一致'] === undefined ? '—' : stats.value['对账一致'] ? '一致' : '不一致',
    hint: stats.value['对账一致']
      ? '在场箱量与箱况统计一致'
      : `台账挂账：${(stats.value['台账挂账箱号'] ?? []).join('、') || '存在差异'}`,
    tone: stats.value['对账一致'] === false ? 'error-text' : 'ok-text',
  },
])

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '堆存单登记入口尚未接入审批流'
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
      throw new Error(payload?.message ?? '堆存记录动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '堆存记录操作失败'
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
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('堆存单列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    await reloadStats()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '堆存记录列表读取失败'
  }
}

onMounted(reload)
</script>
