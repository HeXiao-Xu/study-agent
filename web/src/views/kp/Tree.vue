<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox, ElTree } from 'element-plus'

import { createKp, deleteKp, getKpTree, reorderKp, updateKp } from '@/api/kp'
import EmptyState from '@/components/common/EmptyState.vue'
import KpNodeDialog from '@/components/kp/KpNodeDialog.vue'
import { useAuthStore } from '@/stores/auth'
import type { KpDialogPayload, KpNode, KpTree } from '@/types/kp'
import {
  canDropNode,
  collectSiblingIds,
  dropParentId,
  findKpNode,
  flattenKpNodes,
  type DropType,
} from './treeUtils'

const props = defineProps<{ subject: string }>()

const auth = useAuthStore()
const canManage = computed(
  () => auth.user?.role === 'admin' || auth.user?.role === 'teacher',
)

const tree = ref<KpTree | null>(null)
const loading = ref(false)
const error = ref('')
const keyword = ref('')
const treeRef = ref<InstanceType<typeof ElTree> | null>(null)
const treeKey = ref(0)
const expandedKeys = ref<number[]>([])
const expandedIds = ref<Set<number>>(new Set())
const busy = ref(false)

const dialogOpen = ref(false)
const dialogMode = ref<'create' | 'edit'>('create')
const dialogNode = ref<KpNode | null>(null)
const dialogParent = ref<KpNode | null>(null)
const dialogParentName = ref('根级')
const saving = ref(false)

function rootIds(): number[] {
  return (tree.value?.nodes ?? []).map((node) => node.id)
}

function currentExpanded(): number[] {
  return expandedIds.value.size ? [...expandedIds.value] : rootIds()
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    tree.value = await getKpTree(props.subject)
    expandedKeys.value = currentExpanded()
    treeKey.value += 1
  } catch {
    error.value = '知识点树加载失败，请重试'
  } finally {
    loading.value = false
  }
}

function onExpand(data: KpNode): void {
  expandedIds.value.add(data.id)
}

function onCollapse(data: KpNode): void {
  expandedIds.value.delete(data.id)
}

function filterNode(value: string, data: KpNode): boolean {
  const text = value.trim().toLowerCase()
  if (!text) return true
  return data.name.toLowerCase().includes(text) || data.code.toLowerCase().includes(text)
}

function applyFilter(value: string): void {
  const text = value.trim()
  if (!tree.value) return
  if (!text) {
    expandedKeys.value = currentExpanded()
    treeKey.value += 1
    return
  }
  expandedKeys.value = flattenKpNodes(tree.value.nodes)
    .filter((node) => node.children.length > 0)
    .map((node) => node.id)
  treeKey.value += 1
  void nextTick(() => treeRef.value?.filter(text))
}

watch(keyword, applyFilter)
watch(
  () => props.subject,
  () => {
    expandedIds.value.clear()
    keyword.value = ''
    void load()
  },
)

function openCreate(parent: KpNode | null): void {
  dialogMode.value = 'create'
  dialogNode.value = null
  dialogParent.value = parent
  dialogParentName.value = parent?.name ?? '根级'
  dialogOpen.value = true
}

function openEdit(node: KpNode): void {
  dialogMode.value = 'edit'
  dialogNode.value = node
  dialogParent.value = findKpNode(tree.value?.nodes ?? [], node.parent_id)
  dialogParentName.value = dialogParent.value?.name ?? '根级'
  dialogOpen.value = true
}

async function onDialogSubmit(payload: KpDialogPayload): Promise<void> {
  if (!tree.value) return
  saving.value = true
  try {
    if (dialogMode.value === 'create') {
      const parentId = dialogParent.value?.id ?? null
      await createKp({
        subject: props.subject,
        parent_id: parentId,
        code: payload.code ?? '',
        name: payload.name,
        description: payload.description,
        exam_weight: payload.exam_weight,
        order_no: collectSiblingIds(tree.value.nodes, parentId).length,
      })
      ElMessage.success('知识点已创建')
    } else if (dialogNode.value) {
      await updateKp(dialogNode.value.id, {
        name: payload.name,
        description: payload.description,
        exam_weight: payload.exam_weight,
      })
      ElMessage.success('知识点已更新')
    }
    dialogOpen.value = false
    await load()
  } catch {
    // http.ts 已统一提示；保留弹窗让用户修改。
  } finally {
    saving.value = false
  }
}

