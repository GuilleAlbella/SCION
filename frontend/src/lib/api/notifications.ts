const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/v1";

export interface DataAvailableNotification {
  type: "data_available";
  date: string;
  files: string[];
  path: string;
}

export interface NotificationsResponse {
  notifications: DataAvailableNotification[];
  share_available: boolean;
  share_path: string;
}

export async function fetchNotifications(): Promise<NotificationsResponse> {
  const res = await fetch(`${API_BASE}/notifications`, { cache: "no-store" });
  if (!res.ok) throw new Error(`notifications: ${res.status}`);
  return res.json();
}
