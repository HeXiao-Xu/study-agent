/** S5-6 学习报告：overview 与周报两个接口。 */
import http, { API_PREFIX, type ApiEnvelope } from '@/api/http'
import type { ReportOverview, ReportRange, WeeklyReport } from '@/types/reports'

export async function fetchReportOverview(
  range: ReportRange = '30d',
): Promise<ReportOverview> {
  const resp = await http.get<ApiEnvelope<ReportOverview>>(`${API_PREFIX}/reports/mastery`, {
    params: { range },
  })
  return resp.data.data
}

export async function generateWeeklyReport(): Promise<WeeklyReport> {
  const resp = await http.post<ApiEnvelope<WeeklyReport>>(`${API_PREFIX}/reports/weekly`)
  return resp.data.data
}