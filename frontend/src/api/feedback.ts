import { request } from "./client";
import type {
  CreateFeedbackResponse,
  FeedbackListItem,
  FeedbackPayload,
  FeedbackScope,
  FeedbackStatus,
  FeedbackType,
} from "../types/feedback";

interface FeedbackListQuery {
  limit?: number;
  status?: FeedbackStatus;
  type?: FeedbackType;
  scope?: FeedbackScope;
}

export async function createFeedback(payload: FeedbackPayload): Promise<CreateFeedbackResponse> {
  return request<CreateFeedbackResponse>({
    path: "/feedbacks",
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function listFeedbacks(query: FeedbackListQuery = {}): Promise<FeedbackListItem[]> {
  const params = new URLSearchParams();

  if (query.limit) {
    params.set("limit", String(query.limit));
  }
  if (query.status) {
    params.set("status", query.status);
  }
  if (query.type) {
    params.set("type", query.type);
  }
  if (query.scope) {
    params.set("scope", query.scope);
  }

  return request<FeedbackListItem[]>({
    path: `/feedbacks${params.toString() ? `?${params.toString()}` : ""}`,
    method: "GET",
  });
}

export async function updateFeedbackStatus(feedbackId: number, status: FeedbackStatus): Promise<FeedbackListItem> {
  return request<FeedbackListItem>({
    path: `/feedbacks/${feedbackId}/status`,
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
}
