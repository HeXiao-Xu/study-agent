/** S4-8 统计看板：只有一条聚合接口。 */
import http, { API_PREFIX, type ApiEnvelope } from '@/api/http'
import type { StatsOverview, StatsRange } from '@/types/stats'

export async function fetchStatsOverview(range: StatsRange = '30d'): Promise<StatsOverview> {
  const resp = await http.get<ApiEnvelope<StatsOverview>>(`${API_PREFIX}/stats/overview`, {
    params: { range },
  })
  return resp.data.data
}