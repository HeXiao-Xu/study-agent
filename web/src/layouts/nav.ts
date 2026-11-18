export interface NavItem {
  label: string
  name: string
  path: string
}

export interface NavGroup {
  name: string
  title: string
  items: NavItem[]
}

/** 侧栏分组：按学习流程归类，标题避免与子项重名。 */
export const NAV_GROUPS: NavGroup[] = [
  {
    name: 'knowledge',
    title: '知识空间',
    items: [
      { label: '笔记', name: 'notes', path: '/notes' },
      { label: '文件', name: 'files', path: '/files' },
      { label: '知识库', name: 'knowledge', path: '/knowledge' },
      { label: '图谱', name: 'graph', path: '/graph' },
    ],
  },
  {
    name: 'assessment',
    title: '测评与考试',
    items: [
      { label: '题库', name: 'questions', path: '/questions' },
      { label: '组卷', name: 'papers', path: '/papers/generate' },
      { label: '我的试卷', name: 'papers-list', path: '/papers' },
      { label: '练习', name: 'practice', path: '/practice' },
    ],
  },
  {
    name: 'review',
    title: '复盘与反馈',
    items: [
      { label: '错题本', name: 'mistakes', path: '/mistakes' },
      { label: '复习', name: 'review', path: '/review' },
      { label: '报告', name: 'reports', path: '/reports' },
      { label: '统计', name: 'stats', path: '/stats' },
    ],
  },
  {
    name: 'assistant',
    title: 'AI 助手',
    items: [
      { label: '智能问答', name: 'qa', path: '/qa' },
      { label: 'Agent 任务', name: 'agent-tasks', path: '/agent/tasks' },
    ],
  },
]

/** 扁平列表保留给面包屑/标题查找；顺序即分组内顺序。 */
export const NAV_ITEMS: NavItem[] = NAV_GROUPS.flatMap((group) => group.items)