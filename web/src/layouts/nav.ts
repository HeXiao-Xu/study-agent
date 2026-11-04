export interface NavItem {
  label: string
  name: string
  path: string
}

export const NAV_ITEMS: NavItem[] = [
  { label: '笔记', name: 'notes', path: '/notes' },
  { label: '文件', name: 'files', path: '/files' },
  { label: '知识库', name: 'knowledge', path: '/knowledge' },
  { label: '题库', name: 'questions', path: '/questions' },
  { label: '智能问答', name: 'qa', path: '/qa' },
  { label: '错题本', name: 'mistakes', path: '/mistakes' },
  { label: '复习计划', name: 'plan', path: '/plan' },
  { label: '图谱', name: 'graph', path: '/graph' },
  { label: '统计', name: 'stats', path: '/stats' },
]