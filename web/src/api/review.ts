/** S5-5 复习清单接口：只封装契约，不做业务计算。 */
import http, { API_PREFIX, type ApiEnvelope } from '@/api/http'
import type { ReviewItem, ReviewToday } from '@/types/review'

export async function refreshReview(): Promise<ReviewToday> {
  const resp = await http.post<ApiEnvelope<ReviewToday>>(`${API_PREFIX}/review/refresh`)
  return resp.data.data
}

export async function getTodayReview(): Promise<ReviewToday> {
  const resp = await http.get<ApiEnvelope<ReviewToday>>(`${API_PREFIX}/review/today`)
  return resp.data.data
}

export async function markReviewDone(id: number): Promise<ReviewItem> {
  const resp = await http.post<ApiEnvelope<ReviewItem>>(
    `${API_PREFIX}/review/items/${id}/done`,
  )
  return resp.data.data
}

export async function markReviewSkip(id: number): Promise<ReviewItem> {
  const resp = await http.post<ApiEnvelope<ReviewItem>>(
    `${API_PREFIX}/review/items/${id}/skip`,
  )
  return resp.data.data
}

export async function markReviewLater(id: number): Promise<ReviewItem> {
  const resp = await http.post<ApiEnvelope<ReviewItem>>(
    `${API_PREFIX}/review/items/${id}/later`,
  )
  return resp.data.data
}