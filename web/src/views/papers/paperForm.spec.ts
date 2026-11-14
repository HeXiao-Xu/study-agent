import { describe, expect, it } from 'vitest'

import { allocateCounts, difficultyCounts, qtypeCounts } from './paperForm'

describe('paperForm 预计题量', () => {
  it('按题型权重分配默认 10 题', () => {
    expect(qtypeCounts({ 单选: 0.4, 多选: 0, 填空: 0.2, 解答: 0.4 }, 10)).toEqual({
      单选: 4,
      多选: 0,
      填空: 2,
      解答: 4,
    })
  })

  it('题量变化时用最大余数补足', () => {
    expect(qtypeCounts({ 单选: 0.4, 多选: 0, 填空: 0.2, 解答: 0.4 }, 7)).toEqual({
      单选: 3,
      多选: 0,
      填空: 1,
      解答: 3,
    })
  })

  it('按难度权重分配默认 10 题', () => {
    expect(difficultyCounts([0, 50, 50, 0, 0], 10)).toEqual({
      1: 0,
      2: 5,
      3: 5,
      4: 0,
      5: 0,
    })
  })

  it('余数并列时按传入顺序稳定补位', () => {
    expect(
      allocateCounts(
        [
          { key: 'a', weight: 1 },
          { key: 'b', weight: 1 },
          { key: 'c', weight: 1 },
        ],
        4,
      ),
    ).toEqual({ a: 2, b: 1, c: 1 })
  })

  it('全 0 权重不产生题量', () => {
    expect(qtypeCounts({ 单选: 0, 多选: 0, 填空: 0, 解答: 0 }, 10)).toEqual({
      单选: 0,
      多选: 0,
      填空: 0,
      解答: 0,
    })
  })
})