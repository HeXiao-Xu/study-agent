export interface NavItem {
  index: string
  label: string
  name: string
  path: string
}

export const NAV_ITEMS: NavItem[] = [
  { index: '01', label: '笔记', name: 'notes', path: '/notes' },
  { index: '02', label: '文件', name: 'files', path: '/files' },
  { index: '03', label: '知识库', name: 'knowledge', path: '/knowledge' },
  { index: '04', label: '题库', name: 'questions', path: '/questions' },
  { index: '05', label: '智能问答', name: 'qa', path: '/qa' },
  { index: '06', label: '错题本', name: 'mistakes', path: '/mistakes' },
  { index: '07', label: '复习计划', name: 'plan', path: '/plan' },
]