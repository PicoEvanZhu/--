import type { FeedbackScope, FeedbackType } from "../types/feedback";

export const FEEDBACK_OPEN_EVENT = "stock-assistant:open-feedback";

export interface FeedbackOpenPayload {
  type?: FeedbackType;
  scope?: FeedbackScope;
  content?: string;
  page?: string;
  extra_meta?: Record<string, unknown>;
}

export function openFeedbackDrawer(payload: FeedbackOpenPayload): void {
  window.dispatchEvent(
    new CustomEvent<FeedbackOpenPayload>(FEEDBACK_OPEN_EVENT, {
      detail: payload,
    })
  );
}
