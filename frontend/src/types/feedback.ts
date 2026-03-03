export type FeedbackType = "bug" | "feature" | "data" | "ux" | "other";

export type FeedbackScope = "home" | "dashboard" | "stocks" | "stock_detail" | "report" | "news" | "other";

export type FeedbackStatus = "new" | "triaged" | "done";

export interface FeedbackPayload {
  user_id?: string | null;
  page: string;
  type: FeedbackType;
  scope: FeedbackScope;
  content: string;
  contact?: string | null;
  screenshot_url?: string | null;
  meta_json?: Record<string, unknown>;
}

export interface CreateFeedbackResponse {
  feedback_id: number;
}

export interface FeedbackListItem {
  id: number;
  user_id: string | null;
  page: string;
  type: FeedbackType;
  scope: FeedbackScope;
  content: string;
  contact: string | null;
  screenshot_url: string | null;
  meta_json: string | null;
  status: FeedbackStatus;
  created_at: string;
}
