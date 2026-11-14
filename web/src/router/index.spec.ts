import { describe, expect, it } from 'vitest'

import router from './index'

describe('S5-7 routes', () => {
  it('registers review, reports and practice', () => {
    const paths = router.getRoutes().map((route) => route.path)
    expect(paths).toContain('/review')
    expect(paths).toContain('/reports')
    expect(paths).toContain('/practice')
  })

  it('keeps /plan as a redirect to /review', () => {
    const plan = router.getRoutes().find((route) => route.path === '/plan')
    expect(plan?.redirect).toBe('/review')
  })
})