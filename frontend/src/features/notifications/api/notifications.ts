import { api } from '@/api/client';
import type { components } from '@/api/generated';

export type NotificationList = components['schemas']['NotificationListResponse'];
export type Notification = components['schemas']['NotificationResponse'];
export type MarkRead = components['schemas']['MarkReadResponse'];

export const fetchNotifications = () => api.get<NotificationList>('/notifications');
export const markRead = (externalId: string) =>
  api.post<MarkRead>(`/notifications/${externalId}/read`);
export const markAllRead = () => api.post<MarkRead>('/notifications/read-all');
