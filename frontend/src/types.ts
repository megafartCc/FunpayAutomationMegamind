export type HealthStatus = {
  funpay_ready?: boolean;
  funpay_enabled?: boolean;
};

export type Stats = {
  total_accounts?: number;
  active_rentals?: number;
  available_accounts?: number;
  recent_rentals?: number;
};

export type Rental = {
  id: number;
  account_name?: string;
  owner?: string;
  chat_url?: string;
  login?: string;
  rental_start?: string;
  rental_duration?: number;
  rental_duration_minutes?: number;
  steamid?: string | number | null;
  in_match?: boolean;
  in_game?: boolean;
  hero_name?: string | null;
  match_seconds?: number | null;
  match_time?: string | null;
  presence_label?: string | null;
};

export type Account = {
  id: number;
  account_name?: string;
  login?: string;
  password?: string;
  mmr?: number | string | null;
  steamid?: string | number | null;
  owner?: string | null;
  rental_start?: string | null;
  rental_duration?: number | null;
  rental_duration_minutes?: number | null;
  lot_number?: number | null;
  lot_url?: string | null;
};

export type Lot = {
  lot_number: number;
  account_id: number;
  account_name?: string;
  lot_url?: string | null;
};

export type NotificationItem = {
  level?: string;
  message?: string;
  created_at?: string;
  owner?: string | null;
  account_id?: number | null;
};

export type Chat = {
  id: number;
  name?: string;
  last_message_text?: string;
  last_message_time?: string;
  time?: string;
  unread?: boolean;
};

export type ChatMessage = {
  id: number | string;
  text?: string | null;
  author?: string | null;
  author_id?: number | null;
  chat_id?: number | null;
  chat_name?: string | null;
  image_link?: string | null;
  by_bot?: boolean;
  type?: string | null;
  sent_time?: string | null;
};

export type ApiList<T> = {
  items: T[];
};