async function removeNode(node: KpNode): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确定删除“${node.name}”吗？有子节点或被引用时后端会拒绝。`,
      '删除知识点',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await deleteKp(node.id)
    ElMessage.success('知识点已删除')
    await load()
  } catch {
    await load()
  }
}

interface DragNode {
  data: KpNode
  parent?: { childNodes?: DragNode[] } | null
}

function allowDrag(node: DragNode): boolean {
  return canManage.value && !keyword.value.trim() && node.data.parent_id !== null
}

function allowDrop(dragNode: DragNode, dropNode: DragNode, type: string): boolean {
  if (!canManage.value || keyword.value.trim()) return false
  return canDropNode(dragNode.data, dropNode.data, type as DropType)
}

async function onNodeDrop(
  dragging: DragNode,
  dropNode: DragNode,
  type: DropType,
): Promise<void> {
  if (!canManage.value || busy.value) return
  busy.value = true
  try {
    const parentId = dropParentId(dropNode.data, type)
    const orderedIds =
      dragging.parent?.childNodes?.map((node) => node.data.id) ??
      collectSiblingIds(tree.value?.nodes ?? [], parentId)
    await reorderKp({
      parent_id: parentId,
      ordered_ids: orderedIds,
      moved_id: dragging.data.id,
    })
    await load()
  } catch {
    await load()
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="kp-tree-panel">
    <div class="kp-toolbar">
      <el-input
        v-model="keyword"
        class="kp-search"
        clearable
        placeholder="搜索知识点名称或编码"
        name="kp-search"
      />
      <el-button :loading="loading" @click="load">刷新</el-button>
      <el-button
        v-if="canManage"
        type="primary"
        data-testid="add-root"
        @click="openCreate(null)"
      >
        新增根节点
      </el-button>
    </div>

    <div v-if="!canManage" class="kp-readonly" role="note">
      只读：教师或管理员可编辑知识点
    </div>

    <div v-if="error" class="kp-error" role="alert">
      {{ error }}
      <el-button link type="primary" @click="load">重试</el-button>
    </div>

    <div v-loading="loading || busy" class="kp-tree-wrap">
      <EmptyState
        v-if="!loading && tree && !tree.nodes.length"
        title="还没有知识点"
        description="教师或管理员可以新增根节点。"
      />
      <el-tree
        v-else-if="tree"
        :key="treeKey"
        ref="treeRef"
        :data="tree.nodes"
        node-key="id"
        :props="{ children: 'children', label: 'name' }"
        :default-expanded-keys="expandedKeys"
        :filter-node-method="filterNode"
        :draggable="canManage && !keyword.trim()"
        :allow-drag="allowDrag"
        :allow-drop="allowDrop"
        :expand-on-click-node="false"
        @node-expand="onExpand"
        @node-collapse="onCollapse"
        @node-drop="onNodeDrop"
      >
        <template #default="{ data }">
          <div class="kp-node">
            <span class="kp-node-name">{{ data.name }}</span>
            <el-tag size="small" effect="plain">{{ data.code }}</el-tag>
            <span class="kp-node-meta">
              L{{ data.level }}
              <template v-if="data.exam_weight !== null">
                · 权重 {{ data.exam_weight }}
              </template>
            </span>
            <span v-if="canManage" class="kp-node-actions">
              <el-button
                v-if="data.level < 4"
                link
                type="primary"
                @click.stop="openCreate(data)"
              >
                新增子节点
              </el-button>
              <el-button link @click.stop="openEdit(data)">编辑</el-button>
              <el-button
                v-if="data.parent_id !== null"
                link
                type="danger"
                @click.stop="removeNode(data)"
              >
                删除
              </el-button>
            </span>
          </div>
        </template>
      </el-tree>
    </div>

    <KpNodeDialog
      v-model="dialogOpen"
      :mode="dialogMode"
      :node="dialogNode"
      :parent-id="dialogParent?.id ?? null"
      :parent-name="dialogParentName"
      :saving="saving"
      @submit="onDialogSubmit"
    />
  </div>
</template>

<style scoped>
.kp-tree-panel {
  min-width: 0;
}

.kp-toolbar {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 14px;
}

.kp-search {
  max-width: 320px;
}

.kp-readonly {
  padding: 8px 12px;
  margin-bottom: 12px;
  color: var(--app-text-secondary);
  font-size: 13px;
  background: #f6f8fa;
  border-radius: var(--app-radius-sm);
}

.kp-error {
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 10px 14px;
  margin-bottom: 12px;
  color: var(--app-danger);
  font-size: 13px;
  background: #fff5f5;
  border: 1px solid #ffc9c9;
  border-radius: var(--app-radius-sm);
}

.kp-tree-wrap {
  min-height: 260px;
  padding: 12px;
  background: #fff;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
}

.kp-node {
  display: flex;
  gap: 8px;
  align-items: center;
  width: 100%;
  min-width: 0;
}

.kp-node-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.kp-node-meta {
  color: var(--app-text-tertiary);
  font-size: 12px;
}

.kp-node-actions {
  display: inline-flex;
  gap: 4px;
  margin-left: auto;
}
</style>
