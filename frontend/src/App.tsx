import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import Toast from "./components/common/Toast";
import LoginPage from "./pages/LoginPage";
import { createApiClient } from "./services/api";
import { connectChatWS } from "./services/ws";
import { useToast } from "./hooks/useToast";
import AddAccountForm from "./components/account/AddAccountForm";
import { formatDate } from "./utils/format";

const EASE: [number, number, number, number] = [0.22, 1, 0.36, 1];
const PRESENCE_BASE =
  (import.meta.env.VITE_PRESENCE_URL && import.meta.env.VITE_PRESENCE_URL.replace(/\/$/, "")) ||
  // fallback to window-injected value if present
  (typeof window !== "undefined" && (window as any).__PRESENCE_URL__?.replace?.(/\/$/, "")) ||
  "https://laudable-flow-production-9c8a.up.railway.app/presence";

type OverviewData = {
  totalAccounts: number | null;
  activeRentals: number | null;
  freeAccounts: number | null;
  past24: number | null;
  totalHours: number | null;
};

type AccountRow = {
  id?: string | number;
  login?: string;
  password?: string;
  steamId?: string;
  name?: string;
  mmr?: number | string | null;
  owner?: string | null;
  rentalStart?: string | null;
  rentalDurationMinutes?: number | null;
  rentalDurationHours?: number | null;
  accountFrozen?: boolean;
  rentalFrozen?: boolean;
  rentalFrozenAt?: string | null;
  keyId?: number | null;
};

type RentalRow = {
  id?: string | number;
  accountName?: string;
  login?: string | null;
  buyer?: string;
  durationSec?: number | null;
  startedAt?: string | number | null;
  status?: string;
  hero?: string;
  steamId?: string;
  presence?: PresenceData | null;
  presenceLabel?: string | null;
  presenceObservedAt?: number | null;
  chatUrl?: string | null;
  adminCalls?: number;
  adminLastCalledAt?: string | null;
  rentalFrozen?: boolean;
  rentalFrozenAt?: string | null;
  keyId?: number | null;
};

type NotificationItem = {
  id?: string | number;
  level?: string;
  message?: string;
  createdAt?: string;
  owner?: string;
  accountId?: string | number;
};

type ChatItem = {
  id?: string | number;
  name?: string;
  last?: string;
  time?: string;
  unread?: boolean;
  avatarUrl?: string | null;
  adminCalls?: number;
  adminLastCalledAt?: string | null;
  _hidden?: boolean;
};

type ChatMessage = {
  id?: string | number;
  author?: string;
  text?: string;
  sentAt?: string;
  byBot?: boolean;
  adminCall?: boolean;
};

type FunpayStatsPayload = {
  balance?: {
    total_rub?: number | null;
    available_rub?: number | null;
    total_usd?: number | null;
    total_eur?: number | null;
    created_at?: string | null;
  } | null;
  balance_series?: number[];
  orders?: {
    daily?: number[];
    weekly?: number[];
    monthly?: number[];
  };
  reviews?: {
    daily?: number[];
    weekly?: number[];
    monthly?: number[];
  };
  generated_at?: string | null;
};

type OrderHistoryItem = {
  id?: string | number;
  orderId?: string;
  buyer?: string;
  accountName?: string;
  accountId?: number | null;
  login?: string | null;
  steamId?: string | null;
  rentalMinutes?: number | null;
  amount?: number | null;
  price?: number | null;
  action?: string | null;
  createdAt?: string | null;
  chatUrl?: string | null;
  lotNumber?: number | null;
};

type OverviewCachePayload = {
  overview: OverviewData;
  accounts: AccountRow[];
  rentals: RentalRow[];
};

type DashboardPayload = {
  stats?: Record<string, number>;
  accounts?: any[];
  rentals?: any[];
  generated_at?: string;
  cached?: boolean;
};

type UserKey = {
  id: number;
  label: string;
  is_default?: boolean;
  created_at?: string | null;
  proxy_url?: string | null;
  proxy_username?: string | null;
  proxy_password?: string | null;
};

type LotRow = {
  lotNumber: number;
  accountId: number;
  accountName?: string;
  lotUrl?: string | null;
  owner?: string | null;
  keyId?: number | null;
};

type KeyScope = "all" | number;

type BlacklistEntry = {
  id?: string | number;
  owner: string;
  reason?: string | null;
  createdAt?: string | null;
};

type BlacklistLog = {
  owner: string;
  action: string;
  reason?: string | null;
  details?: string | null;
  created_at?: string | null;
};

type CategoryOption = {
  id: number;
  name: string;
  game?: string | null;
  category?: string | null;
  server?: string | null;
};

const extractSteamId = (a: any): string => {
  const direct =
    a?.steamId ??
    a?.steamid ??
    a?.steam_id ??
    a?.steamId64 ??
    a?.steam ??
    a?.steamId32 ??
    a?.steamid32 ??
    "";
  const stringDirect = direct ? String(direct).trim() : "";
  const regex17 = /\b(7656119\d{10})\b/;
  if (stringDirect && regex17.test(stringDirect)) return regex17.exec(stringDirect)![1];

  const maRaw = a?.mafile_json ?? a?.maFileJson ?? a?.mafile ?? "";
  if (typeof maRaw === "string" && maRaw.trim()) {
    const hit = regex17.exec(maRaw);
    if (hit) return hit[1];
    try {
      const parsed = JSON.parse(maRaw);
      const deep =
        parsed?.steamid ||
        parsed?.Session?.SteamID ||
        parsed?.session?.SteamID ||
        parsed?.SessionID ||
        parsed?.SteamID;
      const deepStr = deep ? String(deep) : "";
      const deepHit = regex17.exec(deepStr);
      if (deepHit) return deepHit[1];
    } catch {
      // ignore bad JSON
    }
  }
  return stringDirect || "";
};

const normalizeKey = (value?: string | number | null) =>
  value === null || value === undefined ? "" : String(value).trim().toLowerCase();

const getInitials = (value?: string | null) => {
  const clean = String(value || "").trim();
  if (!clean) return "?";
  const parts = clean.split(/\s+/).filter(Boolean);
  const first = parts[0]?.[0] || "";
  const second = parts.length > 1 ? parts[parts.length - 1]?.[0] || "" : "";
  const initials = (first + second).toUpperCase();
  return initials || clean.slice(0, 2).toUpperCase();
};

const hashToHue = (value?: string | null) => {
  const text = String(value || "");
  let hash = 0;
  for (let i = 0; i < text.length; i += 1) {
    hash = (hash * 31 + text.charCodeAt(i)) % 360;
  }
  return Math.abs(hash) % 360;
};

const isAdminCallText = (value?: string | null) => {
  if (!value) return false;
  const trimmed = String(value).trim().toLowerCase();
  return /^!(admin|админ)\b/.test(trimmed);
};

const playAdminCallSound = () => {
  try {
    const AudioContextClass = (window as any).AudioContext || (window as any).webkitAudioContext;
    if (!AudioContextClass) return;
    const context = new AudioContextClass();
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.type = "sine";
    oscillator.frequency.value = 880;
    gain.gain.value = 0.05;
    oscillator.connect(gain);
    gain.connect(context.destination);
    oscillator.start();
    oscillator.stop(context.currentTime + 0.2);
    oscillator.onended = () => {
      context.close().catch(() => null);
    };
  } catch {
    // ignore audio errors
  }
};

const avatarStyle = (name?: string | null) => {
  const hue = hashToHue(name);
  const hue2 = (hue + 36) % 360;
  return {
    background: `linear-gradient(135deg, hsl(${hue} 70% 45%), hsl(${hue2} 70% 55%))`,
  } as React.CSSProperties;
};

const DashboardIcon = () => (
  <svg width="18" height="19" viewBox="0 0 18 19" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path
      d="M17 14.3425V8.79451C17 8.26017 16.9995 7.99286 16.9346 7.74422C16.877 7.52387 16.7825 7.31535 16.6546 7.12693C16.5102 6.9143 16.3096 6.73797 15.9074 6.38611L11.1074 2.18611C10.3608 1.53283 9.98751 1.20635 9.56738 1.08211C9.19719 0.972631 8.80261 0.972631 8.43242 1.08211C8.01261 1.20626 7.63985 1.53242 6.89436 2.18472L2.09277 6.38611C1.69064 6.73798 1.49004 6.9143 1.3457 7.12693C1.21779 7.31536 1.12255 7.52387 1.06497 7.74422C1 7.99286 1 8.26017 1 8.79451V14.3425C1 15.2743 1 15.7401 1.15224 16.1076C1.35523 16.5977 1.74432 16.9875 2.23438 17.1905C2.60192 17.3427 3.06786 17.3427 3.99974 17.3427C4.93163 17.3427 5.39808 17.3427 5.76562 17.1905C6.25568 16.9875 6.64467 16.5978 6.84766 16.1077C6.9999 15.7402 7 15.2742 7 14.3424V13.3424C7 12.2378 7.89543 11.3424 9 11.3424C10.1046 11.3424 11 12.2378 11 13.3424V14.3424C11 15.2742 11 15.7402 11.1522 16.1077C11.3552 16.5978 11.7443 16.9875 12.2344 17.1905C12.6019 17.3427 13.0679 17.3427 13.9997 17.3427C14.9316 17.3427 15.3981 17.3427 15.7656 17.1905C16.2557 16.9875 16.6447 16.5977 16.8477 16.1076C16.9999 15.7401 17 15.2743 17 14.3425Z"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const FunpayStatisticsIcon = () => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path
      d="M20 21C20 18.2386 16.4183 16 12 16C7.58172 16 4 18.2386 4 21M12 13C9.23858 13 7 10.7614 7 8C7 5.23858 9.23858 3 12 3C14.7614 3 17 5.23858 17 8C17 10.7614 14.7614 13 12 13Z"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const RentalsIcon = () => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path
      d="M12 13V9M21 6L19 4M10 2H14M12 21C7.58172 21 4 17.4183 4 13C4 8.58172 7.58172 5 12 5C16.4183 5 20 8.58172 20 13C20 17.4183 16.4183 21 12 21Z"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const BlacklistIcon = () => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path
      d="M5.75 5.75L18.25 18.25M12 21C7.02944 21 3 16.9706 3 12C3 7.02944 7.02944 3 12 3C16.9706 3 21 7.02944 21 12C21 16.9706 16.9706 21 12 21Z"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const InventoryIcon = () => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path
      d="M18 12V17C18 18.6569 15.3137 20 12 20C8.68629 20 6 18.6569 6 17V12M18 12V7M18 12C18 13.6569 15.3137 15 12 15C8.68629 15 6 13.6569 6 12M18 7C18 5.34315 15.3137 4 12 4C8.68629 4 6 5.34315 6 7M18 7C18 8.65685 15.3137 10 12 10C8.68629 10 6 8.65685 6 7M6 12V7"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const LotsIcon = () => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path
      d="M18 12V17C18 18.6569 15.3137 20 12 20C8.68629 20 6 18.6569 6 17V12M18 12V7M18 12C18 13.6569 15.3137 15 12 15C8.68629 15 6 13.6569 6 12M18 7C18 5.34315 15.3137 4 12 4C8.68629 4 6 5.34315 6 7M18 7C18 8.65685 15.3137 10 12 10C8.68629 10 6 8.65685 6 7M6 12V7"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const ChatsIcon = () => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path
      d="M5.59961 19.9203L7.12357 18.7012L7.13478 18.6926C7.45249 18.4384 7.61281 18.3101 7.79168 18.2188C7.95216 18.1368 8.12328 18.0771 8.2998 18.0408C8.49877 18 8.70603 18 9.12207 18H17.8031C18.921 18 19.4806 18 19.908 17.7822C20.2843 17.5905 20.5905 17.2842 20.7822 16.9079C21 16.4805 21 15.9215 21 14.8036V7.19691C21 6.07899 21 5.5192 20.7822 5.0918C20.5905 4.71547 20.2837 4.40973 19.9074 4.21799C19.4796 4 18.9203 4 17.8002 4H6.2002C5.08009 4 4.51962 4 4.0918 4.21799C3.71547 4.40973 3.40973 4.71547 3.21799 5.0918C3 5.51962 3 6.08009 3 7.2002V18.6712C3 19.7369 3 20.2696 3.21846 20.5433C3.40845 20.7813 3.69644 20.9198 4.00098 20.9195C4.35115 20.9191 4.76744 20.5861 5.59961 19.9203Z"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const AddIcon = () => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path
      d="M12 16V10M12 10L9 12M12 10L15 12M3 6V16.8C3 17.9201 3 18.4798 3.21799 18.9076C3.40973 19.2839 3.71547 19.5905 4.0918 19.7822C4.5192 20 5.07899 20 6.19691 20H17.8031C18.921 20 19.48 20 19.9074 19.7822C20.2837 19.5905 20.5905 19.2841 20.7822 18.9078C21.0002 18.48 21.0002 17.9199 21.0002 16.7998L21.0002 9.19978C21.0002 8.07967 21.0002 7.51962 20.7822 7.0918C20.5905 6.71547 20.2839 6.40973 19.9076 6.21799C19.4798 6 18.9201 6 17.8 6H12M3 6H12M3 6C3 4.89543 3.89543 4 5 4H8.67452C9.1637 4 9.40886 4 9.63904 4.05526C9.84311 4.10425 10.0379 4.18526 10.2168 4.29492C10.4186 4.41857 10.5918 4.59182 10.9375 4.9375L12 6"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const NotificationsIcon = () => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path
      d="M15 17V18C15 19.6569 13.6569 21 12 21C10.3431 21 9 19.6569 9 18V17M15 17H9M15 17H18.5905C18.973 17 19.1652 17 19.3201 16.9478C19.616 16.848 19.8475 16.6156 19.9473 16.3198C19.9997 16.1643 19.9997 15.9715 19.9997 15.5859C19.9997 15.4172 19.9995 15.3329 19.9863 15.2524C19.9614 15.1004 19.9024 14.9563 19.8126 14.8312C19.7651 14.7651 19.7048 14.7048 19.5858 14.5858L19.1963 14.1963C19.0706 14.0706 19 13.9001 19 13.7224V10C19 6.134 15.866 2.99999 12 3C8.13401 3.00001 5 6.13401 5 10V13.7224C5 13.9002 4.92924 14.0706 4.80357 14.1963L4.41406 14.5858C4.29476 14.7051 4.23504 14.765 4.1875 14.8312C4.09766 14.9564 4.03815 15.1004 4.0132 15.2524C4 15.3329 4 15.4172 4 15.586C4 15.9715 4 16.1642 4.05245 16.3197C4.15225 16.6156 4.3848 16.848 4.68066 16.9478C4.83556 17 5.02701 17 5.40956 17H9"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const OrdersHistoryIcon = () => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path
      d="M4 8H20M4 8V16.8002C4 17.9203 4 18.4801 4.21799 18.9079C4.40973 19.2842 4.71547 19.5905 5.0918 19.7822C5.5192 20 6.07899 20 7.19691 20H16.8031C17.921 20 18.48 20 18.9074 19.7822C19.2837 19.5905 19.5905 19.2842 19.7822 18.9079C20 18.4805 20 17.9215 20 16.8036V8M4 8V7.2002C4 6.08009 4 5.51962 4.21799 5.0918C4.40973 4.71547 4.71547 4.40973 5.0918 4.21799C5.51962 4 6.08009 4 7.2002 4H8M20 8V7.19691C20 6.07899 20 5.5192 19.7822 5.0918C19.5905 4.71547 19.2837 4.40973 18.9074 4.21799C18.4796 4 17.9203 4 16.8002 4H16M16 2V4M16 4H8M8 2V4"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const SettingsIcon = () => (
  <svg width="22" height="21" viewBox="0 0 22 21" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path
      d="M19.3465 7.35066L18.9803 7.14693C18.9234 7.1153 18.8955 7.09942 18.868 7.08297C18.5949 6.91939 18.3647 6.69337 18.1968 6.42296C18.1799 6.39575 18.1639 6.36722 18.1314 6.31083C18.0988 6.25451 18.0824 6.22597 18.0672 6.19772C17.9166 5.9164 17.8351 5.60289 17.8302 5.2838C17.8297 5.25172 17.8298 5.21894 17.8309 5.15378L17.8381 4.72852C17.8495 4.04799 17.8552 3.70667 17.7596 3.40035C17.6747 3.12827 17.5325 2.87766 17.3428 2.66499C17.1282 2.42458 16.8313 2.25308 16.2368 1.9105L15.743 1.62594C15.1502 1.28431 14.8536 1.11344 14.5389 1.0483C14.2605 0.990672 13.9731 0.993343 13.6957 1.05563C13.3825 1.12592 13.0897 1.30125 12.5044 1.65169L12.5011 1.65328L12.1473 1.86514C12.0914 1.89864 12.063 1.91553 12.035 1.93112C11.7567 2.08584 11.4461 2.17139 11.1278 2.1816C11.0958 2.18263 11.0631 2.18263 10.9979 2.18263C10.9331 2.18263 10.899 2.18263 10.867 2.1816C10.5481 2.17134 10.2368 2.08533 9.95809 1.92997C9.93 1.91431 9.90222 1.89729 9.84615 1.86364L9.49008 1.64986C8.90081 1.2961 8.60573 1.11895 8.29086 1.0483C8.01229 0.9858 7.72395 0.984071 7.44449 1.04244C7.12894 1.10835 6.83235 1.28049 6.23916 1.62477L6.23653 1.62594L5.74886 1.90897L5.74347 1.91227C5.15562 2.25345 4.86099 2.42445 4.64828 2.66387C4.45952 2.87633 4.31843 3.12655 4.23398 3.39791C4.13852 3.70465 4.14361 4.0467 4.15511 4.73043L4.16226 5.15509C4.16334 5.2194 4.16522 5.25135 4.16475 5.28298C4.16002 5.60272 4.07744 5.91687 3.92633 6.19869C3.91138 6.22656 3.89528 6.25444 3.86312 6.31011C3.83094 6.36582 3.81536 6.39352 3.79867 6.42041C3.62995 6.69226 3.39872 6.9196 3.12391 7.08346C3.09673 7.09967 3.06808 7.11525 3.0118 7.14645L2.65023 7.34681C2.04867 7.68018 1.74795 7.84701 1.52914 8.08443C1.33557 8.29446 1.18933 8.54358 1.10007 8.8149C0.999171 9.1216 0.999256 9.46552 1.00082 10.1533L1.00209 10.7154C1.00365 11.3986 1.00577 11.7399 1.1069 12.0446C1.19637 12.3141 1.34153 12.5617 1.53402 12.7705C1.7516 13.0064 2.04932 13.1722 2.64633 13.5044L3.00467 13.7037C3.06565 13.7376 3.09634 13.7544 3.12575 13.7721C3.39806 13.9361 3.62747 14.1628 3.79476 14.4331C3.81284 14.4623 3.83019 14.4926 3.86488 14.5532C3.89914 14.613 3.91667 14.643 3.93252 14.673C4.07919 14.9507 4.15772 15.2592 4.16307 15.5732C4.16365 15.6071 4.16316 15.6414 4.16199 15.7104L4.15511 16.1179C4.14353 16.804 4.13849 17.1474 4.2345 17.455C4.31945 17.7271 4.46142 17.9777 4.65121 18.1904C4.86573 18.4308 5.16313 18.6022 5.75765 18.9448L6.25136 19.2293C6.84421 19.5709 7.14053 19.7416 7.45527 19.8067C7.73372 19.8644 8.02123 19.8621 8.29867 19.7998C8.61225 19.7294 8.90606 19.5535 9.49301 19.2021L9.84683 18.9902C9.90281 18.9567 9.93115 18.9399 9.9592 18.9243C10.2375 18.7696 10.5478 18.6836 10.8661 18.6734C10.8981 18.6723 10.9307 18.6723 10.996 18.6723C11.0614 18.6723 11.094 18.6723 11.1261 18.6734C11.445 18.6836 11.7573 18.7699 12.036 18.9253C12.0605 18.9389 12.0851 18.9537 12.1282 18.9796L12.5044 19.2054C13.0937 19.5592 13.3882 19.7359 13.703 19.8065C13.9816 19.869 14.2702 19.8716 14.5496 19.8132C14.8651 19.7473 15.1623 19.5748 15.7551 19.2307L16.2501 18.9434C16.8384 18.6021 17.1333 18.4309 17.3461 18.1914C17.5349 17.9789 17.6761 17.7288 17.7606 17.4574C17.8553 17.1529 17.8496 16.8135 17.8383 16.1396L17.8309 15.7002C17.8298 15.6358 17.8297 15.6039 17.8302 15.5722C17.8349 15.2525 17.9161 14.9381 18.0672 14.6563C18.0821 14.6285 18.0984 14.6004 18.1304 14.5449C18.1626 14.4892 18.1793 14.4614 18.1959 14.4345C18.3647 14.1627 18.5961 13.9351 18.8709 13.7713C18.8978 13.7553 18.9254 13.74 18.9804 13.7095L18.9823 13.7086L19.3438 13.5083C19.9454 13.1749 20.2467 13.0079 20.4655 12.7705C20.6591 12.5604 20.8051 12.3117 20.8944 12.0403C20.9947 11.7354 20.9939 11.3935 20.9924 10.7138L20.9911 10.1396C20.9895 9.45644 20.9887 9.11513 20.8875 8.81051C20.7981 8.54101 20.6521 8.29334 20.4596 8.08458C20.2422 7.84884 19.9441 7.68299 19.3483 7.35151L19.3465 7.35066Z"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M6.99691 10.4277C6.99691 12.6368 8.78777 14.4277 10.9969 14.4277C13.2061 14.4277 14.9969 12.6368 14.9969 10.4277C14.9969 8.21856 13.2061 6.4277 10.9969 6.4277C8.78777 6.4277 6.99691 8.21856 6.99691 10.4277Z"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const NAV_ITEMS = [
  { id: "funpay-stats", label: "Funpay Statistics", Icon: FunpayStatisticsIcon },
  { id: "overview", label: "Dashboard", Icon: DashboardIcon },
  { id: "rentals", label: "Active Rentals", Icon: RentalsIcon },
  { id: "orders", label: "Orders History", Icon: OrdersHistoryIcon },
  { id: "tickets", label: "Tickets (FunPay)", Icon: OrdersHistoryIcon },
  { id: "blacklist", label: "Blacklist", Icon: BlacklistIcon },
  { id: "inventory", label: "Inventory", Icon: InventoryIcon },
  { id: "lots", label: "Lots", Icon: LotsIcon },
  { id: "chats", label: "Chats", Icon: ChatsIcon },
  { id: "add", label: "Add Account", Icon: AddIcon },
  { id: "notifications", label: "Notifications", Icon: NotificationsIcon },
  { id: "settings", label: "Settings", Icon: SettingsIcon },
];
const BOTTOM_NAV_IDS = new Set(["notifications", "settings"]);

const CardUsersIcon = () => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path
      d="M21 19.9999C21 18.2583 19.3304 16.7767 17 16.2275M15 20C15 17.7909 12.3137 16 9 16C5.68629 16 3 17.7909 3 20M15 13C17.2091 13 19 11.2091 19 9C19 6.79086 17.2091 5 15 5M9 13C6.79086 13 5 11.2091 5 9C5 6.79086 6.79086 5 9 5C11.2091 5 13 6.79086 13 9C13 11.2091 11.2091 13 9 13Z"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const FunpayStatsIcon = () => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path
      d="M20 21C20 18.2386 16.4183 16 12 16C7.58172 16 4 18.2386 4 21M12 13C9.23858 13 7 10.7614 7 8C7 5.23858 9.23858 3 12 3C14.7614 3 17 5.23858 17 8C17 10.7614 14.7614 13 12 13Z"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const CardCloudCheckIcon = () => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path
      d="M15 11L11 15L9 13M23 15C23 12.7909 21.2091 11 19 11C18.9764 11 18.9532 11.0002 18.9297 11.0006C18.4447 7.60802 15.5267 5 12 5C9.20335 5 6.79019 6.64004 5.66895 9.01082C3.06206 9.18144 1 11.3498 1 13.9999C1 16.7613 3.23858 19.0001 6 19.0001L19 19C21.2091 19 23 17.2091 23 15Z"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const CardBarsIcon = () => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path
      d="M19.5 5.5V18.5M12 3.5V18.5M4.5 9.5V18.5M22 18.5H2"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const navIdToPath: Record<string, string> = {
  "funpay-stats": "/funpay-stats",
  overview: "/dashboard",
  rentals: "/rentals",
  orders: "/orders",
  tickets: "/tickets",
  blacklist: "/blacklist",
  profile: "/profile",
  inventory: "/inventory",
  lots: "/lots",
  chats: "/chats",
  add: "/add",
  notifications: "/notifications",
  settings: "/settings",
};

const pathToNavId = (path: string): string => {
  const clean = path.toLowerCase();
  const found = Object.entries(navIdToPath).find(([, p]) => p === clean);
  return found?.[0] || "overview";
};

const overviewCards = [
  { key: "totalAccounts", title: "Total Accounts", delta: "+12%", deltaTone: "positive", Icon: CardUsersIcon },
  { key: "activeRentals", title: "Active Rentals", delta: "-3%", deltaTone: "negative", Icon: CardUsersIcon },
  { key: "freeAccounts", title: "Free Accounts", delta: "+6%", deltaTone: "positive", Icon: CardCloudCheckIcon },
  { key: "past24", title: "Past 24h", delta: "+2%", deltaTone: "positive", Icon: CardBarsIcon },
];

const INVENTORY_GRID =
  "minmax(72px,0.6fr) minmax(180px,1.4fr) minmax(140px,1fr) minmax(140px,1fr) minmax(190px,1.1fr) minmax(80px,0.6fr) minmax(110px,0.6fr)";
const RENTALS_GRID =
  "minmax(64px,0.6fr) minmax(180px,1.4fr) minmax(160px,1.1fr) minmax(140px,1fr) minmax(120px,0.8fr) minmax(110px,0.8fr) minmax(140px,1fr) minmax(110px,0.7fr)";
const ORDERS_GRID =
  "minmax(120px,0.9fr) minmax(160px,1fr) minmax(180px,1.2fr) minmax(180px,1.2fr) minmax(120px,0.8fr) minmax(110px,0.7fr) minmax(110px,0.7fr) minmax(160px,1fr) minmax(110px,0.7fr)";
const BLACKLIST_GRID =
  "minmax(48px,0.4fr) minmax(200px,1.1fr) minmax(240px,1.6fr) minmax(160px,0.9fr) minmax(120px,0.6fr)";
const LOTS_GRID =
  "minmax(80px,0.6fr) minmax(220px,1.4fr) minmax(160px,0.9fr) minmax(160px,1fr) minmax(180px,1.2fr) minmax(110px,0.6fr)";
const CACHE_PREFIX = "fpa_cache:";
const createEmptyOverview = (): OverviewData => ({
  totalAccounts: null,
  activeRentals: null,
  freeAccounts: null,
  past24: null,
  totalHours: null,
});
const createEmptyFunpayStats = (): FunpayStatsPayload => ({
  balance_series: [],
  orders: { daily: [], weekly: [], monthly: [] },
  reviews: { daily: [], weekly: [], monthly: [] },
});
const STATS_CACHE_KEY = `${CACHE_PREFIX}funpay_stats`;
const OVERVIEW_CACHE_KEY = `${CACHE_PREFIX}overview`;
const CHAT_LIST_CACHE_KEY = `${CACHE_PREFIX}chat_list`;
const CHAT_HISTORY_CACHE_PREFIX = `${CACHE_PREFIX}chat_history:`;
const ORDERS_HISTORY_CACHE_PREFIX = `${CACHE_PREFIX}orders_history:`;
const LOTS_CACHE_KEY = `${CACHE_PREFIX}lots`;
type CacheEntry<T> = { data: T; ts: number; etag?: string };
const memoryCache = new Map<string, CacheEntry<any>>();
const inflightRequests = new Map<string, Promise<CacheEntry<any> | null>>();
const revalidateGuards = new Map<string, number>();
const REVALIDATE_THROTTLE_MS = 4000;
const CACHE_TTLS = {
  stats: 10 * 60 * 1000,
  overview: 30 * 1000,
  chatList: 15 * 1000,
  chatHistory: 8 * 1000,
  orders: 5 * 60 * 1000,
  blacklist: 2 * 60 * 1000,
  lots: 2 * 60 * 1000,
};

const readCache = <T,>(key: string, maxAgeMs?: number) => {
  try {
    let best: CacheEntry<T> | null = null;
    const memory = memoryCache.get(key) as CacheEntry<T> | undefined;
    if (memory?.ts && Number.isFinite(memory.ts)) {
      best = memory;
    }
    const raw = localStorage.getItem(key);
    if (raw) {
      const parsed = JSON.parse(raw) as { ts?: number; data?: T; etag?: string } | null;
      if (parsed && typeof parsed === "object") {
        const ts = Number(parsed.ts);
        if (Number.isFinite(ts)) {
          const entry: CacheEntry<T> = {
            data: parsed.data as T,
            ts,
            etag: typeof parsed.etag === "string" ? parsed.etag : undefined,
          };
          if (!best || entry.ts > best.ts) {
            best = entry;
          }
        }
      }
    }
    if (!best) return null;
    memoryCache.set(key, best);
    const isStale = maxAgeMs ? Date.now() - best.ts > maxAgeMs : false;
    return { data: best.data as T, ts: best.ts, isStale, etag: best.etag };
  } catch {
    return null;
  }
};

  const writeCache = <T,>(key: string, data: T, etag?: string) => {
    try {
      const entry: CacheEntry<T> = { data, ts: Date.now(), etag };
      memoryCache.set(key, entry);
      localStorage.setItem(key, JSON.stringify(entry));
    } catch {
      // ignore cache writes
    }
  };

const App: React.FC = () => {
  const [token, setToken] = useState("");
  const [authState, setAuthState] = useState<"unknown" | "authed" | "guest">("unknown");
  const [pathname, setPathname] = useState(() => window.location.pathname);
  const [activeNav, setActiveNav] = useState<string>("overview");
  const [userKeys, setUserKeys] = useState<UserKey[]>([]);
  const [activeKeyId, setActiveKeyId] = useState<KeyScope>(() => {
    const raw = localStorage.getItem("fpa_active_key_id");
    if (!raw || raw === "all") return "all";
    const parsed = Number(raw);
    return Number.isFinite(parsed) ? parsed : "all";
  });
  const [keysLoading, setKeysLoading] = useState(false);
  const [overview, setOverview] = useState<OverviewData>(createEmptyOverview);
  const [overviewHydrated, setOverviewHydrated] = useState(false);
  const [funpayStats, setFunpayStats] = useState<FunpayStatsPayload>(createEmptyFunpayStats);
  const [funpayStatsLoading, setFunpayStatsLoading] = useState(false);
  const [accountsTable, setAccountsTable] = useState<AccountRow[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState<string | number | null>(null);
  const [assignOwner, setAssignOwner] = useState("");
  const [accountEditName, setAccountEditName] = useState("");
  const [accountEditLogin, setAccountEditLogin] = useState("");
  const [accountEditPassword, setAccountEditPassword] = useState("");
  const [accountEditMmr, setAccountEditMmr] = useState("");
  const [accountEditKeyId, setAccountEditKeyId] = useState("");
  const [accountActionBusy, setAccountActionBusy] = useState(false);
  const [reviewRange, setReviewRange] = useState<"daily" | "weekly" | "monthly">("weekly");
  const [orderRange, setOrderRange] = useState<"daily" | "weekly" | "monthly">("weekly");
  const [selectedRentalId, setSelectedRentalId] = useState<string | number | null>(null);
  const [rentalExtendHours, setRentalExtendHours] = useState("");
  const [rentalExtendMinutes, setRentalExtendMinutes] = useState("");
  const [rentalActionBusy, setRentalActionBusy] = useState(false);
  const [rentalsTable, setRentalsTable] = useState<RentalRow[]>([]);
  const [chats, setChats] = useState<ChatItem[]>([]);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [selectedChat, setSelectedChat] = useState<string | number | null>(null);
  const [chatLoading, setChatLoading] = useState(false);
  const [chatListLoading, setChatListLoading] = useState(false);
  const [chatStreamActive, setChatStreamActive] = useState(false);
  const chatListStreamRef = useRef<EventSource | null>(null);
  const chatHistoryStreamRef = useRef<EventSource | null>(null);
  const chatWsRef = useRef<WebSocket | null>(null);
  const [chatWsConnected, setChatWsConnected] = useState(false);
  const chatWsSubscribedRef = useRef<string | null>(null);
  const chatWsHeartbeatRef = useRef<number | null>(null);
  const hydrateTimeoutRef = useRef<number | null>(null);
  const [chatInput, setChatInput] = useState("");
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [ordersHistory, setOrdersHistory] = useState<OrderHistoryItem[]>([]);
  const [ordersQuery, setOrdersQuery] = useState("");
  const [ordersLoading, setOrdersLoading] = useState(false);
  const [autoRaise, setAutoRaise] = useState<boolean | null>(null);
  const [autoRaiseCategories, setAutoRaiseCategories] = useState<string>("");
  const [categoryOptions, setCategoryOptions] = useState<CategoryOption[]>([]);
  const [categorySearch, setCategorySearch] = useState("");
  const [categoryIdSearch, setCategoryIdSearch] = useState("");
  const [categoryLoading, setCategoryLoading] = useState(false);
  const [categoryMeta, setCategoryMeta] = useState<{ ts?: number; count?: number }>({});
  const [expandedGames, setExpandedGames] = useState<Set<string>>(() => new Set());
  const [autoOnline, setAutoOnline] = useState<boolean>(() => localStorage.getItem("autoOnline") === "1");
  const [autoTickets, setAutoTickets] = useState<boolean | null>(null);
  const [uiMode, setUiMode] = useState<"light" | "dark">(
    () => (localStorage.getItem("uiMode") as "light" | "dark") || "light"
  );
  const [ticketTopic, setTicketTopic] = useState("problem_order");
  const [ticketRole, setTicketRole] = useState<"buyer" | "seller">("seller");
  const [ticketOrderId, setTicketOrderId] = useState("");
  const [ticketComment, setTicketComment] = useState("");
  const [ticketSubmitting, setTicketSubmitting] = useState(false);
  const [lastTicketUrl, setLastTicketUrl] = useState<string | null>(null);
  const [ticketHistory, setTicketHistory] = useState<any[]>([]);
  const [ticketHistoryLoading, setTicketHistoryLoading] = useState(false);
  const [ticketAIDrafting, setTicketAIDrafting] = useState(false);
  const [ticketAIAnalysis, setTicketAIAnalysis] = useState<any | null>(null);
  const [submittingAccount, setSubmittingAccount] = useState(false);
  const [blacklistEntries, setBlacklistEntries] = useState<BlacklistEntry[]>([]);
  const [blacklistQuery, setBlacklistQuery] = useState("");
  const [blacklistLoading, setBlacklistLoading] = useState(false);
  const [blacklistOwner, setBlacklistOwner] = useState("");
  const [blacklistOrderId, setBlacklistOrderId] = useState("");
  const [blacklistReason, setBlacklistReason] = useState("");
  const [blacklistSelected, setBlacklistSelected] = useState<string[]>([]);
  const [blacklistEditingId, setBlacklistEditingId] = useState<string | number | null>(null);
  const [blacklistEditOwner, setBlacklistEditOwner] = useState("");
  const [blacklistEditReason, setBlacklistEditReason] = useState("");
  const [blacklistResolving, setBlacklistResolving] = useState(false);
  const [blacklistLogs, setBlacklistLogs] = useState<BlacklistLog[]>([]);
  const [blacklistLogsLoading, setBlacklistLogsLoading] = useState(false);
  const [lots, setLots] = useState<LotRow[]>([]);
  const [lotsLoading, setLotsLoading] = useState(false);
  const [lotsQuery, setLotsQuery] = useState("");
  const [lotNumber, setLotNumber] = useState("");
  const [lotAccountId, setLotAccountId] = useState("");
  const [lotUrl, setLotUrl] = useState("");
  const [lotKeyId, setLotKeyId] = useState("");
  const [lotActionBusy, setLotActionBusy] = useState(false);
  const [editingLotNumber, setEditingLotNumber] = useState<number | null>(null);
  const [editingLotKeyId, setEditingLotKeyId] = useState<number | null>(null);
  const [editLotNumber, setEditLotNumber] = useState("");
  const [editLotAccountId, setEditLotAccountId] = useState("");
  const [editLotUrl, setEditLotUrl] = useState("");
  const [newKeyLabel, setNewKeyLabel] = useState("");
  const [newKeyValue, setNewKeyValue] = useState("");
  const [newKeyDefault, setNewKeyDefault] = useState(false);
  const [editingKeyId, setEditingKeyId] = useState<number | null>(null);
  const [editKeyLabel, setEditKeyLabel] = useState("");
  const [editKeyValue, setEditKeyValue] = useState("");
  const [keyActionBusy, setKeyActionBusy] = useState(false);
  const [newKeyProxyUrl, setNewKeyProxyUrl] = useState("");
  const [newKeyProxyUsername, setNewKeyProxyUsername] = useState("");
  const [newKeyProxyPassword, setNewKeyProxyPassword] = useState("");
  const [editKeyProxyUrl, setEditKeyProxyUrl] = useState("");
  const [editKeyProxyUsername, setEditKeyProxyUsername] = useState("");
  const [editKeyProxyPassword, setEditKeyProxyPassword] = useState("");
  const [profileName, setProfileName] = useState("");

  const isHardReload = useMemo(() => {
    try {
      const navEntries = performance.getEntriesByType?.("navigation") as PerformanceNavigationTiming[] | undefined;
      if (navEntries && navEntries.length) {
        return navEntries[0]?.type === "reload";
      }
      // Fallback for older browsers
      // @ts-expect-error legacy navigation type
      return performance.navigation?.type === 1;
    } catch {
      return false;
    }
  }, []);

  const groupedCategories = useMemo(() => {
    const term = categorySearch.trim().toLowerCase();
    const idTerm = categoryIdSearch.trim();
    const normalized = (categoryOptions || []).map((c) => {
      const name = (c.name || "").trim();
      let game = (c.game || "").trim();
      let category = (c.category || "").trim();
      if ((!game || !category) && name.includes(" - ")) {
        const parts = name.split(" - ", 2).map((p) => p.trim());
        if (!game) game = parts[0] || game;
        if (!category) category = parts[1] || category;
      }
      return { ...c, game, category };
    });
    const filtered = normalized.filter((c) => {
      const game = (c.game || "").trim();
      const category = (c.category || "").trim();
      if (!game || !category) return false;
      if (game === category) return false;
      const haystack = `${c.name || ""} ${game} ${category}`.toLowerCase();
      if (term && !haystack.includes(term)) return false;
      if (idTerm && !String(c.id).includes(idTerm)) return false;
      return true;
    });
    return filtered.sort(
      (a, b) =>
        (a.game || "Other").localeCompare(b.game || "Other") ||
        (a.category || a.name || "").localeCompare(b.category || b.name || "") ||
        a.id - b.id
    );
  }, [categoryOptions, categorySearch, categoryIdSearch]);

  const [tick, setTick] = useState(0);
  const now = useMemo(() => Date.now(), [tick]);
  const { toast, showToast } = useToast();
  const activeKeyRef = useRef<KeyScope>(activeKeyId);
  activeKeyRef.current = activeKeyId;
  const activeKeyScope = useMemo(
    () => (activeKeyId === "all" ? "all" : String(activeKeyId)),
    [activeKeyId]
  );
  const sessionKey = useMemo(
    () => (token ? `${profileName || "session"}:${activeKeyScope}` : ""),
    [token, profileName, activeKeyScope]
  );
  const cachedSessionKey = useMemo(() => {
    try {
      return localStorage.getItem("fpa_last_session_key") || "";
    } catch {
      return "";
    }
  }, [activeKeyScope]);
  const effectiveSessionKey = useMemo(() => {
    if (authState === "unknown" && cachedSessionKey) return cachedSessionKey;
    return sessionKey;
  }, [authState, cachedSessionKey, sessionKey]);
  const lastSessionRef = useRef<string>("");
  const sessionKeyRef = useRef<string>(effectiveSessionKey);
  sessionKeyRef.current = effectiveSessionKey;
  const presenceWarmupRef = useRef<number>(0);
  const presenceCacheRef = useRef<Map<string, { data: PresenceData; fetchedAt: number }>>(new Map());
  const overviewRequestRef = useRef<number>(0);
  const scopedKey = useCallback(
    (key: string) => `${key}:u:${effectiveSessionKey || "anon"}`,
    [effectiveSessionKey]
  );
  const adminCallCountsRef = useRef<Record<string, number>>({});
  const adminCallToastRef = useRef<number>(0);
  const selectedChatRef = useRef<string | number | null>(null);
  const chatHistoryRequestRef = useRef<number>(0);
  const lastClearedChatRef = useRef<string | null>(null);
  const chatScrollRef = useRef<HTMLDivElement | null>(null);
  const clearedAdminCallsRef = useRef<Record<string, number>>({});

  useEffect(() => {
    if (authState !== "authed") return;
    if (!sessionKey) return;
    try {
      localStorage.setItem("fpa_last_session_key", sessionKey);
    } catch {
      // ignore storage failures
    }
  }, [authState, sessionKey]);

  const clearAppCaches = useCallback(() => {
    memoryCache.clear();
    try {
      for (let i = localStorage.length - 1; i >= 0; i -= 1) {
        const key = localStorage.key(i);
        if (key && key.startsWith(CACHE_PREFIX)) {
          localStorage.removeItem(key);
        }
      }
      localStorage.removeItem("fpa_last_session_key");
    } catch {
      // ignore cache cleanup errors
    }
  }, []);

  useEffect(() => {
    if (authState === "authed" && !token) {
      setAuthState("guest");
      clearAppCaches();
    }
  }, [authState, token, clearAppCaches]);

  const parseAdminCallTimestamp = (value?: string | null) => {
    if (!value) return null;
    const raw = String(value).trim();
    if (!raw) return null;
    if (/^\d+$/.test(raw)) {
      const numeric = Number(raw);
      if (!Number.isFinite(numeric)) return null;
      return numeric < 1e12 ? numeric * 1000 : numeric;
    }
    const parsed = Date.parse(raw);
    return Number.isNaN(parsed) ? null : parsed;
  };

  useEffect(() => {
    const root = document.documentElement;
    if (uiMode === "dark") {
      root.classList.add("dark");
    } else {
      root.classList.remove("dark");
    }
  }, [uiMode]);

  useEffect(() => {
    selectedChatRef.current = selectedChat;
  }, [selectedChat]);

  const api = useMemo(
    () =>
      createApiClient({
        onUnauthorized: () => {
          setToken("");
          setProfileName("");
          setAuthState("guest");
          clearAppCaches();
        },
        getKeyId: () => activeKeyRef.current,
      }),
    [clearAppCaches]
  );

  const { apiFetch, apiFetchWithMeta } = api;

  const keyLabelMap = useMemo(() => {
    const map = new Map<number, string>();
    userKeys.forEach((item) => {
      if (typeof item.id === "number") {
        map.set(item.id, item.label || `Workspace ${item.id}`);
      }
    });
    return map;
  }, [userKeys]);

  const defaultKeyLabel = useMemo(() => {
    const fallback = userKeys.find((item) => item.is_default);
    return fallback?.label || "Default";
  }, [userKeys]);

  const resolveKeyLabel = useCallback(
    (keyId?: number | string | null) => {
      if (keyId === null || keyId === undefined || keyId === "") {
        return defaultKeyLabel;
      }
      const numeric = Number(keyId);
      if (!Number.isFinite(numeric) || numeric === 0) return defaultKeyLabel;
      return keyLabelMap.get(numeric) || `Workspace ${numeric}`;
    },
    [defaultKeyLabel, keyLabelMap]
  );

  const buildKeyHeader = useCallback(
    (keyId?: number | string | null) => {
      if (activeKeyId !== "all") return undefined;
      const numeric = Number(keyId);
      if (!Number.isFinite(numeric)) return undefined;
      return { "x-key-id": String(numeric) };
    },
    [activeKeyId]
  );

  const loadKeys = useCallback(async () => {
    if (!token) return;
    setKeysLoading(true);
    try {
      const data = await apiFetch<{ items: UserKey[] }>("/api/keys");
      const items = Array.isArray(data?.items) ? data.items : [];
      setUserKeys(items);
    } catch {
      setUserKeys([]);
    } finally {
      setKeysLoading(false);
    }
  }, [token, apiFetch]);

  const applyAdminCallOverrides = useCallback((items: ChatItem[]) => {
    const cleared = clearedAdminCallsRef.current;
    return items.map((chat) => {
      const key = String(chat.id ?? "");
      const clearedAt = cleared[key];
      if (!clearedAt) return chat;
      const lastCalledAt = parseAdminCallTimestamp(chat.adminLastCalledAt);
      if (lastCalledAt && lastCalledAt > clearedAt) {
        delete cleared[key];
        return chat;
      }
      if (!chat.adminCalls && !lastCalledAt) {
        delete cleared[key];
        return chat;
      }
      return { ...chat, adminCalls: 0, adminLastCalledAt: null };
    });
  }, []);

  useEffect(() => {
    if (!token) {
      setUserKeys([]);
      return;
    }
    loadKeys();
  }, [token, loadKeys]);

  useEffect(() => {
    if (!token || !userKeys.length) return;
    setActiveKeyId((prev) => {
      if (prev === "all") return prev;
      if (userKeys.some((item) => item.id === prev)) return prev;
      const fallback = userKeys.find((item) => item.is_default) ?? userKeys[0];
      return fallback ? fallback.id : "all";
    });
  }, [token, userKeys]);

  useEffect(() => {
    try {
      localStorage.setItem("fpa_active_key_id", activeKeyId === "all" ? "all" : String(activeKeyId));
    } catch {
      // ignore storage errors
    }
  }, [activeKeyId]);

  useEffect(() => {
    if (activeKeyId === "all") return;
    setLotKeyId((prev) => prev || String(activeKeyId));
  }, [activeKeyId]);

  const clearAdminCall = useCallback(
    async (chatId: string | number | null) => {
      if (!token || chatId === null || chatId === undefined) return;
      const chatKey = String(chatId);
      const currentCount = adminCallCountsRef.current[chatKey] || 0;
      if (lastClearedChatRef.current === chatKey && currentCount === 0) return;
      lastClearedChatRef.current = chatKey;
      clearedAdminCallsRef.current[chatKey] = Date.now();
      adminCallCountsRef.current[chatKey] = 0;
      setChats((prev) =>
        prev.map((chat) =>
          String(chat.id) === chatKey ? { ...chat, adminCalls: 0, adminLastCalledAt: null } : chat
        )
      );
      try {
        await apiFetch(`/api/admin-calls/${encodeURIComponent(chatKey)}/clear`, { method: "POST" });
      } catch {
        // ignore clear errors
      }
    },
    [token, apiFetch]
  );

  const sendChatWs = useCallback((payload: any) => {
    const ws = chatWsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    try {
      ws.send(JSON.stringify(payload));
      return true;
    } catch {
      return false;
    }
  }, []);

  const updateChatPreview = useCallback((chatId: string | number, item: ChatMessage) => {
    const idKey = String(chatId);
    setChats((prev) =>
      prev.map((chat) =>
        String(chat.id) === idKey
          ? {
              ...chat,
              last: item.text || chat.last,
              time: item.sentAt || chat.time,
            }
          : chat
      )
    );
  }, []);

  const appendChatMessage = useCallback(
    (chatId: string | number, item: ChatMessage) => {
      const idKey = String(chatId);
      const cacheKey = scopedKey(`${CHAT_HISTORY_CACHE_PREFIX}${idKey}`);
      setChatMessages((prev) => {
        if (!item) return prev;
        const incomingId = item.id ?? "";
        const incomingKey = String(incomingId);
        if (prev.some((m) => String(m.id) === incomingKey)) {
          return prev;
        }
        const last = prev[prev.length - 1];
        let next = prev;
        if (
          last &&
          String(last.id).startsWith("local-") &&
          last.text === item.text &&
          (item.byBot || last.byBot)
        ) {
          next = [...prev];
          next[next.length - 1] = item;
        } else {
          next = [...prev, item];
        }
        writeCache(cacheKey, next);
        return next;
      });
      updateChatPreview(idKey, item);
    },
    [updateChatPreview, scopedKey]
  );

  const swrFetch = useCallback(
    async <T,>({
      key,
      url,
      ttl,
      revalidate = false,
      onData,
      onLoading,
      map,
    }: {
      key: string;
      url: string;
      ttl: number;
      revalidate?: boolean;
      onData: (data: T) => void;
      onLoading?: (loading: boolean) => void;
      map?: (payload: any) => T;
    }) => {
      const guardKey = effectiveSessionKey;
      const isActive = () => sessionKeyRef.current === guardKey;
      const cached = readCache<T>(key, ttl);
      if (cached?.data && isActive()) {
        onData(cached.data);
      }
      if (onLoading && isActive()) {
        onLoading(!cached?.data);
      }
      const shouldRevalidate = revalidate || !cached || cached.isStale;
      if (!shouldRevalidate) {
        if (onLoading && isActive()) onLoading(false);
        return;
      }
      if (typeof navigator !== "undefined" && "onLine" in navigator && !navigator.onLine) {
        if (onLoading && isActive()) onLoading(false);
        return;
      }
      if (revalidate) {
        const last = revalidateGuards.get(key) || 0;
        const nowTs = Date.now();
        if (nowTs - last < REVALIDATE_THROTTLE_MS) {
          if (onLoading && isActive()) onLoading(false);
          return;
        }
        revalidateGuards.set(key, nowTs);
      }
      const inflight = inflightRequests.get(key);
      if (inflight) {
        await inflight.catch(() => null);
        if (onLoading && isActive()) onLoading(false);
        return;
      }
      const request = (async () => {
        const headers: Record<string, string> = {};
        if (cached?.etag) {
          headers["If-None-Match"] = cached.etag;
        }
        const result = await apiFetchWithMeta<any>(url, {
          headers: Object.keys(headers).length ? headers : undefined,
        });
        if (result.status === 304 && cached?.data) {
          writeCache(key, cached.data, cached.etag);
          return cached as CacheEntry<T>;
        }
        if (!result.data) return null;
        const mapped = map ? map(result.data) : (result.data as T);
        const etag = result.headers.get("etag") || cached?.etag;
        writeCache(key, mapped, etag || undefined);
        return { data: mapped, ts: Date.now(), etag: etag || undefined } as CacheEntry<T>;
      })();
      inflightRequests.set(key, request);
      try {
        const next = await request;
        if (next?.data && isActive()) {
          onData(next.data);
        }
      } catch {
        // keep cached data
      } finally {
        inflightRequests.delete(key);
        if (onLoading && isActive()) onLoading(false);
      }
    },
    [apiFetchWithMeta, effectiveSessionKey]
  );

  const selectedAccount = useMemo(() => {
    if (selectedAccountId === null || selectedAccountId === undefined) return null;
    return accountsTable.find((acc) => String(acc.id) === String(selectedAccountId)) || null;
  }, [accountsTable, selectedAccountId]);

  const selectedRental = useMemo(() => {
    if (selectedRentalId === null || selectedRentalId === undefined) return null;
    return rentalsTable.find((r) => String(r.id) === String(selectedRentalId)) || null;
  }, [rentalsTable, selectedRentalId]);

  useEffect(() => {
    if (!selectedAccount) {
      setAssignOwner("");
      setAccountEditName("");
      setAccountEditLogin("");
      setAccountEditPassword("");
      setAccountEditMmr("");
      setAccountEditKeyId("");
      return;
    }
    const owner =
      selectedAccount.owner && String(selectedAccount.owner).trim().toUpperCase() !== "OTHER_ACCOUNT"
        ? selectedAccount.owner
        : "";
    setAssignOwner(owner);
    setAccountEditName(selectedAccount.name || "");
    setAccountEditLogin(selectedAccount.login || "");
    setAccountEditPassword(selectedAccount.password || "");
    setAccountEditMmr(
      selectedAccount.mmr !== null && selectedAccount.mmr !== undefined ? String(selectedAccount.mmr) : ""
    );
    setAccountEditKeyId(
      selectedAccount.keyId !== null && selectedAccount.keyId !== undefined ? String(selectedAccount.keyId) : ""
    );
  }, [selectedAccount]);

  useEffect(() => {
    if (!selectedRental) {
      setRentalExtendHours("");
      setRentalExtendMinutes("");
    }
  }, [selectedRental]);

  useEffect(() => {
    let active = true;
    const checkSession = async () => {
      try {
        const response = await fetch("/api/auth/me", { credentials: "include" });
        if (!active) return;
        if (response.ok) {
          const data = (await response.json()) as { username?: string };
          if (data?.username) {
            setToken("session");
            setProfileName(data.username);
            setAuthState("authed");
          } else {
            setToken("");
            setProfileName("");
            setAuthState("guest");
            clearAppCaches();
          }
          return;
        }
        if (response.status === 401) {
          setToken("");
          setProfileName("");
          setAuthState("guest");
          clearAppCaches();
          return;
        }
        setToken("");
        setProfileName("");
        setAuthState("guest");
        clearAppCaches();
      } catch {
        if (!active) return;
        setToken("");
        setProfileName("");
        setAuthState("guest");
        clearAppCaches();
      } finally {
        // authState drives rendering; no blocking on session checks
      }
    };
    checkSession();
    return () => {
      active = false;
    };
  }, [clearAppCaches]);

  const rentedAccountLookup = useMemo(() => {
    const ids = new Set<string>();
    const logins = new Set<string>();
    const names = new Set<string>();
    const steamIds = new Set<string>();
    rentalsTable.forEach((r) => {
      if (r.id !== undefined && r.id !== null) ids.add(String(r.id));
      const loginKey = normalizeKey(r.login);
      if (loginKey) logins.add(loginKey);
      const nameKey = normalizeKey(r.accountName);
      if (nameKey) names.add(nameKey);
      const steamKey = normalizeKey(r.steamId);
      if (steamKey) steamIds.add(steamKey);
    });
    return { ids, logins, names, steamIds };
  }, [rentalsTable]);

  const isAccountRented = (acc: AccountRow) => {
    const idKey = acc.id !== undefined && acc.id !== null ? String(acc.id) : "";
    const loginKey = normalizeKey(acc.login);
    const nameKey = normalizeKey(acc.name);
    const steamKey = normalizeKey(acc.steamId);
    const ownerKey = normalizeKey(acc.owner);
    if (ownerKey) return true;
    return (
      (idKey && rentedAccountLookup.ids.has(idKey)) ||
      (loginKey && rentedAccountLookup.logins.has(loginKey)) ||
      (nameKey && rentedAccountLookup.names.has(nameKey)) ||
      (steamKey && rentedAccountLookup.steamIds.has(steamKey))
    );
  };

  useEffect(() => {
    const targetNav = pathToNavId(pathname);
    setActiveNav(targetNav);
    if (authState === "unknown") return;
    const desired =
      authState === "guest"
        ? pathname === "/login" || pathname === "/authentication" || pathname === "/authencation"
          ? pathname
          : "/authencation"
        : navIdToPath[targetNav] || "/dashboard";
    if (pathname !== desired) {
      window.history.replaceState(null, "", desired);
      setPathname(desired);
    }
  }, [authState, pathname]);

  useEffect(() => {
    if (authState === "guest") {
      setOverview(createEmptyOverview());
      setAccountsTable([]);
      setRentalsTable([]);
      setOverviewHydrated(false);
      setFunpayStats(createEmptyFunpayStats());
      setNotifications([]);
      setChats([]);
      setChatMessages([]);
      setOrdersHistory([]);
      setSelectedAccountId(null);
      setSelectedRentalId(null);
      setSelectedChat(null);
      setChatStreamActive(false);
      if (chatListStreamRef.current) {
        chatListStreamRef.current.close();
        chatListStreamRef.current = null;
      }
      if (chatHistoryStreamRef.current) {
        chatHistoryStreamRef.current.close();
        chatHistoryStreamRef.current = null;
      }
      if (chatWsRef.current) {
        chatWsRef.current.close();
        chatWsRef.current = null;
      }
      if (chatWsHeartbeatRef.current) {
        window.clearInterval(chatWsHeartbeatRef.current);
        chatWsHeartbeatRef.current = null;
      }
      chatWsSubscribedRef.current = null;
      setChatWsConnected(false);
      lastSessionRef.current = "";
      return;
    }
    if (effectiveSessionKey === lastSessionRef.current && authState !== "unknown") return;
    setOverviewHydrated(false);
    const overviewCache = readCache<OverviewCachePayload>(scopedKey(OVERVIEW_CACHE_KEY), CACHE_TTLS.overview);
    if (overviewCache?.data && !overviewCache.isStale && !isHardReload) {
      setOverview(overviewCache.data.overview || createEmptyOverview());
      setAccountsTable(overviewCache.data.accounts || []);
      setRentalsTable(overviewCache.data.rentals || []);
    } else {
      setOverview(createEmptyOverview());
      setAccountsTable([]);
      setRentalsTable([]);
    }
    setFunpayStats(createEmptyFunpayStats());
    setNotifications([]);
    setChats([]);
    setChatMessages([]);
    setOrdersHistory([]);
    setSelectedAccountId(null);
    setSelectedRentalId(null);
    setSelectedChat(null);
    setChatStreamActive(false);
    if (chatListStreamRef.current) {
      chatListStreamRef.current.close();
      chatListStreamRef.current = null;
    }
    if (chatHistoryStreamRef.current) {
      chatHistoryStreamRef.current.close();
      chatHistoryStreamRef.current = null;
    }
    if (chatWsRef.current) {
      chatWsRef.current.close();
      chatWsRef.current = null;
    }
    if (chatWsHeartbeatRef.current) {
      window.clearInterval(chatWsHeartbeatRef.current);
      chatWsHeartbeatRef.current = null;
    }
    chatWsSubscribedRef.current = null;
    setChatWsConnected(false);
    lastSessionRef.current = effectiveSessionKey;
  }, [authState, effectiveSessionKey, isHardReload, scopedKey]);

  const handleRegister = async (payload: { username: string; password: string; golden_key: string }) => {
    try {
      const data = await apiFetch<{ username: string }>("/api/auth/register", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setToken("session");
      setProfileName(data.username || payload.username);
      setAuthState("authed");
      setSessionChecked(true);
      showToast("Registration complete. You're logged in.");
    } catch (error) {
      showToast((error as Error).message || "Registration failed.", "error");
    }
  };

  const handleLogin = async (payload: { username: string; password: string }) => {
    try {
      const data = await apiFetch<{ username: string }>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setToken("session");
      setProfileName(data.username || payload.username);
      setAuthState("authed");
      setSessionChecked(true);
      showToast("Login successful.");
    } catch (error) {
      showToast((error as Error).message || "Login failed.", "error");
    }
  };

  const handleLogout = async () => {
    try {
      await apiFetch("/api/auth/logout", { method: "POST" });
    } catch {
      // ignore logout errors
    }
    setToken("");
    setProfileName("");
    setAuthState("guest");
    clearAppCaches();
  };

  const handleToggleAutoTickets = async (enabled: boolean) => {
    const prev = autoTickets;
    setAutoTickets(enabled);
    try {
      await apiFetch("/api/settings/auto-ticket", {
        method: "POST",
        body: JSON.stringify({ enabled }),
      });
      showToast(enabled ? "Auto-tickets enabled." : "Auto-tickets disabled.", "success");
    } catch (error) {
      showToast((error as Error).message || "Failed to update auto-ticket setting.", "error");
      setAutoTickets(prev);
    }
  };

  const handleToggleAutoRaise = async (enabled: boolean) => {
    const prev = autoRaise;
    setAutoRaise(enabled);
    try {
      const cats = autoRaiseCategories
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean)
        .map((v) => Number(v))
        .filter((v) => Number.isFinite(v));
      await apiFetch("/api/settings/auto-raise/config", {
        method: "POST",
        body: JSON.stringify({ enabled, categories: cats }),
      });
      showToast(enabled ? "Auto-raise enabled." : "Auto-raise disabled.", "success");
    } catch (error) {
      showToast((error as Error).message || "Failed to update auto-raise setting.", "error");
      setAutoRaise(prev);
    }
  };

  const handleCreateKey = async () => {
    if (keyActionBusy) return;
    const label = newKeyLabel.trim() || "Workspace";
    const goldenKey = newKeyValue.trim();
    const proxyUrl = newKeyProxyUrl.trim();
    const proxyUser = newKeyProxyUsername.trim();
    const proxyPass = newKeyProxyPassword.trim();
    if (!goldenKey) {
      showToast("Golden key is required.", "error");
      return;
    }
    if (!proxyUrl) {
      showToast("Proxy is required for each workspace.", "error");
      return;
    }
    setKeyActionBusy(true);
    try {
      const result = await apiFetch<{ id: number }>("/api/keys", {
        method: "POST",
        body: JSON.stringify({
          label,
          golden_key: goldenKey,
          make_default: newKeyDefault,
          proxy_url: proxyUrl,
          proxy_username: proxyUser || undefined,
          proxy_password: proxyPass || undefined,
        }),
      });
      showToast("Workspace added.");
      setNewKeyLabel("");
      setNewKeyValue("");
      setNewKeyProxyUrl("");
      setNewKeyProxyUsername("");
      setNewKeyProxyPassword("");
      setNewKeyDefault(false);
      await loadKeys();
      if (newKeyDefault && result?.id) {
        setActiveKeyId(result.id);
      }
    } catch (error) {
      showToast((error as Error).message || "Failed to add workspace.", "error");
    } finally {
      setKeyActionBusy(false);
    }
  };

  const startEditKey = (item: UserKey) => {
    setEditingKeyId(item.id);
    setEditKeyLabel(item.label || "");
    setEditKeyValue("");
    setEditKeyProxyUrl(item.proxy_url || "");
    setEditKeyProxyUsername(item.proxy_username || "");
    setEditKeyProxyPassword(item.proxy_password || "");
  };

  const cancelEditKey = () => {
    setEditingKeyId(null);
    setEditKeyLabel("");
    setEditKeyValue("");
    setEditKeyProxyUrl("");
    setEditKeyProxyUsername("");
    setEditKeyProxyPassword("");
  };

  const handleSaveKeyEdit = async () => {
    if (editingKeyId === null || keyActionBusy) return;
    const current = userKeys.find((item) => item.id === editingKeyId);
    if (!current) {
      cancelEditKey();
      return;
    }
    const nextLabel = editKeyLabel.trim();
    const nextKey = editKeyValue.trim();
    const nextProxyUrl = editKeyProxyUrl.trim();
    const nextProxyUser = editKeyProxyUsername.trim();
    const nextProxyPass = editKeyProxyPassword.trim();
    if (!nextProxyUrl) {
      showToast("Proxy is required for this workspace.", "error");
      return;
    }
    const payload: Record<string, unknown> = {};
    if (nextLabel && nextLabel !== current.label) payload.label = nextLabel;
    if (nextKey) payload.golden_key = nextKey;
    if (nextProxyUrl !== current.proxy_url?.trim()) payload.proxy_url = nextProxyUrl;
    if (nextProxyUser !== (current.proxy_username || "").trim()) payload.proxy_username = nextProxyUser;
    if (nextProxyPass !== (current.proxy_password || "").trim()) payload.proxy_password = nextProxyPass;
    if (!Object.keys(payload).length) {
      showToast("No changes to save.", "error");
      return;
    }
    setKeyActionBusy(true);
    try {
      await apiFetch(`/api/keys/${editingKeyId}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      showToast("Workspace updated.");
      cancelEditKey();
      await loadKeys();
    } catch (error) {
      showToast((error as Error).message || "Failed to update workspace.", "error");
    } finally {
      setKeyActionBusy(false);
    }
  };

  const handleSetDefaultKey = async (keyId: number) => {
    if (keyActionBusy) return;
    setKeyActionBusy(true);
    try {
      await apiFetch(`/api/keys/${keyId}/default`, { method: "POST" });
      showToast("Default workspace updated.");
      await loadKeys();
      setActiveKeyId(keyId);
    } catch (error) {
      showToast((error as Error).message || "Failed to set default workspace.", "error");
    } finally {
      setKeyActionBusy(false);
    }
  };

  const handleDeleteKey = async (keyId: number) => {
    if (keyActionBusy) return;
    if (
      !window.confirm(
        "Delete this workspace and all data linked to it (accounts, lots, history)? This cannot be undone."
      )
    ) {
      return;
    }
    setKeyActionBusy(true);
    try {
      await apiFetch(`/api/keys/${keyId}`, { method: "DELETE" });
      showToast("Workspace removed.");
      clearAppCaches();
      await loadKeys();
      revalidateActive();
    } catch (error) {
      showToast((error as Error).message || "Failed to delete workspace.", "error");
    } finally {
      setKeyActionBusy(false);
    }
  };

  const mapChatItems = useCallback(
    (payload: any): ChatItem[] =>
      (payload.items || []).map((c: any, idx: number) => ({
        id: c.id ?? idx,
        name: c.name || c.chat_name || `Chat ${idx + 1}`,
        last: c.last_message_text || c.preview || "",
        time: c.last_message_time || c.time || "",
        unread: !!c.unread,
        avatarUrl: c.avatar_url ?? c.avatarUrl ?? c.avatar ?? null,
        adminCalls: Number(c.admin_calls ?? c.adminCalls ?? 0) || 0,
        adminLastCalledAt: c.admin_last_called_at ?? c.adminLastCalledAt ?? null,
      })),
    []
  );

  const mapChatMessages = useCallback(
    (payload: any): ChatMessage[] =>
      (payload.items || []).map((m: any, idx: number) => ({
        id: m.id ?? idx,
        author: m.author || m.user || (m.by_bot ? "Bot" : "User"),
        text: m.text || m.body || "",
        sentAt: m.sent_time || m.sent_at || m.time || "",
        byBot: !!m.by_bot,
        adminCall: typeof m.admin_call === "boolean" ? m.admin_call : isAdminCallText(m.text || m.body || ""),
      })),
    []
  );

  const loadOverview = useCallback(async (mode: "fast" | "full" = "full") => {
    const requestId = ++overviewRequestRef.current;
    const guardKey = effectiveSessionKey;
    const cacheKey = scopedKey(OVERVIEW_CACHE_KEY);
    const cached = readCache<OverviewCachePayload>(cacheKey, CACHE_TTLS.overview);
    if (cached?.data && !cached.isStale && !isHardReload && sessionKeyRef.current === guardKey) {
      setOverview(cached.data.overview || createEmptyOverview());
      setAccountsTable(cached.data.accounts || []);
      setRentalsTable(cached.data.rentals || []);
    }
    try {
      const useFast = mode === "fast";
      const qs = new URLSearchParams();
      if (useFast) {
        qs.set("fast", "1");
      } else {
        qs.set("fast", "0");
        qs.set("refresh", "1");
      }
      const url = qs.toString() ? `/api/dashboard?${qs.toString()}` : "/api/dashboard";
      const payload = await apiFetch<DashboardPayload>(url).catch(() => ({} as DashboardPayload));
      if (overviewRequestRef.current !== requestId || sessionKeyRef.current !== guardKey) {
        return;
      }

      const stats = payload?.stats || {};
      const accountsList = Array.isArray(payload?.accounts) ? (payload.accounts as any[]) : [];
      const rentalsList = Array.isArray(payload?.rentals) ? (payload.rentals as any[]) : [];

      const totalAccounts =
        (stats as any)?.accounts_total ??
        (Array.isArray(payload?.accounts) ? accountsList.length : null);

      const active =
        (stats as any)?.active_rentals ??
        (Array.isArray(payload?.rentals) ? rentalsList.length : null);

      const past24 = (stats as any)?.rentals_last24 ?? (stats as any)?.recent_rentals ?? null;
      const totalHours = (stats as any)?.total_hours ?? null;

      const freeAccounts =
        (stats as any)?.free_accounts ??
        (totalAccounts != null && active != null ? Math.max(totalAccounts - active, 0) : null);

      const nextOverview = {
        totalAccounts,
        activeRentals: active,
        freeAccounts,
        past24,
        totalHours,
      };
      setOverview(nextOverview);
      if (mode === "full") {
        setOverviewHydrated(true);
      }

      const accountSteamMap = new Map<string, string>();
      let mappedAccounts: AccountRow[] = [];

      // inventory table
      if (accountsList.length) {
        mappedAccounts = accountsList.map((a, idx) => {
          const name = (() => {
            const preferred =
              a.account_name ??
              a.account ??
              a.acc_name ??
              a.title ??
              a.name ??
              a.login ??
              "";
            const cleaned = String(preferred).trim();
            return cleaned || `ID ${a.id ?? idx}`;
          })();
          const login = a.login ?? "";
          const steamId = extractSteamId(a);
          if (steamId) {
            if (login) accountSteamMap.set(login, steamId);
            accountSteamMap.set(name, steamId);
          }
          const durationHoursRaw = Number(a.rental_duration ?? a.rental_hours ?? a.duration_hours);
          const durationMinutesRaw = Number(
            a.rental_duration_minutes ?? a.rental_minutes ?? a.duration_minutes
          );
          return {
            id: a.id ?? idx,
            name,
            login,
            password: a.password ?? a.pass ?? "",
            steamId,
            mmr: a.mmr ?? a.mmr_estimate ?? a.rank ?? a.elo ?? null,
            owner: a.owner ?? null,
            rentalStart: a.rental_start ?? a.rentalStart ?? null,
            rentalDurationMinutes: Number.isFinite(durationMinutesRaw) ? durationMinutesRaw : null,
            rentalDurationHours: Number.isFinite(durationHoursRaw) ? durationHoursRaw : null,
            accountFrozen: !!(a.account_frozen ?? a.accountFrozen),
            rentalFrozen: !!(a.rental_frozen ?? a.rentalFrozen),
            rentalFrozenAt: a.rental_frozen_at ?? a.rentalFrozenAt ?? null,
            keyId: a.key_id ?? a.keyId ?? null,
          };
        });
        setAccountsTable(mappedAccounts);
      } else {
        setAccountsTable([]);
      }

      let mappedRentals: RentalRow[] = [];
      // rentals table
      if (rentalsList.length) {
        mappedRentals = rentalsList.map((r, idx) => {
            const matchTimeRaw = r.match_time ?? r.matchTime ?? null;
            const matchTime = matchTimeRaw ? String(matchTimeRaw) : null;
            const matchSecondsRaw = Number(r.match_seconds ?? r.matchSeconds ?? r.matchtime);
            const matchSeconds = Number.isFinite(matchSecondsRaw) ? Math.max(0, Math.floor(matchSecondsRaw)) : null;
            const hasPresence =
              r.in_match !== undefined ||
              r.in_game !== undefined ||
              r.hero_name ||
              r.presence_label ||
              matchTime !== null ||
              matchSeconds !== null;
            const presenceFetchedAt = hasPresence ? Date.now() : null;
            const presence = hasPresence
              ? {
                  in_match: !!r.in_match,
                  in_game: !!r.in_game,
                  hero_name: r.hero_name ?? null,
                  match_time: matchTime,
                  match_seconds: matchSeconds,
                  fetched_at: presenceFetchedAt,
                }
              : null;
            const derivedStatus = presence
              ? presence.in_match
                ? "In match"
                : presence.in_game
                  ? "In game"
                  : "Offline"
              : "";
            const durationSec = (() => {
              const explicit = Number(r.duration_sec ?? r.duration_seconds ?? r.seconds);
              if (Number.isFinite(explicit) && explicit >= 0) return explicit;
              const minutesRaw = Number(r.rental_duration_minutes ?? r.rental_minutes);
              if (Number.isFinite(minutesRaw) && minutesRaw > 0) return minutesRaw * 60;
              const hoursRaw = Number(r.rental_duration);
              if (Number.isFinite(hoursRaw) && hoursRaw > 0) return hoursRaw * 3600;
              return null;
            })();
            return {
              id: r.id ?? idx,
              accountName: r.account_name ?? r.login ?? `Rental ${idx + 1}`,
              login: r.login ?? null,
              buyer: r.owner ?? r.buyer ?? r.rented_by ?? "",
              durationSec,
              startedAt: r.started_at ?? r.start_time ?? r.created_at ?? r.rental_start ?? r.rental_start_time,
              status: derivedStatus,
              hero: r.hero ?? r.character ?? "",
              chatUrl: r.chat_url ?? r.chatUrl ?? r.chat ?? r.chat_link ?? null,
              steamId:
                r.steamid ??
                r.steam_id ??
                r.steamId ??
                extractSteamId(r) ??
                extractSteamId({ mafile_json: r.mafile_json, mafile: r.mafile }) ??
                (r.login ? accountSteamMap.get(r.login) : undefined) ??
                (r.account_name ? accountSteamMap.get(r.account_name) : undefined),
              presence,
              presenceLabel: r.presence_label ?? null,
              presenceObservedAt: presenceFetchedAt,
              adminCalls: Number(r.admin_calls ?? r.adminCalls ?? 0) || 0,
              adminLastCalledAt: r.admin_last_called_at ?? r.adminLastCalledAt ?? null,
              rentalFrozen: !!(r.rental_frozen ?? r.rentalFrozen),
              rentalFrozenAt: r.rental_frozen_at ?? r.rentalFrozenAt ?? null,
              keyId: r.key_id ?? r.keyId ?? null,
            };
          });
        setRentalsTable(mappedRentals);
      } else {
        setRentalsTable([]);
      }

      writeCache(cacheKey, {
        overview: nextOverview,
        accounts: mappedAccounts,
        rentals: mappedRentals,
      });
    } catch {
      // ignore overview load errors
    }
  }, [apiFetch, scopedKey, effectiveSessionKey, isHardReload]);

  const loadNotifications = useCallback(async () => {
    try {
      const data = await apiFetch<{ items: any[] }>("/api/notifications?limit=50").catch(() => ({ items: [] }));
      const mapped: NotificationItem[] = (data.items || []).map((n, idx) => ({
        id: n.id ?? idx,
        level: n.level ?? n.type ?? "info",
        message: n.message ?? n.text ?? "",
        createdAt: n.created_at ?? n.time ?? "",
        owner: n.owner ?? n.user ?? "",
        accountId: n.account_id ?? n.account ?? "",
      }));
      setNotifications(mapped);
    } catch {
      setNotifications([]);
    }
  }, [apiFetch]);

  const loadFunpayStats = useCallback(
    async (refresh = false, revalidate = false) => {
      const qs = new URLSearchParams();
      if (refresh) qs.set("refresh", "1");
      const query = qs.toString();
      const url = query ? `/api/funpay/stats?${query}` : "/api/funpay/stats";
      await swrFetch<FunpayStatsPayload>({
        key: scopedKey(STATS_CACHE_KEY),
        url,
        ttl: CACHE_TTLS.stats,
        revalidate,
        onLoading: setFunpayStatsLoading,
        onData: setFunpayStats,
        map: (data) => ({
          balance: data.balance ?? null,
          balance_series: data.balance_series ?? [],
          orders: data.orders ?? { daily: [], weekly: [], monthly: [] },
          reviews: data.reviews ?? { daily: [], weekly: [], monthly: [] },
          generated_at: data.generated_at ?? null,
        }),
      });
    },
    [swrFetch, scopedKey]
  );

  const loadOrdersHistory = useCallback(
    async (queryText: string, revalidate = false) => {
      const trimmedQuery = queryText.trim();
      const cacheKey = scopedKey(
        `${ORDERS_HISTORY_CACHE_PREFIX}${encodeURIComponent(trimmedQuery || "all")}`
      );
      const qs = new URLSearchParams();
      if (trimmedQuery) qs.set("query", trimmedQuery);
      qs.set("limit", "200");
      qs.set("fast", "1");
      await swrFetch<OrderHistoryItem[]>({
        key: cacheKey,
        url: `/api/orders/history?${qs.toString()}`,
        ttl: CACHE_TTLS.orders,
        revalidate,
        onLoading: setOrdersLoading,
        onData: setOrdersHistory,
        map: (payload) =>
          (payload.items || []).map((item: any, idx: number) => ({
            id: item.id ?? idx,
            orderId: item.order_id ?? item.orderId ?? "",
            buyer: item.buyer ?? item.owner ?? "",
            accountName: item.account_name ?? item.accountName ?? "",
            accountId: item.account_id ?? item.accountId ?? null,
            login: item.login ?? null,
            steamId: item.steam_id ?? item.steamid ?? item.steamId ?? null,
            rentalMinutes: item.rental_minutes ?? item.rentalMinutes ?? null,
            amount: item.amount ?? null,
            price: item.price ?? null,
            action: item.action ?? "",
            createdAt: item.created_at ?? item.createdAt ?? null,
            chatUrl: item.chat_url ?? item.chatUrl ?? null,
            lotNumber: item.lot_number ?? item.lotNumber ?? null,
          })),
      });
    },
    [swrFetch, scopedKey]
  );

  const loadLots = useCallback(
    async (revalidate = false) => {
      if (!token) return;
      await swrFetch<LotRow[]>({
        key: scopedKey(LOTS_CACHE_KEY),
        url: "/api/lots",
        ttl: CACHE_TTLS.lots,
        revalidate,
        onLoading: setLotsLoading,
        onData: setLots,
        map: (payload) =>
          (payload.items || [])
            .map((item: any) => ({
              lotNumber: Number(item.lot_number ?? item.lotNumber ?? 0),
              accountId: Number(item.account_id ?? item.accountId ?? 0),
              accountName: item.account_name ?? item.accountName ?? "",
              lotUrl: item.lot_url ?? item.lotUrl ?? null,
              owner: item.owner ?? null,
              keyId: item.key_id ?? item.keyId ?? null,
            }))
            .filter((item: LotRow) => Number.isFinite(item.lotNumber) && Number.isFinite(item.accountId)),
      });
    },
    [token, swrFetch, scopedKey]
  );

  const loadChats = useCallback(
    async (revalidate = false) => {
      if (!token || activeKeyId === "all") return;
      await swrFetch<ChatItem[]>({
        key: scopedKey(CHAT_LIST_CACHE_KEY),
        url: "/api/chats?fast=1",
        ttl: CACHE_TTLS.chatList,
        revalidate,
        onLoading: setChatListLoading,
        onData: (items) => {
          const nextItems = applyAdminCallOverrides(items);
          setChats(nextItems);
          if ((selectedChat === null || selectedChat === undefined) && items.length) {
            setSelectedChat(items[0].id);
          }
        },
        map: mapChatItems,
      });
    },
    [token, activeKeyId, selectedChat, swrFetch, mapChatItems, scopedKey, applyAdminCallOverrides]
  );

  const loadChatHistory = useCallback(
    async (chatId: string | number | null, revalidate = false, force = false) => {
      if (!token || activeKeyId === "all" || chatId === null || chatId === undefined) return;
      const requestId = ++chatHistoryRequestRef.current;
      const chatKey = String(chatId);
      const cacheKey = scopedKey(`${CHAT_HISTORY_CACHE_PREFIX}${chatKey}`);
      const qs = new URLSearchParams();
      qs.set("limit", "80");
      qs.set("fast", "1");
      if (force) qs.set("refresh", "1");
      await swrFetch<ChatMessage[]>({
        key: cacheKey,
        url: `/api/chats/${encodeURIComponent(chatKey)}/history?${qs.toString()}`,
        ttl: CACHE_TTLS.chatHistory,
        revalidate,
        onLoading: (loading) => {
          if (chatHistoryRequestRef.current !== requestId) return;
          if (String(selectedChatRef.current ?? "") !== chatKey) return;
          setChatLoading(loading);
        },
        onData: (items) => {
          if (chatHistoryRequestRef.current !== requestId) return;
          if (String(selectedChatRef.current ?? "") !== chatKey) return;
          setChatMessages(items);
        },
        map: mapChatMessages,
      });
    },
    [token, activeKeyId, swrFetch, mapChatMessages, scopedKey]
  );

  const loadBlacklist = useCallback(
    async (query?: string, revalidate = false) => {
      if (!token) return;
      const trimmed = (query ?? "").trim();
      const cacheKey = scopedKey(`${CACHE_PREFIX}blacklist:${encodeURIComponent(trimmed || "all")}`);
      const url = trimmed ? `/api/blacklist?query=${encodeURIComponent(trimmed)}` : "/api/blacklist";
      await swrFetch<BlacklistEntry[]>({
        key: cacheKey,
        url,
        ttl: CACHE_TTLS.blacklist,
        revalidate,
        onLoading: setBlacklistLoading,
        onData: (items) => {
          setBlacklistEntries(items);
          setBlacklistSelected((prev) => prev.filter((owner) => items.some((entry) => entry.owner === owner)));
        },
        map: (data) =>
          (data.items || [])
            .map((item: any, idx: number) => ({
              id: item.id ?? idx,
              owner: String(item.owner ?? "").trim(),
              reason: item.reason ?? null,
              createdAt: item.created_at ?? item.createdAt ?? null,
            }))
            .filter((item: BlacklistEntry) => item.owner),
      });
    },
    [token, swrFetch, scopedKey]
  );

  const loadBlacklistLogs = useCallback(
    async (revalidate = false) => {
      if (!token || activeKeyId === "all") return;
      await swrFetch<BlacklistLog[]>({
        key: scopedKey(`${CACHE_PREFIX}blacklist_logs`),
        url: "/api/blacklist/logs?limit=200",
        ttl: 20, // keep fresh
        revalidate,
        onLoading: setBlacklistLogsLoading,
        onData: (items) => setBlacklistLogs(items),
        map: (data) =>
          (data.items || []).map((item: any) => ({
            owner: String(item.owner ?? "").trim(),
            action: String(item.action ?? "").trim(),
            reason: item.reason ?? null,
            details: item.details ?? null,
            created_at: item.created_at ?? item.createdAt ?? null,
          })),
      });
    },
    [token, activeKeyId, swrFetch, scopedKey]
  );

  const loadTicketHistory = useCallback(
    async (revalidate = false) => {
      if (!token) return;
      await swrFetch<any[]>({
        key: `${CACHE_PREFIX}ticket_history`,
        url: "/api/support/tickets/logs",
        ttl: 15,
        revalidate,
        onLoading: setTicketHistoryLoading,
        onData: (items) => setTicketHistory(items),
        map: (data) => data.items || [],
      });
    },
    [token, swrFetch]
  );

  useEffect(() => {
    if (authState !== "authed") return;
    loadNotifications();
    loadChats(false);
    return undefined;
  }, [authState, loadNotifications, loadChats]);

  useEffect(() => {
    if (authState === "guest") return;
    if (!(activeNav === "overview" || activeNav === "rentals" || activeNav === "inventory")) return;
    loadOverview("fast");
    if (authState !== "authed") return;
    if (hydrateTimeoutRef.current) {
      window.clearTimeout(hydrateTimeoutRef.current);
      hydrateTimeoutRef.current = null;
    }
    hydrateTimeoutRef.current = window.setTimeout(() => {
      loadOverview("full");
    }, 700);
    return () => {
      if (hydrateTimeoutRef.current) {
        window.clearTimeout(hydrateTimeoutRef.current);
        hydrateTimeoutRef.current = null;
      }
    };
  }, [authState, activeNav, loadOverview]);

  useEffect(() => {
    if (authState === "guest") return;
    if (!(activeNav === "overview" || activeNav === "rentals" || activeNav === "inventory")) return;
    const handle = window.setInterval(() => {
      loadOverview("fast");
    }, 30_000);
    return () => window.clearInterval(handle);
  }, [authState, activeNav, loadOverview]);

  useEffect(() => {
    if (!token || activeKeyId === "all") return;
    // keep blacklist data reasonably fresh for nav badge; revalidate when tab is active
    loadBlacklist(blacklistQuery, activeNav === "blacklist");
    loadBlacklistLogs(activeNav === "blacklist");
    if (activeNav === "tickets") {
      loadTicketHistory(true);
    }
  }, [token, sessionKey, activeKeyId, activeNav, blacklistQuery, loadBlacklist, loadBlacklistLogs, loadTicketHistory]);

    useEffect(() => {
      if (!token || !(activeNav === "overview" || activeNav === "rentals")) return;
      if (!rentalsTable.length) return;
      const anyPresence = rentalsTable.some((item) => item.presence);
      if (!anyPresence) return;
    const allOffline = rentalsTable.every((item) => {
      const presence = item.presence;
      return !presence || (!presence.in_game && !presence.in_match);
    });
    if (!allOffline) return;
    const nowTs = Date.now();
    if (nowTs - presenceWarmupRef.current < 8000) return;
      presenceWarmupRef.current = nowTs;
      const handle = window.setTimeout(() => {
        loadOverview();
      }, 2000);
      return () => window.clearTimeout(handle);
    }, [token, activeNav, rentalsTable, loadOverview]);

    // Refresh presence (match time, hero) directly from NodeBridge to keep timers accurate
    useEffect(() => {
      if (!token || !(activeNav === "overview" || activeNav === "rentals")) return;
      const now = Date.now();
      const targets = Array.from(
        new Set(
          rentalsTable
            .map((r) => (r.steamId ? String(r.steamId).trim() : ""))
            .filter(Boolean)
        )
      ).filter((steamId) => {
        const cached = presenceCacheRef.current.get(steamId);
        return !cached || now - cached.fetchedAt > 15_000;
      });
      if (!targets.length) return;

      let cancelled = false;

      const fetchPresence = async (steamId: string) => {
        try {
          const res = await fetch(`${PRESENCE_BASE}/${steamId}`);
          if (!res.ok) return;
          const data = await res.json();
          const payload: PresenceData = {
            in_game: !!data.in_game,
            in_match: !!data.in_match,
            hero_name: data.hero_name ?? data.hero ?? null,
            hero_token: data.hero_token ?? null,
            hero_level: data.hero_level ?? null,
            lobby_info: data.lobby_info ?? null,
            match_time: data.match_time ?? null,
            match_seconds: Number.isFinite(Number(data.match_seconds))
              ? Number(data.match_seconds)
              : data.match_seconds ?? null,
          };
          const fetchedAt = Date.now();
          presenceCacheRef.current.set(steamId, { data: payload, fetchedAt });
          if (cancelled) return;
          const presenceLabel = payload.in_match ? "In match" : payload.in_game ? "In game" : "Offline";
          setRentalsTable((prev) =>
            prev.map((r) =>
              String(r.steamId || "") === steamId
                ? {
                    ...r,
                    presence: payload,
                    presenceLabel,
                    presenceObservedAt: fetchedAt,
                    hero: r.hero || payload.hero_name || r.hero,
                  }
                : r
            )
          );
        } catch {
          // ignore fetch errors
        }
      };

      const CONCURRENCY = 4;
      let index = 0;
      const runNext = () => {
        if (cancelled) return;
        const sid = targets[index++];
        if (!sid) return;
        fetchPresence(sid).finally(runNext);
      };
      const starters = Math.min(CONCURRENCY, targets.length);
      for (let i = 0; i < starters; i += 1) {
        runNext();
      }

      return () => {
        cancelled = true;
      };
    }, [token, activeNav, rentalsTable]);

  // load chat list when on chats tab
  useEffect(() => {
    if (!token || activeNav !== "chats" || activeKeyId === "all") return;
    loadChats(true);
  }, [token, sessionKey, activeNav, activeKeyId, loadChats]);

  // load chat history when selection changes
  useEffect(() => {
    if (!token || activeNav !== "chats" || activeKeyId === "all") return;
    if (selectedChat === null || selectedChat === undefined) {
      setChatMessages([]);
      setChatLoading(false);
      return;
    }
    selectedChatRef.current = selectedChat;
    const cacheKey = scopedKey(`${CHAT_HISTORY_CACHE_PREFIX}${selectedChat}`);
    const cached = readCache<ChatMessage[]>(cacheKey, CACHE_TTLS.chatHistory);
    if (cached?.data) {
      setChatMessages(cached.data);
      setChatLoading(false);
    } else {
      setChatMessages([]);
      setChatLoading(true);
    }
    loadChatHistory(selectedChat, true, true);
  }, [token, sessionKey, activeNav, activeKeyId, selectedChat, loadChatHistory, scopedKey]);

  useEffect(() => {
    if (!token || activeNav !== "chats" || activeKeyId === "all") {
      if (chatWsRef.current) {
        chatWsRef.current.close();
        chatWsRef.current = null;
      }
      if (chatWsHeartbeatRef.current) {
        window.clearInterval(chatWsHeartbeatRef.current);
        chatWsHeartbeatRef.current = null;
      }
      chatWsSubscribedRef.current = null;
      setChatWsConnected(false);
      return;
    }
    if (chatWsRef.current) return;

    const ws = connectChatWS(
      {
      onOpen: () => {
        setChatWsConnected(true);
        if (chatWsHeartbeatRef.current) {
          window.clearInterval(chatWsHeartbeatRef.current);
        }
        chatWsHeartbeatRef.current = window.setInterval(() => {
          sendChatWs({ type: "ping" });
        }, 15000);
        if (selectedChat !== null && selectedChat !== undefined) {
          const key = String(selectedChat);
          chatWsSubscribedRef.current = key;
          sendChatWs({ type: "subscribe", chat_id: selectedChat });
        }
      },
      onMessage: (event) => {
        try {
          const payload = JSON.parse(event.data || "{}");
          const eventType = payload?.type;
          if (eventType === "chats:list") {
            const items = mapChatItems(payload);
            const nextItems = applyAdminCallOverrides(items);
            setChats(nextItems);
            writeCache(scopedKey(CHAT_LIST_CACHE_KEY), nextItems);
            if ((selectedChat === null || selectedChat === undefined) && items.length) {
              setSelectedChat(items[0].id);
            }
            const nowTs = Date.now();
            const prevCounts = adminCallCountsRef.current;
            const nextCounts: Record<string, number> = {};
            nextItems.forEach((chat) => {
              const key = String(chat.id ?? "");
              const count = Number(chat.adminCalls || 0);
              nextCounts[key] = count;
              const prev = prevCounts[key] || 0;
              if (count > prev && activeNav !== "chats") {
                const lastToastAt = adminCallToastRef.current || 0;
                if (nowTs - lastToastAt > 1500) {
                  adminCallToastRef.current = nowTs;
                  showToast(`Admin call: ${chat.name || "Buyer"}`, "error");
                  playAdminCallSound();
                }
              }
            });
            adminCallCountsRef.current = nextCounts;
          } else if (eventType === "chats:update") {
            const mapped = mapChatItems({ items: payload.item ? [payload.item] : [] });
            const nextItems = applyAdminCallOverrides(mapped);
            if (nextItems.length) {
              const next = nextItems[0];
              setChats((prev) => {
                const updated = prev.map((chat) =>
                  String(chat.id) === String(next.id) ? { ...chat, ...next } : chat
                );
                writeCache(scopedKey(CHAT_LIST_CACHE_KEY), updated);
                return updated;
              });
            }
          } else if (eventType === "chat:history") {
            const chatId = payload.chat_id;
            if (String(selectedChatRef.current ?? "") !== String(chatId)) {
              return;
            }
            const items = mapChatMessages({ items: payload.items || [] });
            setChatMessages(items);
            writeCache(scopedKey(`${CHAT_HISTORY_CACHE_PREFIX}${chatId}`), items);
          } else if (eventType === "chat:message") {
            const chatId = payload.chat_id;
            if (chatId === null || chatId === undefined) return;
            const mapped = mapChatMessages({ items: payload.item ? [payload.item] : [] });
            const next = mapped[0];
            if (!next) return;
            if (String(selectedChatRef.current ?? "") === String(chatId)) {
              appendChatMessage(chatId, next);
            }
            updateChatPreview(chatId, next);
          }
        } catch {
          // ignore ws parse errors
        }
      },
      onClose: () => {
        setChatWsConnected(false);
        if (chatWsHeartbeatRef.current) {
          window.clearInterval(chatWsHeartbeatRef.current);
          chatWsHeartbeatRef.current = null;
        }
        chatWsSubscribedRef.current = null;
        chatWsRef.current = null;
      },
      onError: () => {
        setChatWsConnected(false);
      },
    },
      activeKeyId
    );

    chatWsRef.current = ws;
    return () => {
      ws.close();
    };
  }, [
    token,
    activeNav,
    activeKeyId,
    selectedChat,
    mapChatItems,
    mapChatMessages,
    applyAdminCallOverrides,
    appendChatMessage,
    updateChatPreview,
    scopedKey,
    sendChatWs,
    showToast,
  ]);

  useEffect(() => {
    if (!chatWsConnected) return;
    const current = selectedChat !== null && selectedChat !== undefined ? String(selectedChat) : null;
    const previous = chatWsSubscribedRef.current;
    if (previous && previous !== current) {
      sendChatWs({ type: "unsubscribe", chat_id: previous });
    }
    if (current && previous !== current) {
      sendChatWs({ type: "subscribe", chat_id: current });
      chatWsSubscribedRef.current = current;
    }
  }, [chatWsConnected, selectedChat, sendChatWs]);

  useEffect(() => {
    if (chatWsConnected && activeNav === "chats") {
      setChatStreamActive(false);
      return;
    }
    if (!token || activeKeyId === "all") {
      if (chatListStreamRef.current) {
        chatListStreamRef.current.close();
        chatListStreamRef.current = null;
      }
      setChatStreamActive(false);
      return;
    }
    if (typeof EventSource === "undefined") {
      setChatStreamActive(false);
      return;
    }

    let source: EventSource;
    try {
      const streamUrl =
        activeKeyId === "all" ? "/api/stream/chats" : `/api/stream/chats?key_id=${encodeURIComponent(String(activeKeyId))}`;
      source = new EventSource(streamUrl);
    } catch {
      setChatStreamActive(false);
      return;
    }
    if (chatListStreamRef.current) {
      chatListStreamRef.current.close();
    }
    chatListStreamRef.current = source;

    const handleChats = (event: MessageEvent) => {
      try {
        const payload = JSON.parse(event.data || "{}");
        const items = mapChatItems(payload);
        const nextItems = applyAdminCallOverrides(items);
        setChats(nextItems);
        writeCache(scopedKey(CHAT_LIST_CACHE_KEY), nextItems);
        if (items.length) {
          setSelectedChat((prev) => (prev === null || prev === undefined ? items[0].id : prev));
        }

        const nowTs = Date.now();
        const prevCounts = adminCallCountsRef.current;
        const nextCounts: Record<string, number> = {};
        nextItems.forEach((chat) => {
          const key = String(chat.id ?? "");
          const count = Number(chat.adminCalls || 0);
          nextCounts[key] = count;
          const prev = prevCounts[key] || 0;
          if (count > prev && activeNav !== "chats") {
            const lastToastAt = adminCallToastRef.current || 0;
            if (nowTs - lastToastAt > 1500) {
              adminCallToastRef.current = nowTs;
              showToast(`Admin call: ${chat.name || "Buyer"}`, "error");
              playAdminCallSound();
            }
          }
        });
        adminCallCountsRef.current = nextCounts;
        setChatStreamActive(true);
      } catch {
        // ignore stream parse errors
      }
    };

    source.addEventListener("chats", handleChats as EventListener);
    source.onopen = () => setChatStreamActive(true);
    source.onerror = () => {
      setChatStreamActive(false);
      source.close();
      if (chatListStreamRef.current === source) {
        chatListStreamRef.current = null;
      }
    };

    return () => {
      source.removeEventListener("chats", handleChats as EventListener);
      source.close();
      if (chatListStreamRef.current === source) {
        chatListStreamRef.current = null;
      }
      setChatStreamActive(false);
    };
  }, [
    token,
    sessionKey,
    activeNav,
    activeKeyId,
    mapChatItems,
    scopedKey,
    showToast,
    applyAdminCallOverrides,
    chatWsConnected,
  ]);

  useEffect(() => {
    if (chatWsConnected && activeNav === "chats") {
      if (chatHistoryStreamRef.current) {
        chatHistoryStreamRef.current.close();
        chatHistoryStreamRef.current = null;
      }
      return;
    }
    if (!token || activeNav !== "chats" || !selectedChat || activeKeyId === "all") {
      if (chatHistoryStreamRef.current) {
        chatHistoryStreamRef.current.close();
        chatHistoryStreamRef.current = null;
      }
      return;
    }
    if (typeof EventSource === "undefined") {
      return;
    }

    let source: EventSource;
    try {
      const streamUrl = `/api/stream/chats/${selectedChat}/history?key_id=${encodeURIComponent(
        String(activeKeyId)
      )}`;
      source = new EventSource(streamUrl);
    } catch {
      return;
    }
    if (chatHistoryStreamRef.current) {
      chatHistoryStreamRef.current.close();
    }
    chatHistoryStreamRef.current = source;
    const streamChatId = String(selectedChat);

    const handleHistory = (event: MessageEvent) => {
      try {
        const payload = JSON.parse(event.data || "{}");
        if (String(selectedChatRef.current ?? "") !== streamChatId) {
          return;
        }
        const items = mapChatMessages(payload);
        setChatMessages(items);
        writeCache(scopedKey(`${CHAT_HISTORY_CACHE_PREFIX}${streamChatId}`), items);
      } catch {
        // ignore stream parse errors
      }
    };

    source.addEventListener("history", handleHistory as EventListener);
    source.onerror = () => {
      source.close();
      if (chatHistoryStreamRef.current === source) {
        chatHistoryStreamRef.current = null;
      }
    };

    return () => {
      source.removeEventListener("history", handleHistory as EventListener);
      source.close();
      if (chatHistoryStreamRef.current === source) {
        chatHistoryStreamRef.current = null;
      }
    };
  }, [token, sessionKey, activeNav, activeKeyId, selectedChat, mapChatMessages, scopedKey, chatWsConnected]);

  useEffect(() => {
    if (activeNav !== "chats") return;
    if (!chatScrollRef.current) return;
    const handle = window.requestAnimationFrame(() => {
      const el = chatScrollRef.current;
      if (!el) return;
      el.scrollTop = el.scrollHeight;
    });
    return () => window.cancelAnimationFrame(handle);
  }, [activeNav, selectedChat, chatMessages]);

  useEffect(() => {
    if (!token || activeNav !== "chats" || activeKeyId === "all" || selectedChat === null || selectedChat === undefined)
      return;
    clearAdminCall(selectedChat);
  }, [token, activeNav, activeKeyId, selectedChat, clearAdminCall]);

  useEffect(() => {
    if (!token || activeNav !== "blacklist") return;
    const handle = setTimeout(() => {
      loadBlacklist(blacklistQuery, true);
    }, 250);
    return () => clearTimeout(handle);
  }, [token, sessionKey, activeNav, blacklistQuery, loadBlacklist]);

  useEffect(() => {
    if (!token || activeNav !== "funpay-stats" || activeKeyId === "all") return;
    loadFunpayStats(false, true);
  }, [token, sessionKey, activeNav, activeKeyId, loadFunpayStats]);

  useEffect(() => {
    if (!token || activeNav !== "lots") return;
    loadLots(true);
  }, [token, sessionKey, activeNav, loadLots]);

  useEffect(() => {
    if (!token || activeNav !== "orders") return;
    const handle = setTimeout(() => {
      loadOrdersHistory(ordersQuery.trim(), true);
    }, 250);
    return () => clearTimeout(handle);
  }, [token, sessionKey, activeNav, ordersQuery, loadOrdersHistory]);

  const revalidateActive = useCallback(() => {
    if (!token) return;
    if (activeNav === "overview" || activeNav === "rentals") {
      loadOverview();
      return;
    }
    if (activeNav === "funpay-stats") {
      if (activeKeyId !== "all") {
        loadFunpayStats(false, true);
      }
      return;
    }
    if (activeNav === "lots") {
      loadLots(true);
      return;
    }
    if (activeNav === "chats") {
      if (!chatWsConnected) {
        loadChats(true);
        loadChatHistory(selectedChat, true);
      }
      return;
    }
    if (activeNav === "orders") {
      loadOrdersHistory(ordersQuery.trim(), true);
    }
    if (activeNav === "tickets") {
      return;
    }
  }, [
    token,
    activeNav,
    selectedChat,
    ordersQuery,
    loadFunpayStats,
    loadChats,
    loadChatHistory,
    loadOrdersHistory,
    chatWsConnected,
    loadLots,
  ]);

  useEffect(() => {
    if (!token) return;
    const handleVisibility = () => {
      if (document.visibilityState === "visible") {
        revalidateActive();
      }
    };
    const handleOnline = () => revalidateActive();
    document.addEventListener("visibilitychange", handleVisibility);
    window.addEventListener("online", handleOnline);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibility);
      window.removeEventListener("online", handleOnline);
    };
  }, [token, sessionKey, revalidateActive]);

  useEffect(() => {
    if (!token) return;
    let intervalId: number | undefined;
    if (activeNav === "overview" || activeNav === "rentals") {
      intervalId = window.setInterval(() => {
        loadOverview();
      }, 20000);
    } else if (activeNav === "chats" && !chatStreamActive && !chatWsConnected) {
      intervalId = window.setInterval(() => {
        loadChats(true);
        loadChatHistory(selectedChat, true);
      }, 15000);
    } else if (activeNav === "orders") {
      intervalId = window.setInterval(() => {
        loadOrdersHistory(ordersQuery.trim(), true);
      }, 60000);
    } else if (activeNav === "lots") {
      intervalId = window.setInterval(() => {
        loadLots(true);
      }, 60000);
    } else if (activeNav === "funpay-stats") {
      intervalId = window.setInterval(() => {
        if (activeKeyId !== "all") {
          loadFunpayStats(false, true);
        }
      }, 120000);
    }
    return () => {
      if (intervalId) window.clearInterval(intervalId);
    };
  }, [
    token,
    sessionKey,
    activeNav,
    selectedChat,
    ordersQuery,
    chatStreamActive,
    chatWsConnected,
    loadChats,
    loadChatHistory,
    loadOrdersHistory,
    loadLots,
    loadFunpayStats,
    activeKeyId,
  ]);

  useEffect(() => {
    localStorage.setItem("autoOnline", autoOnline ? "1" : "0");
  }, [autoOnline]);

  useEffect(() => {
    if (!token) return;
    (async () => {
      setCategoryLoading(true);
      try {
        const res = await apiFetch<{ enabled: boolean; categories?: number[] }>("/api/settings/auto-raise/config");
        setAutoRaise(res.enabled);
        if (res.categories && Array.isArray(res.categories)) {
          setAutoRaiseCategories(res.categories.join(","));
        }
      } catch {
        setAutoRaise(true);
      }
      try {
        const res2 = await apiFetch<{ enabled: boolean }>("/api/settings/auto-ticket");
        setAutoTickets(!!res2.enabled);
      } catch {
        setAutoTickets(true);
      }
      try {
        const resCats = await apiFetch<{ items: CategoryOption[] }>("/api/funpay/categories");
        setCategoryOptions(resCats.items || []);
        setCategoryMeta({ ts: Date.now(), count: resCats.items?.length || 0 });
      } catch {
        setCategoryOptions([]);
      } finally {
        setCategoryLoading(false);
      }
    })();
  }, [token, apiFetch]);

  const reloadCategories = useCallback(async () => {
    if (!token) return;
    setCategoryLoading(true);
    try {
        const resCats = await apiFetch<{ items: CategoryOption[] }>("/api/funpay/categories");
        setCategoryOptions(resCats.items || []);
        setCategoryMeta({ ts: Date.now(), count: resCats.items?.length || 0 });
    } catch (error) {
        setCategoryOptions([]);
        showToast((error as Error).message || "Failed to load categories.", "error");
    } finally {
        setCategoryLoading(false);
    }
  }, [apiFetch, token, showToast]);

  useEffect(() => {
    if (!token) return;
    (async () => {
      try {
        const res = await apiFetch<{ enabled: boolean }>("/api/settings/auto-ticket");
        setAutoTickets(!!res.enabled);
      } catch {
        setAutoTickets(true);
      }
    })();
  }, [token, apiFetch]);

  useEffect(() => {
    localStorage.setItem("uiMode", uiMode);
  }, [uiMode]);

  // tick for live timers
  useEffect(() => {
    if (!token) return;
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, [token]);

  const parseDateTime = (value?: string | number | null) => {
    if (value === null || value === undefined) return null;
    const reference = Number.isFinite(now) ? (now as number) : Date.now();
    if (typeof value === "number") {
      if (!Number.isFinite(value)) return null;
      const ms = value < 1e12 ? value * 1000 : value;
      return ms;
    }
    const raw = String(value).trim();
    if (!raw) return null;
    if (/^\d+$/.test(raw)) {
      const numeric = Number(raw);
      if (!Number.isFinite(numeric)) return null;
      const ms = numeric < 1e12 ? numeric * 1000 : numeric;
      return ms;
    }
    let normalized = raw.includes(" ") ? raw.replace(" ", "T") : raw;
    normalized = normalized.replace(/\.(\d{3})\d+/, ".$1");
    const hasTimezone = /[zZ]|[+\-]\d{2}:?\d{2}$/.test(normalized);
    const parsedLocal = new Date(normalized);
    const localMs = Number.isNaN(parsedLocal.getTime()) ? null : parsedLocal.getTime();
    if (hasTimezone) return localMs;
    const parsedMoscow = new Date(`${normalized}+03:00`);
    const moscowMs = Number.isNaN(parsedMoscow.getTime()) ? null : parsedMoscow.getTime();
    if (localMs === null && moscowMs === null) return null;
    if (localMs === null) return moscowMs;
    if (moscowMs === null) return localMs;
    const threshold = 5 * 60 * 1000;
    const localSkew = localMs - reference;
    const moscowSkew = moscowMs - reference;
    if (localSkew > threshold && moscowSkew <= threshold) return moscowMs;
    if (moscowSkew > threshold && localSkew <= threshold) return localMs;
    return Math.abs(moscowSkew) < Math.abs(localSkew) ? moscowMs : localMs;
  };

  const formatDuration = (
    seconds: number | null | undefined,
    startedAt?: string | number | null,
    nowMs?: number,
    freezeAt?: string | number | null
  ) => {
    let remaining = seconds ?? 0;
    if (startedAt !== null && startedAt !== undefined && seconds != null) {
      const startedAtMs = parseDateTime(startedAt);
      const currentMs = Number.isFinite(nowMs) ? (nowMs as number) : Date.now();
      const freezeMs = freezeAt !== undefined && freezeAt !== null ? parseDateTime(freezeAt) : null;
      const effectiveNow =
        freezeMs && Number.isFinite(freezeMs) && freezeMs < currentMs ? freezeMs : currentMs;
      const elapsed = startedAtMs ? Math.max(0, Math.floor((effectiveNow - startedAtMs) / 1000)) : 0;
      remaining = Math.max(0, seconds - elapsed);
    }
    const h = Math.floor(remaining / 3600)
      .toString()
      .padStart(2, "0");
    const m = Math.floor((remaining % 3600) / 60)
      .toString()
      .padStart(2, "0");
    const s = Math.floor(remaining % 60)
      .toString()
      .padStart(2, "0");
    return `${h}:${m}:${s}`;
  };

  const parseMatchTimeSeconds = (value?: string | null) => {
    if (!value) return null;
    const parts = String(value)
      .trim()
      .split(":")
      .map((part) => Number(part));
    if (parts.some((part) => !Number.isFinite(part))) return null;
    if (parts.length === 2) {
      const [minutes, seconds] = parts;
      if (minutes < 0 || seconds < 0 || seconds >= 60) return null;
      return Math.floor(minutes * 60 + seconds);
    }
    if (parts.length === 3) {
      const [hours, minutes, seconds] = parts;
      if (hours < 0 || minutes < 0 || minutes >= 60 || seconds < 0 || seconds >= 60) return null;
      return Math.floor(hours * 3600 + minutes * 60 + seconds);
    }
    return null;
  };

  const formatMatchTimeSeconds = (seconds?: number | null) => {
    if (!Number.isFinite(seconds)) return null;
    const total = Math.max(0, Math.floor(seconds || 0));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const secs = total % 60;
    if (hours) {
      return `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
    }
    return `${minutes}:${String(secs).padStart(2, "0")}`;
  };

  // Use only NodeBridge-reported time, no client-side ticking
  const getMatchSecondsFromPresence = (presence?: PresenceData | null) => {
    if (!presence || !presence.in_match) return null;
    const rawSeconds = Number(presence.match_seconds);
    if (Number.isFinite(rawSeconds)) return Math.max(0, Math.floor(rawSeconds));
    return parseMatchTimeSeconds(presence.match_time ?? null);
  };

  const getMatchTimeLabel = (presence?: PresenceData | null) => {
    if (!presence || !presence.in_match) return "-";
    const seconds = getMatchSecondsFromPresence(presence);
    if (seconds !== null) {
      const formatted = formatMatchTimeSeconds(seconds);
      if (formatted) return formatted;
    }
    return presence.match_time ? String(presence.match_time) : "-";
  };

  const formatStartTime = (value?: string | number | null) => {
    if (value === null || value === undefined || value === "") return "";
    const ts = parseDateTime(value);
    if (!ts) return String(value);
    return new Date(ts).toLocaleTimeString();
  };

  const formatMoscowDateTime = (value?: string | number | null) => {
    if (value === null || value === undefined || value === "") return "-";
    const ts = parseDateTime(value);
    if (!ts) return String(value);
    return new Date(ts).toLocaleString("ru-RU", { timeZone: "Europe/Moscow" });
  };

  const statusPill = (status?: string | boolean) => {
    if (typeof status === "boolean") {
      return status
        ? { className: "bg-emerald-50 text-emerald-600", label: "Online" }
        : { className: "bg-rose-50 text-rose-600", label: "Offline" };
    }
    const lower = (status || "").toLowerCase();
    if (lower.includes("frozen")) return { className: "bg-slate-100 text-slate-700", label: "Frozen" };
    if (lower.includes("match")) return { className: "bg-emerald-50 text-emerald-600", label: "In match" };
    if (lower.includes("game")) return { className: "bg-amber-50 text-amber-600", label: "In game" };
    if (lower.includes("online") || lower === "1" || lower === "true") return { className: "bg-emerald-50 text-emerald-600", label: "Online" };
    if (lower.includes("idle") || lower.includes("away")) return { className: "bg-amber-50 text-amber-600", label: "Idle" };
    if (lower.includes("off") || lower === "" || lower === "0") return { className: "bg-rose-50 text-rose-600", label: "Offline" };
    return { className: "bg-neutral-100 text-neutral-600", label: status || "Unknown" };
  };

  const formatMinutesLabel = (minutes?: number | null) => {
    const numeric = typeof minutes === "number" ? minutes : Number(minutes);
    if (!Number.isFinite(numeric)) return "-";
    const total = Math.max(0, Math.round(numeric));
    const hours = Math.floor(total / 60);
    const mins = total % 60;
    if (hours && mins) return `${hours}h ${mins}m`;
    if (hours) return `${hours}h`;
    return `${mins}m`;
  };

  const orderActionPill = (action?: string | null) => {
    const lower = (action || "").toLowerCase();
    if (lower.includes("issued")) return { className: "bg-emerald-50 text-emerald-600", label: "Issued" };
    if (lower.includes("extend")) return { className: "bg-sky-50 text-sky-600", label: "Extended" };
    if (lower.includes("paid")) return { className: "bg-emerald-50 text-emerald-600", label: "Issued" };
    if (lower.includes("refund")) return { className: "bg-rose-50 text-rose-600", label: "Refunded" };
    if (lower.includes("closed")) return { className: "bg-neutral-200 text-neutral-700", label: "Closed" };
    if (lower.includes("blacklist")) return { className: "bg-neutral-200 text-neutral-700", label: "Blacklisted" };
    if (!lower) return { className: "bg-neutral-100 text-neutral-600", label: "-" };
    return { className: "bg-neutral-100 text-neutral-700", label: action || "-" };
  };

  const rangeOptions: Array<{ id: "daily" | "weekly" | "monthly"; label: string }> = [
    { id: "daily", label: "Daily" },
    { id: "weekly", label: "Weekly" },
    { id: "monthly", label: "Monthly" },
  ];

  const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

  const toLinePath = (values: number[]) => {
    if (!values.length) return "";
    const max = Math.max(...values);
    const min = Math.min(...values);
    const range = Math.max(1, max - min);
    const step = values.length > 1 ? 100 / (values.length - 1) : 100;
    return values
      .map((value, idx) => {
        const x = idx * step;
        const y = 100 - ((value - min) / range) * 100;
        return `${idx === 0 ? "M" : "L"} ${x} ${y}`;
      })
      .join(" ");
  };

  const toAreaPath = (values: number[]) => {
    const line = toLinePath(values);
    if (!line) return "";
    return `${line} L 100 100 L 0 100 Z`;
  };

  const Sparkline: React.FC<{ values: number[]; colorClass: string }> = ({ values, colorClass }) => {
    const line = toLinePath(values);
    const area = toAreaPath(values);
    return (
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" className={`h-full w-full ${colorClass}`}>
        <path d={area} fill="currentColor" opacity="0.12" />
        <path d={line} fill="none" stroke="currentColor" strokeWidth="2" />
      </svg>
    );
  };

  const BarChart: React.FC<{ values: number[]; barClass: string }> = ({ values, barClass }) => {
    const max = Math.max(1, ...values);
    return (
      <div className="flex h-28 items-end gap-1">
        {values.map((value, idx) => (
          <div
            key={`${idx}-${value}`}
            className={`flex-1 rounded-sm ${barClass}`}
            style={{ height: `${(value / max) * 100}%` }}
          />
        ))}
      </div>
    );
  };

  const balanceSeries = funpayStats.balance_series ?? [];
  const reviewSeriesByRange = useMemo(
    () => ({
      daily: funpayStats.reviews?.daily ?? [],
      weekly: funpayStats.reviews?.weekly ?? [],
      monthly: funpayStats.reviews?.monthly ?? [],
    }),
    [funpayStats.reviews]
  );
  const orderSeriesByRange = useMemo(
    () => ({
      daily: funpayStats.orders?.daily ?? [],
      weekly: funpayStats.orders?.weekly ?? [],
      monthly: funpayStats.orders?.monthly ?? [],
    }),
    [funpayStats.orders]
  );

  const reviewSeries = reviewSeriesByRange[reviewRange] ?? [];
  const orderSeries = orderSeriesByRange[orderRange] ?? [];
  const balanceCurrent =
    funpayStats.balance?.total_rub ??
    balanceSeries[balanceSeries.length - 1] ??
    0;
  const balanceStart = balanceSeries[0] ?? balanceCurrent;
  const balanceDelta = balanceCurrent - balanceStart;
  const balanceDeltaPct = balanceStart ? Math.round((balanceDelta / balanceStart) * 100) : 0;
  const totalReviews = reviewSeries.reduce((sum, value) => sum + value, 0);
  const totalOrders = orderSeries.reduce((sum, value) => sum + value, 0);

  const accountUsage = useMemo(() => {
    if (!accountsTable.length) return [];
    const rows = accountsTable.map((acc, idx) => {
      const label = acc.name || acc.login || `ID ${acc.id ?? idx}`;
      const count = isAccountRented(acc) ? 1 : 0;
      return { label, count };
    });
    return rows.sort((a, b) => b.count - a.count).slice(0, 6);
  }, [accountsTable, rentalsTable]);

  const averageRentalMinutes = useMemo(() => {
    if (overview.totalHours && overview.activeRentals) {
      return Math.round((overview.totalHours / overview.activeRentals) * 60);
    }
    const durations = rentalsTable
      .map((r) => (typeof r.durationSec === "number" ? r.durationSec : null))
      .filter((value): value is number => value !== null && Number.isFinite(value) && value > 0);
    if (!durations.length) return null;
    const avgSeconds = Math.round(durations.reduce((sum, value) => sum + value, 0) / durations.length);
    return Math.round(avgSeconds / 60);
  }, [overview.totalHours, overview.activeRentals, rentalsTable]);

  const averageRentalLabel =
    averageRentalMinutes === null
      ? "-"
      : `${Math.floor(averageRentalMinutes / 60)}h ${averageRentalMinutes % 60}m`;

  const averageRentalProgress = averageRentalMinutes
    ? clamp(averageRentalMinutes / (12 * 60), 0, 1)
    : 0;

  const renderAccountActionsPanel = (title = "Rental controls") => {
    return (
      <div className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm shadow-neutral-200/70">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-semibold text-neutral-900">{title}</h3>
          <span className="text-xs text-neutral-500">{selectedAccount ? "Ready" : "Select an account"}</span>
        </div>
        {selectedAccount ? (
          (() => {
            const rented = isAccountRented(selectedAccount);
            const frozen = !!selectedAccount.accountFrozen;
            const stateLabel = frozen ? "Frozen" : rented ? "Rented out" : "Available";
            const stateClass = frozen
              ? "bg-slate-100 text-slate-700"
              : rented
                ? "bg-amber-50 text-amber-700"
                : "bg-emerald-50 text-emerald-600";
            const ownerRaw = selectedAccount.owner ? String(selectedAccount.owner).trim() : "";
            const ownerKey = normalizeKey(ownerRaw);
            const ownerLabel =
              ownerKey && ownerKey !== "other_account" ? ownerRaw : ownerKey === "other_account" ? "Reserved" : "-";
            const startMs = parseDateTime(selectedAccount.rentalStart);
            const startLabel = startMs ? new Date(startMs).toLocaleString() : "-";
            const totalMinutes =
              selectedAccount.rentalDurationMinutes ??
              (selectedAccount.rentalDurationHours ? selectedAccount.rentalDurationHours * 60 : null);
            const hoursLabel =
              typeof totalMinutes === "number" && totalMinutes >= 0
                ? `${Math.floor(totalMinutes / 60)}h ${totalMinutes % 60}m`
                : "-";
            const canAssign = !ownerKey && !frozen;
            const editName = accountEditName.trim();
            const editLogin = accountEditLogin.trim();
            const editPassword = accountEditPassword.trim();
            const editMmrRaw = accountEditMmr.trim();
            const editKeyRaw = accountEditKeyId.trim();
            const editMmrValue = editMmrRaw ? Number(editMmrRaw) : null;
            const editMmrValid = editMmrRaw === "" || (Number.isFinite(editMmrValue) && editMmrValue >= 0);
            const nameChanged = editName && editName !== (selectedAccount.name || "");
            const loginChanged = editLogin && editLogin !== (selectedAccount.login || "");
            const passwordChanged = editPassword && editPassword !== (selectedAccount.password || "");
            const mmrChanged =
              editMmrRaw &&
              Number.isFinite(editMmrValue) &&
              String(editMmrValue) !== String(selectedAccount.mmr ?? "");
            const currentKeyId =
              selectedAccount.keyId !== null && selectedAccount.keyId !== undefined
                ? String(selectedAccount.keyId)
                : "";
            const keyChanged = editKeyRaw !== currentKeyId;
            const hasChanges = nameChanged || loginChanged || passwordChanged || mmrChanged || keyChanged;
            return (
              <div className="space-y-4">
                <div className="rounded-xl border border-neutral-200 bg-neutral-50 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
                        Selected account
                      </div>
                      <div className="mt-1 text-sm font-semibold text-neutral-900">
                        {selectedAccount.name || "Account"}
                      </div>
                    </div>
                    <span className={`rounded-full px-3 py-1 text-xs font-semibold ${stateClass}`}>{stateLabel}</span>
                  </div>
                  <div className="mt-3 grid gap-1 text-xs text-neutral-600">
                    <span>Login: {selectedAccount.login || "-"}</span>
                    <span>Steam ID: {selectedAccount.steamId || "-"}</span>
                    <span>Owner: {ownerLabel}</span>
                    <span>Workspace: {resolveKeyLabel(selectedAccount.keyId)}</span>
                    <span>Rental start: {startLabel}</span>
                    <span>Duration: {hoursLabel}</span>
                  </div>
                </div>
                <div className="rounded-xl border border-neutral-200 bg-neutral-50 p-4">
                  <div className="mb-2 text-sm font-semibold text-neutral-800">Assign rental</div>
                  <p className="text-xs text-neutral-500">The countdown starts after the buyer requests the code.</p>
                  <div className="mt-3 space-y-3">
                    <input
                      value={assignOwner}
                      onChange={(e) => setAssignOwner(e.target.value)}
                      placeholder="Buyer username"
                      className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 outline-none placeholder:text-neutral-400"
                    />
                    <button
                      onClick={handleAssignAccount}
                      disabled={accountActionBusy || !assignOwner.trim() || !canAssign}
                      className="w-full rounded-lg bg-neutral-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-neutral-800 disabled:cursor-not-allowed disabled:bg-neutral-300"
                    >
                      Assign rental
                    </button>
                    {!canAssign && (
                      <div className="text-xs text-neutral-500">
                        {frozen ? "Unfreeze the account before assigning a buyer." : "Release the account first."}
                      </div>
                    )}
                  </div>
                </div>
                <div className="rounded-xl border border-neutral-200 bg-neutral-50 p-4">
                  <div className="mb-2 text-sm font-semibold text-neutral-800">Update account</div>
                  <div className="grid gap-3">
                    <input
                      value={accountEditName}
                      onChange={(e) => setAccountEditName(e.target.value)}
                      placeholder="Account name"
                      className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 outline-none placeholder:text-neutral-400"
                    />
                    <div className="grid gap-3 md:grid-cols-2">
                      <input
                        value={accountEditLogin}
                        onChange={(e) => setAccountEditLogin(e.target.value)}
                        placeholder="Login"
                        className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 outline-none placeholder:text-neutral-400"
                      />
                      <input
                        value={accountEditPassword}
                        onChange={(e) => setAccountEditPassword(e.target.value)}
                        placeholder="Password"
                        className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 outline-none placeholder:text-neutral-400"
                      />
                    </div>
                    {userKeys.length > 0 && (
                      <div className="space-y-1">
                        <label className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
                          Workspace
                        </label>
                        <select
                          value={accountEditKeyId}
                          onChange={(e) => setAccountEditKeyId(e.target.value)}
                          className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 outline-none"
                        >
                          <option value="">
                            Default workspace ({defaultKeyLabel})
                          </option>
                          {userKeys.map((item) => (
                            <option key={item.id} value={item.id}>
                              {item.label || `Workspace ${item.id}`}
                            </option>
                          ))}
                        </select>
                      </div>
                    )}
                    <input
                      value={accountEditMmr}
                      onChange={(e) => setAccountEditMmr(e.target.value)}
                      placeholder="MMR"
                      type="number"
                      min="0"
                      className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 outline-none placeholder:text-neutral-400"
                    />
                  </div>
                  {!editMmrValid && (
                    <div className="mt-2 text-xs text-rose-500">MMR must be 0 or higher.</div>
                  )}
                  <button
                    onClick={handleUpdateAccount}
                    disabled={accountActionBusy || !hasChanges || !editMmrValid}
                    className="mt-3 w-full rounded-lg bg-neutral-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-neutral-800 disabled:cursor-not-allowed disabled:bg-neutral-300"
                  >
                    Save changes
                  </button>
                </div>
              </div>
            );
          })()
        ) : (
          <div className="rounded-xl border border-dashed border-neutral-200 bg-neutral-50 px-4 py-6 text-center text-sm text-neutral-500">
            Select an account to unlock account actions.
          </div>
        )}
      </div>
    );
  };

  const renderRentalActionsPanel = () => {
    return (
      <div className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm shadow-neutral-200/70">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-semibold text-neutral-900">Rental actions</h3>
          <span className="text-xs text-neutral-500">{selectedRental ? "Ready" : "Select a rental"}</span>
        </div>
        {selectedRental ? (
          (() => {
            const presence = selectedRental.presence ?? null;
            const frozen = !!selectedRental.rentalFrozen;
            const presenceLabel = frozen
              ? "Frozen"
              : presence?.in_match
                ? "In match"
                : presence?.in_game
                  ? "In game"
                  : "Offline";
            const pill = statusPill(presenceLabel);
            const timeLeft =
              selectedRental.durationSec != null && selectedRental.startedAt != null
                ? formatDuration(
                    selectedRental.durationSec,
                    selectedRental.startedAt,
                    now,
                    frozen ? selectedRental.rentalFrozenAt ?? null : null
                  )
                : "-";
            const matchTime = getMatchTimeLabel(presence);
            const heroLabel = presence?.hero_name || selectedRental.hero || "-";
            return (
              <div className="space-y-4">
                <div className="rounded-xl border border-neutral-200 bg-neutral-50 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
                        Selected rental
                      </div>
                      <div className="mt-1 text-sm font-semibold text-neutral-900">
                        {selectedRental.accountName || "Rental"}
                      </div>
                    </div>
                    <span className={`rounded-full px-3 py-1 text-xs font-semibold ${pill.className}`}>
                      {presenceLabel}
                    </span>
                  </div>
                  <div className="mt-3 grid gap-1 text-xs text-neutral-600">
                    <span>Buyer: {selectedRental.buyer || "-"}</span>
                    <span>Time left: {timeLeft}</span>
                    <span>Match time: {matchTime}</span>
                    <span>Hero: {heroLabel}</span>
                    <span>Workspace: {resolveKeyLabel(selectedRental.keyId)}</span>
                    <span>
                      Started: {selectedRental.startedAt ? formatStartTime(selectedRental.startedAt) : "-"}
                    </span>
                    {frozen && (
                      <span className="text-rose-600">Frozen: timer paused until you unfreeze.</span>
                    )}
                  </div>
                  {selectedRental.chatUrl && (
                    <a
                      href={selectedRental.chatUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="mt-3 inline-flex items-center justify-center rounded-lg border border-neutral-200 bg-white px-3 py-2 text-xs font-semibold text-neutral-700 transition hover:bg-neutral-100"
                    >
                      Open chat
                    </a>
                  )}
                </div>
                <div className="rounded-xl border border-neutral-200 bg-neutral-50 p-4">
                  <div className="mb-2 text-sm font-semibold text-neutral-800">Freeze rental</div>
                  <p className="text-xs text-neutral-500">
                    Freezing pauses the timer and kicks the user from Steam.
                  </p>
                  <button
                    onClick={() => handleToggleRentalFreeze(!frozen)}
                    disabled={rentalActionBusy}
                    className={`mt-3 w-full rounded-lg px-4 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-60 ${
                      frozen
                        ? "border border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100"
                        : "border border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100"
                    }`}
                  >
                    {frozen ? "Unfreeze rental" : "Freeze rental"}
                  </button>
                </div>
                <div className="rounded-xl border border-neutral-200 bg-neutral-50 p-4">
                  <div className="mb-2 text-sm font-semibold text-neutral-800">Extend rental</div>
                  <div className="grid grid-cols-2 gap-3">
                    <input
                      value={rentalExtendHours}
                      onChange={(e) => setRentalExtendHours(e.target.value)}
                      placeholder="Hours"
                      type="number"
                      min="0"
                      className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 outline-none placeholder:text-neutral-400"
                    />
                    <input
                      value={rentalExtendMinutes}
                      onChange={(e) => setRentalExtendMinutes(e.target.value)}
                      placeholder="Minutes"
                      type="number"
                      min="0"
                      className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 outline-none placeholder:text-neutral-400"
                    />
                  </div>
                  <button
                    onClick={handleExtendRental}
                    disabled={rentalActionBusy}
                    className="mt-3 w-full rounded-lg bg-neutral-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-neutral-800 disabled:cursor-not-allowed disabled:bg-neutral-300"
                  >
                    Extend rental
                  </button>
                </div>
                <div className="rounded-xl border border-neutral-200 bg-neutral-50 p-4">
                  <div className="mb-2 text-sm font-semibold text-neutral-800">End rental</div>
                  <p className="text-xs text-neutral-500">Stops the rental and releases the account.</p>
                  <button
                    onClick={handleReleaseRental}
                    disabled={rentalActionBusy}
                    className="mt-3 w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm font-semibold text-neutral-700 transition hover:bg-neutral-100 disabled:cursor-not-allowed disabled:text-neutral-400"
                  >
                    Release rental
                  </button>
                </div>
              </div>
            );
          })()
        ) : (
          <div className="rounded-xl border border-dashed border-neutral-200 bg-neutral-50 px-4 py-6 text-center text-sm text-neutral-500">
            Select an active rental to unlock actions.
          </div>
        )}
      </div>
    );
  };

  const renderInventoryActionsPanel = () => {
    const frozen = !!selectedAccount?.accountFrozen;
    return (
      <div className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm shadow-neutral-200/70">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-semibold text-neutral-900">Account controls</h3>
          <span className="text-xs text-neutral-500">{selectedAccount ? "Ready" : "Select an account"}</span>
        </div>
        {selectedAccount ? (
          <div className="space-y-4">
            <div className="rounded-xl border border-neutral-200 bg-neutral-50 p-4">
              <div className="mb-2 text-sm font-semibold text-neutral-800">Freeze account</div>
              <p className="text-xs text-neutral-500">
                Frozen accounts are hidden from available slots until you unfreeze them.
              </p>
              <button
                onClick={() => handleToggleAccountFreeze(!frozen)}
                disabled={accountActionBusy}
                className={`mt-3 w-full rounded-lg px-4 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-60 ${
                  frozen
                    ? "border border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100"
                    : "border border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100"
                }`}
              >
                {frozen ? "Unfreeze account" : "Freeze account"}
              </button>
            </div>
            <div className="rounded-xl border border-neutral-200 bg-neutral-50 p-4">
              <div className="mb-2 text-sm font-semibold text-neutral-800">Delete account</div>
              <p className="text-xs text-neutral-500">Removes the account and its lot mapping.</p>
              <button
                onClick={handleDeleteAccount}
                disabled={accountActionBusy}
                className="mt-3 w-full rounded-lg border border-rose-200 bg-rose-50 px-4 py-2 text-sm font-semibold text-rose-700 transition hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-60"
              >
                Delete account
              </button>
            </div>
          </div>
        ) : (
          <div className="rounded-xl border border-dashed border-neutral-200 bg-neutral-50 px-4 py-6 text-center text-sm text-neutral-500">
            Select an account to manage freeze & deletion.
          </div>
        )}
      </div>
    );
  };

  const ToggleRow: React.FC<{
    label: string;
    enabled: boolean;
    onChange: (next: boolean) => void;
    disabled?: boolean;
  }> = ({ label, enabled, onChange, disabled }) => (
    <button
      type="button"
      onClick={() => {
        if (disabled) return;
        onChange(!enabled);
      }}
      disabled={disabled}
      className="flex h-16 w-full items-center justify-between rounded-xl border border-neutral-200 bg-white px-4 text-left shadow-sm transition hover:-translate-y-0.5 hover:shadow-md"
    >
      <div className="text-sm font-semibold text-neutral-900">{label}</div>
      <div
        className={`relative flex h-8 w-14 items-center rounded-full transition-all duration-300 ease-out ${
          enabled ? "bg-emerald-500/90 shadow-[0_10px_25px_-12px_rgba(16,185,129,0.9)]" : "bg-neutral-300"
        }`}
      >
        <span
          className={`absolute left-1 h-6 w-6 rounded-full bg-white shadow transform transition-all duration-300 ease-out ${
            enabled ? "translate-x-6" : "translate-x-0"
          }`}
        />
      </div>
    </button>
  );

  const handleCreateAccount = async (payload: Record<string, unknown>) => {
    if (!token) throw new Error("Not authorized");
    setSubmittingAccount(true);
    try {
      const nextPayload: Record<string, unknown> = { ...payload };
      if (nextPayload.key_id === undefined && activeKeyId !== "all") {
        nextPayload.key_id = activeKeyId;
      }
      if (activeKeyId === "all" && (nextPayload.key_id === undefined || nextPayload.key_id === null)) {
        showToast("Select a workspace for this account.", "error");
        return;
      }
      await apiFetch("/api/accounts", { method: "POST", body: JSON.stringify(nextPayload) });
      await Promise.all([loadOverview()]);
    } finally {
      setSubmittingAccount(false);
    }
  };

  const handleAssignAccount = async () => {
    if (!selectedAccount) {
      showToast("Select an account first.", "error");
      return;
    }
    if (accountActionBusy) return;
    if (selectedAccount.accountFrozen) {
      showToast("Unfreeze the account before assigning a buyer.", "error");
      return;
    }
    const owner = assignOwner.trim();
    if (!owner) {
      showToast("Enter a buyer username.", "error");
      return;
    }
    const accountId = selectedAccount.id;
    if (accountId === null || accountId === undefined) {
      showToast("Invalid account selected.", "error");
      return;
    }
    setAccountActionBusy(true);
    try {
      await apiFetch(`/api/accounts/${encodeURIComponent(String(accountId))}/assign`, {
        method: "POST",
        headers: buildKeyHeader(selectedAccount.keyId),
        body: JSON.stringify({ owner }),
      });
      showToast("Rental assigned.");
      await Promise.all([loadOverview()]);
    } catch (error) {
      showToast((error as Error).message || "Failed to assign rental.", "error");
    } finally {
      setAccountActionBusy(false);
    }
  };

  const handleUpdateAccount = async () => {
    if (!selectedAccount) {
      showToast("Select an account first.", "error");
      return;
    }
    if (accountActionBusy) return;
    const accountId = selectedAccount.id;
    if (accountId === null || accountId === undefined) {
      showToast("Invalid account selected.", "error");
      return;
    }
    const payload: Record<string, unknown> = {};
    const name = accountEditName.trim();
    const login = accountEditLogin.trim();
    const password = accountEditPassword.trim();
    const mmrRaw = accountEditMmr.trim();
    const keyRaw = accountEditKeyId.trim();

    if (name && name !== (selectedAccount.name || "")) payload.account_name = name;
    if (login && login !== (selectedAccount.login || "")) payload.login = login;
    if (password && password !== (selectedAccount.password || "")) payload.password = password;
    if (mmrRaw) {
      const mmr = Number(mmrRaw);
      if (!Number.isFinite(mmr) || mmr < 0) {
        showToast("MMR must be 0 or higher.", "error");
        return;
      }
      if (String(mmr) !== String(selectedAccount.mmr ?? "")) payload.mmr = mmr;
    }
    if (!keyRaw) {
      if (selectedAccount.keyId !== null && selectedAccount.keyId !== undefined) {
        payload.key_id = null;
      }
    } else {
      const keyValue = Number(keyRaw);
      if (!Number.isFinite(keyValue)) {
        showToast("Select a workspace.", "error");
        return;
      }
      if (String(keyValue) !== String(selectedAccount.keyId ?? "")) {
        payload.key_id = keyValue;
      }
    }
    if (!Object.keys(payload).length) {
      showToast("No changes to save.", "error");
      return;
    }
    setAccountActionBusy(true);
    try {
      await apiFetch(`/api/accounts/${encodeURIComponent(String(accountId))}`, {
        method: "PATCH",
        headers: buildKeyHeader(selectedAccount.keyId),
        body: JSON.stringify(payload),
      });
      showToast("Account updated.");
      await Promise.all([loadOverview()]);
    } catch (error) {
      showToast((error as Error).message || "Failed to update account.", "error");
    } finally {
      setAccountActionBusy(false);
    }
  };

  const handleToggleAccountFreeze = async (nextFrozen: boolean) => {
    if (!selectedAccount) {
      showToast("Select an account first.", "error");
      return;
    }
    if (accountActionBusy) return;
    const accountId = selectedAccount.id;
    if (accountId === null || accountId === undefined) {
      showToast("Invalid account selected.", "error");
      return;
    }
    setAccountActionBusy(true);
    try {
      await apiFetch(`/api/accounts/${encodeURIComponent(String(accountId))}/freeze`, {
        method: "POST",
        headers: buildKeyHeader(selectedAccount.keyId),
        body: JSON.stringify({ frozen: nextFrozen }),
      });
      showToast(nextFrozen ? "Account frozen." : "Account unfrozen.");
      await Promise.all([loadOverview()]);
    } catch (error) {
      showToast((error as Error).message || "Failed to update freeze state.", "error");
    } finally {
      setAccountActionBusy(false);
    }
  };

  const handleDeleteAccount = async () => {
    if (!selectedAccount) {
      showToast("Select an account first.", "error");
      return;
    }
    if (accountActionBusy) return;
    const accountId = selectedAccount.id;
    if (accountId === null || accountId === undefined) {
      showToast("Invalid account selected.", "error");
      return;
    }
    const label = selectedAccount.name || `ID ${accountId}`;
    if (!window.confirm(`Delete ${label}? This cannot be undone.`)) return;
    setAccountActionBusy(true);
    try {
      await apiFetch(`/api/accounts/${encodeURIComponent(String(accountId))}`, {
        method: "DELETE",
        headers: buildKeyHeader(selectedAccount.keyId),
      });
      showToast("Account deleted.");
      setSelectedAccountId(null);
      await Promise.all([loadOverview()]);
    } catch (error) {
      showToast((error as Error).message || "Failed to delete account.", "error");
    } finally {
      setAccountActionBusy(false);
    }
  };

  const handleExtendRental = async () => {
    if (!selectedRental) {
      showToast("Select a rental first.", "error");
      return;
    }
    if (rentalActionBusy) return;
    const accountId = selectedRental.id;
    if (accountId === null || accountId === undefined) {
      showToast("Invalid rental selected.", "error");
      return;
    }
    const hoursValue = parseInt(rentalExtendHours, 10);
    const minutesValue = parseInt(rentalExtendMinutes, 10);
    const hours = Number.isFinite(hoursValue) && hoursValue > 0 ? hoursValue : 0;
    const minutes = Number.isFinite(minutesValue) && minutesValue > 0 ? minutesValue : 0;
    if (!hours && !minutes) {
      showToast("Enter a time extension.", "error");
      return;
    }
    setRentalActionBusy(true);
    try {
      await apiFetch(`/api/accounts/${encodeURIComponent(String(accountId))}/extend`, {
        method: "POST",
        headers: buildKeyHeader(selectedRental.keyId),
        body: JSON.stringify({ hours, minutes }),
      });
      showToast("Rental extended.");
      setRentalExtendHours("");
      setRentalExtendMinutes("");
      await Promise.all([loadOverview()]);
    } catch (error) {
      showToast((error as Error).message || "Failed to extend rental.", "error");
    } finally {
      setRentalActionBusy(false);
    }
  };

  const handleReleaseRental = async () => {
    if (!selectedRental) {
      showToast("Select a rental first.", "error");
      return;
    }
    if (rentalActionBusy) return;
    const accountId = selectedRental.id;
    if (accountId === null || accountId === undefined) {
      showToast("Invalid rental selected.", "error");
      return;
    }
    setRentalActionBusy(true);
    try {
      await apiFetch(`/api/accounts/${encodeURIComponent(String(accountId))}/release`, {
        method: "POST",
        headers: buildKeyHeader(selectedRental.keyId),
      });
      showToast("Rental released.");
      await Promise.all([loadOverview()]);
    } catch (error) {
      showToast((error as Error).message || "Failed to release rental.", "error");
    } finally {
      setRentalActionBusy(false);
    }
  };

  const handleToggleRentalFreeze = async (nextFrozen: boolean) => {
    if (!selectedRental) {
      showToast("Select a rental first.", "error");
      return;
    }
    if (rentalActionBusy) return;
    const accountId = selectedRental.id;
    if (accountId === null || accountId === undefined) {
      showToast("Invalid rental selected.", "error");
      return;
    }
    setRentalActionBusy(true);
    try {
      await apiFetch(`/api/rentals/${encodeURIComponent(String(accountId))}/freeze`, {
        method: "POST",
        headers: buildKeyHeader(selectedRental.keyId),
        body: JSON.stringify({ frozen: nextFrozen }),
      });
      showToast(nextFrozen ? "Rental frozen." : "Rental unfrozen.");
      await Promise.all([loadOverview()]);
    } catch (error) {
      showToast((error as Error).message || "Failed to update rental state.", "error");
    } finally {
      setRentalActionBusy(false);
    }
  };

  const toggleBlacklistSelected = (owner: string) => {
    setBlacklistSelected((prev) => (prev.includes(owner) ? prev.filter((item) => item !== owner) : [...prev, owner]));
  };

  const toggleBlacklistSelectAll = () => {
    if (!blacklistEntries.length) return;
    setBlacklistSelected((prev) =>
      prev.length === blacklistEntries.length ? [] : blacklistEntries.map((entry) => entry.owner)
    );
  };

  const handleAddBlacklist = async () => {
    if (activeKeyId === "all") {
      showToast("Select a workspace to manage the blacklist.", "error");
      return;
    }
    let owner = blacklistOwner.trim();
    const orderId = blacklistOrderId.trim();
    try {
      if (!owner && orderId) {
        setBlacklistResolving(true);
        const resolved = await apiFetch<{ owner?: string }>(
          `/api/orders/resolve?order_id=${encodeURIComponent(orderId)}`
        );
        owner = (resolved?.owner || "").trim();
        if (!owner) {
          showToast("Order found but buyer is missing.", "error");
          setBlacklistResolving(false);
          return;
        }
        setBlacklistOwner(owner);
      }
      if (!owner) {
        showToast("Enter a buyer username or order ID.", "error");
        return;
      }
      await apiFetch("/api/blacklist", {
        method: "POST",
        body: JSON.stringify({ owner, reason: blacklistReason.trim() || null, order_id: orderId || null }),
      });
      showToast("User added to blacklist.");
      setBlacklistOwner("");
      setBlacklistOrderId("");
      setBlacklistReason("");
      loadBlacklist(blacklistQuery, true);
    } catch (error) {
      showToast((error as Error).message || "Failed to add user", "error");
    } finally {
      setBlacklistResolving(false);
    }
  };

  const handleResolveBlacklistOrder = async () => {
    if (activeKeyId === "all") {
      showToast("Select a workspace to manage the blacklist.", "error");
      return;
    }
    const orderId = blacklistOrderId.trim();
    if (!orderId) {
      showToast("Enter an order ID.", "error");
      return;
    }
    try {
      setBlacklistResolving(true);
      const resolved = await apiFetch<{ owner?: string }>(
        `/api/orders/resolve?order_id=${encodeURIComponent(orderId)}`
      );
      const owner = (resolved?.owner || "").trim();
      if (!owner) {
        showToast("Order found but buyer is missing.", "error");
        return;
      }
      setBlacklistOwner(owner);
      showToast(`Buyer найден: ${owner}`);
    } catch (error) {
      showToast((error as Error).message || "Order not found.", "error");
    } finally {
      setBlacklistResolving(false);
    }
  };

  const startEditBlacklist = (entry: BlacklistEntry) => {
    setBlacklistEditingId(entry.id ?? null);
    setBlacklistEditOwner(entry.owner || "");
    setBlacklistEditReason(entry.reason || "");
  };

  const cancelEditBlacklist = () => {
    setBlacklistEditingId(null);
    setBlacklistEditOwner("");
    setBlacklistEditReason("");
  };

  const handleSaveBlacklistEdit = async () => {
    if (blacklistEditingId === null || blacklistEditingId === undefined) return;
    if (activeKeyId === "all") {
      showToast("Select a workspace to manage the blacklist.", "error");
      return;
    }
    const owner = blacklistEditOwner.trim();
    if (!owner) {
      showToast("Owner is required.", "error");
      return;
    }
    try {
      await apiFetch(`/api/blacklist/${encodeURIComponent(String(blacklistEditingId))}`, {
        method: "PATCH",
        body: JSON.stringify({ owner, reason: blacklistEditReason.trim() || null }),
      });
      showToast("Blacklist entry updated.");
      cancelEditBlacklist();
      loadBlacklist(blacklistQuery, true);
    } catch (error) {
      showToast((error as Error).message || "Failed to update entry", "error");
    }
  };

  const handleRemoveSelected = async () => {
    if (!blacklistSelected.length) {
      showToast("Select users to unblacklist.", "error");
      return;
    }
    if (activeKeyId === "all") {
      showToast("Select a workspace to manage the blacklist.", "error");
      return;
    }
    try {
      await apiFetch("/api/blacklist/remove", {
        method: "POST",
        body: JSON.stringify({ owners: blacklistSelected }),
      });
      showToast("Selected users removed from blacklist.");
      setBlacklistSelected([]);
      loadBlacklist(blacklistQuery, true);
    } catch (error) {
      showToast((error as Error).message || "Failed to unblacklist users", "error");
    }
  };

  const handleClearBlacklist = async () => {
    if (!blacklistEntries.length) {
      showToast("Blacklist is already empty.", "error");
      return;
    }
    if (activeKeyId === "all") {
      showToast("Select a workspace to manage the blacklist.", "error");
      return;
    }
    if (!window.confirm("Remove everyone from the blacklist...")) return;
    try {
      await apiFetch("/api/blacklist/clear", { method: "POST" });
      showToast("Blacklist cleared.");
      setBlacklistSelected([]);
      loadBlacklist(blacklistQuery, true);
    } catch (error) {
      showToast((error as Error).message || "Failed to clear blacklist", "error");
    }
  };

  const handleCreateLot = async () => {
    if (lotActionBusy) return;
    const numberValue = Number(lotNumber);
    const accountValue = Number(lotAccountId);
    if (!Number.isFinite(numberValue) || numberValue <= 0) {
      showToast("Enter a valid lot number.", "error");
      return;
    }
    if (!Number.isFinite(accountValue) || accountValue <= 0) {
      showToast("Select an account for this lot.", "error");
      return;
    }
    const targetKey = targetLotKeyId;
    if (activeKeyId === "all" && !targetKey) {
      showToast("Select a workspace for this lot.", "error");
      return;
    }
    const payload: Record<string, unknown> = {
      lot_number: numberValue,
      account_id: accountValue,
      lot_url: lotUrl.trim() || null,
    };
    if (targetKey !== null) {
      payload.key_id = targetKey;
    }
    setLotActionBusy(true);
    try {
      await apiFetch("/api/lots", {
        method: "POST",
        headers: buildKeyHeader(targetKey),
        body: JSON.stringify(payload),
      });
      showToast("Lot mapping saved.");
      setLotNumber("");
      setLotAccountId("");
      setLotUrl("");
      loadLots(true);
    } catch (error) {
      showToast((error as Error).message || "Failed to save lot.", "error");
    } finally {
      setLotActionBusy(false);
    }
  };

  const startEditLot = (item: LotRow) => {
    setEditingLotNumber(item.lotNumber);
    setEditingLotKeyId(item.keyId ?? null);
    setEditLotNumber(String(item.lotNumber));
    setEditLotAccountId(String(item.accountId));
    setEditLotUrl(item.lotUrl ?? "");
  };

  const cancelEditLot = () => {
    setEditingLotNumber(null);
    setEditingLotKeyId(null);
    setEditLotNumber("");
    setEditLotAccountId("");
    setEditLotUrl("");
  };

  const handleSaveLotEdit = async () => {
    if (editingLotNumber === null || lotActionBusy) return;
    const nextLotNumber = Number(editLotNumber);
    const nextAccountId = Number(editLotAccountId);
    if (!Number.isFinite(nextLotNumber) || nextLotNumber <= 0) {
      showToast("Enter a valid lot number.", "error");
      return;
    }
    if (!Number.isFinite(nextAccountId) || nextAccountId <= 0) {
      showToast("Select a valid account.", "error");
      return;
    }
    const targetKey = editingLotKeyId;
    const payload: Record<string, unknown> = {
      lot_number: nextLotNumber,
      account_id: nextAccountId,
      lot_url: editLotUrl.trim() || null,
    };
    if (targetKey !== null) {
      payload.key_id = targetKey;
    }
    setLotActionBusy(true);
    try {
      if (nextLotNumber !== editingLotNumber) {
        await apiFetch(`/api/lots/${encodeURIComponent(String(editingLotNumber))}`, {
          method: "DELETE",
          headers: buildKeyHeader(targetKey),
        });
      }
      await apiFetch("/api/lots", {
        method: "POST",
        headers: buildKeyHeader(targetKey),
        body: JSON.stringify(payload),
      });
      showToast("Lot mapping updated.");
      cancelEditLot();
      loadLots(true);
    } catch (error) {
      showToast((error as Error).message || "Failed to update lot.", "error");
    } finally {
      setLotActionBusy(false);
    }
  };

  const handleDeleteLot = async (item: LotRow) => {
    if (lotActionBusy) return;
    if (!window.confirm(`Delete lot #${item.lotNumber}?`)) return;
    setLotActionBusy(true);
    try {
      await apiFetch(`/api/lots/${encodeURIComponent(String(item.lotNumber))}`, {
        method: "DELETE",
        headers: buildKeyHeader(item.keyId),
      });
      showToast("Lot mapping removed.");
      loadLots(true);
    } catch (error) {
      showToast((error as Error).message || "Failed to remove lot.", "error");
    } finally {
      setLotActionBusy(false);
    }
  };

  const sendChatMessage = async () => {
    const text = chatInput.trim();
    if (!text || selectedChat === null || selectedChat === undefined) {
      showToast("Select a chat and type a message.", "error");
      return;
    }
    setChatInput("");
    const chatKey = String(selectedChat);
    const cacheKey = scopedKey(`${CHAT_HISTORY_CACHE_PREFIX}${chatKey}`);
    const optimistic: ChatMessage = {
      id: `local-${Date.now()}`,
      author: "You",
      text,
      sentAt: new Date().toLocaleTimeString(),
      byBot: true,
    };
    setChatMessages((prev) => {
      const next = [...prev, optimistic];
      writeCache(cacheKey, next);
      return next;
    });
    updateChatPreview(chatKey, optimistic);
    if (chatWsConnected && sendChatWs({ type: "send", chat_id: selectedChat, text })) {
      return;
    }
    try {
      await apiFetch(`/api/chats/${selectedChat}/send`, {
        method: "POST",
        body: JSON.stringify({ text }),
      });
      loadChatHistory(selectedChat, true);
    } catch (error) {
      showToast((error as Error).message || "Failed to send", "error");
      setChatMessages((prev) => prev.filter((m) => m.id !== optimistic.id));
    }
  };

  const allBlacklistSelected =
    blacklistEntries.length > 0 && blacklistSelected.length === blacklistEntries.length;
  const activeLabel =
    activeNav === "profile" ? "Profile" : NAV_ITEMS.find((n) => n.id === activeNav)?.label || "Dashboard";
  const profileInitial = (profileName || "U").trim().charAt(0).toUpperCase();
  const totalAdminCalls = useMemo(
    () => chats.reduce((sum, chat) => sum + (chat.adminCalls || 0), 0),
    [chats]
  );
  const totalBlacklisted = useMemo(() => blacklistEntries.length, [blacklistEntries]);
  const targetLotKeyId = useMemo(() => {
    if (activeKeyId !== "all") return activeKeyId;
    const raw = lotKeyId.trim();
    if (!raw) return null;
    const parsed = Number(raw);
    return Number.isFinite(parsed) ? parsed : null;
  }, [activeKeyId, lotKeyId]);
  const mappedAccountIds = useMemo(() => {
    const set = new Set<string>();
    lots.forEach((item) => {
      if (item.accountId !== undefined && item.accountId !== null) {
        set.add(String(item.accountId));
      }
    });
    return set;
  }, [lots]);
  const scopedLots = useMemo(() => {
    if (activeKeyId === "all") return lots;
    return lots.filter((item) => {
      const keyValue = item.keyId ?? null;
      return keyValue === null || keyValue === activeKeyId;
    });
  }, [lots, activeKeyId]);
  const filteredLots = useMemo(() => {
    const query = lotsQuery.trim().toLowerCase();
    if (!query) return scopedLots;
    return scopedLots.filter((item) => {
      const accountName = (item.accountName || "").toLowerCase();
      const owner = (item.owner || "").toLowerCase();
      return (
        String(item.lotNumber).includes(query) ||
        String(item.accountId).includes(query) ||
        accountName.includes(query) ||
        owner.includes(query)
      );
    });
  }, [scopedLots, lotsQuery]);
  const lotAccounts = useMemo(() => {
    if (activeKeyId !== "all") return accountsTable;
    if (!targetLotKeyId) return accountsTable;
    return accountsTable.filter((acc) => {
      const keyValue = acc.keyId ?? null;
      return keyValue === targetLotKeyId || keyValue === null;
    });
  }, [accountsTable, activeKeyId, targetLotKeyId]);

  return (
    <>
      <AnimatePresence mode="wait">
        {authState === "guest" ? (
          <motion.div
            key="login"
            initial={{ opacity: 0, x: 40 }}
            animate={{ opacity: 1, x: 0, transition: { duration: 0.9, ease: EASE } }}
            exit={{ opacity: 0, x: -40, transition: { duration: 0.5, ease: EASE } }}
          >
            <LoginPage
              onLogin={handleLogin}
              onRegister={handleRegister}
              onToast={(message, isError) => showToast(message, isError ? "error" : "success")}
            />
          </motion.div>
        ) : (
          <motion.div
            key="shell"
            initial={{ opacity: 0, x: 60 }}
            animate={{ opacity: 1, x: 0, transition: { duration: 0.9, ease: EASE } }}
            exit={{ opacity: 0, x: -60, transition: { duration: 0.5, ease: EASE } }}
            className="min-h-screen bg-white text-slate-900"
          >
            <div className="flex min-h-screen">
              <aside className="relative flex w-[280px] shrink-0 flex-col border-r border-neutral-100 bg-white px-6 pb-10 pt-10 shadow-[12px_0_40px_-32px_rgba(0,0,0,0.15)]">
                <div className="text-lg font-semibold tracking-tight text-neutral-900">Funpay Automation</div>
                <nav className="relative mt-8 flex flex-1 flex-col">
                  <div className="flex flex-col space-y-2">
                    <AnimatePresence>
                      {NAV_ITEMS.filter((i) => !BOTTOM_NAV_IDS.has(i.id)).map((item) => {
                        const isActive = activeNav === item.id;
                        const showAdminBadge = item.id === "chats" && totalAdminCalls > 0;
                        const showBlacklistBadge = item.id === "blacklist" && totalBlacklisted > 0;
                        return (
                          <motion.button
                            key={item.id}
                            type="button"
                            onClick={() => {
                              setActiveNav(item.id);
                              const nextPath = navIdToPath[item.id] || "/dashboard";
                              window.history.replaceState(null, "", nextPath);
                              setPathname(nextPath);
                            }}
                            className="relative flex w-full items-center gap-3 overflow-hidden rounded-xl px-4 py-3 text-left text-sm font-semibold transition focus:outline-none"
                            whileHover={{ scale: 1.01 }}
                            transition={{ type: "spring", stiffness: 320, damping: 30 }}
                          >
                            {isActive && (
                              <motion.span
                                layoutId="navHighlight"
                                className="absolute inset-0 rounded-md bg-neutral-900 text-white shadow-[0_10px_25px_-15px_rgba(0,0,0,0.45)]"
                                transition={{ type: "spring", stiffness: 280, damping: 26 }}
                              />
                            )}
                            <span className={`relative z-10 text-base ${isActive ? "text-white" : "text-neutral-500"}`}>
                              <item.Icon />
                            </span>
                            <span className={`relative z-10 truncate ${isActive ? "text-white" : "text-neutral-700"}`}>
                              {item.label}
                            </span>
                            {showAdminBadge && (
                              <span
                                className={`relative z-10 ml-auto rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                                  isActive ? "bg-white/20 text-white" : "bg-rose-100 text-rose-600"
                                }`}
                              >
                                {totalAdminCalls}
                              </span>
                            )}
                            {!showAdminBadge && showBlacklistBadge && (
                              <span
                                className={`relative z-10 ml-auto rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                                  isActive ? "bg-white/20 text-white" : "bg-amber-100 text-amber-700"
                                }`}
                              >
                                {totalBlacklisted}
                              </span>
                            )}
                          </motion.button>
                        );
                      })}
                    </AnimatePresence>
                  </div>
                  <div className="mt-auto flex flex-col space-y-2 pb-2">
                    <AnimatePresence>
                      {NAV_ITEMS.filter((i) => BOTTOM_NAV_IDS.has(i.id)).map((item) => {
                        const isActive = activeNav === item.id;
                        return (
                          <motion.button
                            key={item.id}
                            type="button"
                            onClick={() => {
                              setActiveNav(item.id);
                              const nextPath = navIdToPath[item.id] || "/dashboard";
                              window.history.replaceState(null, "", nextPath);
                              setPathname(nextPath);
                            }}
                            className="relative flex w-full items-center gap-3 overflow-hidden rounded-xl px-4 py-3 text-left text-sm font-semibold transition focus:outline-none"
                            whileHover={{ scale: 1.01 }}
                            transition={{ type: "spring", stiffness: 320, damping: 30 }}
                          >
                            {isActive && (
                              <motion.span
                                layoutId="navHighlight"
                                className="absolute inset-0 rounded-md bg-neutral-900 text-white shadow-[0_10px_25px_-15px_rgba(0,0,0,0.45)]"
                                transition={{ type: "spring", stiffness: 280, damping: 26 }}
                              />
                            )}
                            <span className={`relative z-10 text-base ${isActive ? "text-white" : "text-neutral-500"}`}>
                              <item.Icon />
                            </span>
                            <span className={`relative z-10 truncate ${isActive ? "text-white" : "text-neutral-700"}`}>
                              {item.label}
                            </span>
                          </motion.button>
                        );
                      })}
                    </AnimatePresence>
                  </div>
                </nav>
              </aside>
              <main className="relative flex-1 bg-white">
                <div className="absolute left-0 top-0 h-full w-px bg-neutral-200" />
                <motion.div
                  initial={{ opacity: 0, y: 16 }}
                  animate={{ opacity: 1, y: 0, transition: { duration: 0.7, ease: EASE } }}
                  className="pl-10 pr-10 pt-5 pb-12"
                >
                  <div className="-mx-10 flex items-center justify-between gap-6 border-b border-neutral-200 px-10 pb-4">
                    <div>
                      <h1 className="text-2xl font-semibold text-neutral-900">{activeLabel}</h1>
                    </div>
                    <div className="flex items-center gap-4">
                      <div className="flex items-center gap-2 rounded-lg border border-neutral-200 bg-neutral-50 px-3 py-2 text-xs font-semibold text-neutral-600 shadow-sm shadow-neutral-200">
                        <span className="hidden sm:inline text-[11px] uppercase tracking-wide text-neutral-500">
                          Workspace
                        </span>
                        <select
                          value={activeKeyId === "all" ? "all" : String(activeKeyId)}
                          onChange={(event) => {
                            const next = event.target.value;
                            const parsed = Number(next);
                            setActiveKeyId(next === "all" || !Number.isFinite(parsed) ? "all" : parsed);
                          }}
                          className="bg-transparent text-sm font-semibold text-neutral-700 outline-none"
                          disabled={keysLoading}
                        >
                          <option value="all">All workspaces</option>
                          {userKeys.map((item) => (
                            <option key={item.id} value={item.id}>
                              {item.label || `Workspace ${item.id}`}
                              {item.is_default ? " (Default)" : ""}
                            </option>
                          ))}
                        </select>
                        <button
                          type="button"
                          onClick={() => {
                            setActiveNav("settings");
                            const nextPath = navIdToPath.settings || "/settings";
                            window.history.replaceState(null, "", nextPath);
                            setPathname(nextPath);
                          }}
                          className="rounded-md border border-neutral-200 bg-white px-2 py-1 text-[11px] font-semibold text-neutral-600 transition hover:bg-neutral-100"
                        >
                          Manage
                        </button>
                      </div>
                      <label className="relative flex h-11 w-72 items-center gap-3 rounded-lg border border-neutral-200 bg-neutral-50 px-4 text-sm text-neutral-500 shadow-sm shadow-neutral-200">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                          <path
                            d="M11 19C15.4183 19 19 15.4183 19 11C19 6.58172 15.4183 3 11 3C6.58172 3 3 6.58172 3 11C3 15.4183 6.58172 19 11 19Z"
                            stroke="#9CA3AF"
                            strokeWidth="2"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          />
                          <path d="M21 21L16.65 16.65" stroke="#9CA3AF" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                        <input
                          type="search"
                          placeholder="Search..."
                          className="w-full bg-transparent text-neutral-700 placeholder:text-neutral-400 outline-none"
                        />
                      </label>
                      <button
                        type="button"
                        onClick={() => {
                          setActiveNav("profile");
                          const nextPath = navIdToPath.profile || "/profile";
                          window.history.replaceState(null, "", nextPath);
                          setPathname(nextPath);
                        }}
                        className="flex h-10 w-10 items-center justify-center rounded-full bg-neutral-900 text-sm font-semibold text-white shadow-sm"
                        aria-label="Profile"
                        title="Profile"
                      >
                        {profileInitial}
                      </button>
                    </div>
                  </div>
                  {activeNav === "overview" && (
                    <div className="mt-6">
                      <div className="mb-4 text-lg font-semibold text-neutral-800">Overview</div>
                      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
                        {overviewCards.map((card) => {
                          const value = (overview as Record<string, number | null>)[card.key] ?? null;
                          return (
                            <motion.div
                              key={card.title}
                              className="group relative rounded-xl border border-neutral-200 bg-white p-4 shadow-sm shadow-neutral-200/60"
                              whileHover={{ y: -2, scale: 1.01 }}
                              transition={{ duration: 0.15, ease: EASE }}
                            >
                              <div className="flex items-center justify-between">
                                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-neutral-100 text-neutral-600">
                                  <card.Icon />
                                </div>
                                <div
                                  className={`rounded-full px-3 py-1 text-xs font-semibold ${card.deltaTone === "negative" ? "bg-rose-50 text-rose-600" : "bg-emerald-50 text-emerald-600"}`}
                                >
                                  {card.delta}
                                </div>
                              </div>
                              <div className="mt-4 text-sm text-neutral-500">{card.title}</div>
                              <div className="mt-2 text-2xl font-semibold text-neutral-900">
                                {value === null ? "0" : value.toLocaleString()}
                              </div>
                            </motion.div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                  {activeNav === "funpay-stats" && (
                    activeKeyId === "all" ? (
                      <div className="mt-6 rounded-2xl border border-dashed border-neutral-200 bg-neutral-50 p-6">
                        <div className="text-sm font-semibold text-neutral-900">
                          Select a workspace to view FunPay stats
                        </div>
                        <p className="mt-2 text-xs text-neutral-500">
                          FunPay statistics are tied to a specific golden key. Choose a workspace from the top bar to
                          see balance, orders, and reviews.
                        </p>
                      </div>
                    ) : (
                      <div className="mt-6 space-y-6">
                      <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
                        <div>
                          <div className="text-lg font-semibold text-neutral-800">Funpay Statistics</div>
                          <div className="text-xs text-neutral-500">
                            {funpayStatsLoading ? "Refreshing..." : "Live data from your FunPay account."}
                          </div>
                        </div>
                        <button
                          onClick={() => loadFunpayStats(true, true)}
                          className="rounded-lg border border-neutral-200 bg-neutral-50 px-3 py-2 text-xs font-semibold text-neutral-600"
                        >
                          Refresh
                        </button>
                      </div>
                      <div className="grid gap-6 lg:grid-cols-2">
                        <div className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm shadow-neutral-200/70">
                          <div className="flex items-center justify-between">
                            <div>
                              <div className="text-sm font-semibold text-neutral-700">Balance</div>
                              <div className="mt-2 text-3xl font-bold text-neutral-900">RUB {balanceCurrent.toLocaleString()}</div>
                              <div className="mt-1 text-xs text-neutral-500">
                                {funpayStats.balance?.created_at
                                  ? `Updated ${new Date(funpayStats.balance.created_at).toLocaleString()}`
                                  : "Last 30 days"}
                              </div>
                            </div>
                            <div
                              className={`rounded-full px-3 py-1 text-xs font-semibold ${
                                balanceDelta >= 0 ? "bg-emerald-50 text-emerald-600" : "bg-rose-50 text-rose-600"
                              }`}
                            >
                              {balanceDelta >= 0 ? "+" : ""}
                              {balanceDeltaPct}%
                            </div>
                          </div>
                          <div className="mt-4 h-28">
                            <Sparkline values={balanceSeries.length ? balanceSeries : [0]} colorClass="text-emerald-500" />
                          </div>
                        </div>
                        <div className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm shadow-neutral-200/70">
                          <div className="flex flex-wrap items-center justify-between gap-3">
                            <div>
                              <div className="text-sm font-semibold text-neutral-700">Reviews</div>
                              <div className="mt-2 text-3xl font-bold text-neutral-900">{totalReviews.toLocaleString()}</div>
                              <div className="mt-1 text-xs text-neutral-500">Across selected period</div>
                            </div>
                            <div className="flex items-center gap-1 rounded-full bg-neutral-100 p-1">
                              {rangeOptions.map((option) => (
                                <button
                                  key={option.id}
                                  onClick={() => setReviewRange(option.id)}
                                  className={`rounded-full px-3 py-1 text-xs font-semibold transition ${
                                    reviewRange === option.id
                                      ? "bg-white text-neutral-900 shadow-sm"
                                      : "text-neutral-500 hover:text-neutral-700"
                                  }`}
                                >
                                  {option.label}
                                </button>
                              ))}
                            </div>
                          </div>
                          <div className="mt-4 h-28">
                            <Sparkline values={reviewSeries.length ? reviewSeries : [0]} colorClass="text-sky-500" />
                          </div>
                        </div>
                      </div>

                      <div className="grid gap-6 lg:grid-cols-2">
                        <div className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm shadow-neutral-200/70">
                          <div className="flex flex-wrap items-center justify-between gap-3">
                            <div>
                              <div className="text-sm font-semibold text-neutral-700">Orders</div>
                              <div className="mt-2 text-3xl font-bold text-neutral-900">{totalOrders.toLocaleString()}</div>
                              <div className="mt-1 text-xs text-neutral-500">Across selected period</div>
                            </div>
                            <div className="flex items-center gap-1 rounded-full bg-neutral-100 p-1">
                              {rangeOptions.map((option) => (
                                <button
                                  key={option.id}
                                  onClick={() => setOrderRange(option.id)}
                                  className={`rounded-full px-3 py-1 text-xs font-semibold transition ${
                                    orderRange === option.id
                                      ? "bg-white text-neutral-900 shadow-sm"
                                      : "text-neutral-500 hover:text-neutral-700"
                                  }`}
                                >
                                  {option.label}
                                </button>
                              ))}
                            </div>
                          </div>
                          <div className="mt-4">
                            <BarChart values={orderSeries.length ? orderSeries : [0]} barClass="bg-amber-500/80" />
                          </div>
                        </div>
                        <div className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm shadow-neutral-200/70">
                          <div className="mb-3 text-sm font-semibold text-neutral-700">Rental performance</div>
                          <div className="grid gap-4 lg:grid-cols-[1fr_1.2fr]">
                            <div className="rounded-xl border border-neutral-200 bg-neutral-50 p-4">
                              <div className="text-xs uppercase tracking-wide text-neutral-500">Average rent time</div>
                              <div className="mt-2 text-2xl font-semibold text-neutral-900">{averageRentalLabel}</div>
                              <div className="mt-2 h-2 w-full rounded-full bg-neutral-200">
                                <div
                                  className="h-2 rounded-full bg-emerald-500"
                                  style={{ width: `${averageRentalProgress * 100}%` }}
                                />
                              </div>
                              <div className="mt-2 text-xs text-neutral-500">
                                Total hours active: {overview.totalHours === null ? "-" : overview.totalHours}
                              </div>
                            </div>
                            <div className="rounded-xl border border-neutral-200 bg-neutral-50 p-4">
                              <div className="text-xs uppercase tracking-wide text-neutral-500">Rentals by account</div>
                              <div className="mt-3 space-y-3">
                                {accountUsage.length ? (
                                  accountUsage.map((item, idx) => {
                                    const maxCount = Math.max(1, ...accountUsage.map((row) => row.count));
                                    const width = (item.count / maxCount) * 100;
                                    return (
                                      <div key={`${item.label}-${idx}`} className="flex items-center gap-3">
                                        <span className="w-24 truncate text-xs font-semibold text-neutral-700">
                                          {item.label}
                                        </span>
                                        <div className="flex-1 h-2 rounded-full bg-neutral-200">
                                          <div className="h-2 rounded-full bg-neutral-900/80" style={{ width: `${width}%` }} />
                                        </div>
                                        <span className="text-xs text-neutral-500">{item.count}</span>
                                      </div>
                                    );
                                  })
                                ) : (
                                  <div className="text-xs text-neutral-500">No rental data yet.</div>
                                )}
                              </div>
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                  {activeNav !== "funpay-stats" && (
                  activeNav === "tickets" ? (
                    <motion.div
                      key="tickets"
                      initial={{ opacity: 0, y: 12 }}
                      animate={{ opacity: 1, y: 0, transition: { duration: 0.6, ease: EASE } }}
                      className="mt-8 space-y-4"
                    >
                      <div className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm shadow-neutral-200/70 max-w-4xl">
                        <div className="mb-4">
                          <h3 className="text-lg font-semibold text-neutral-900">FunPay Support Ticket (manual)</h3>
                          <p className="text-sm text-neutral-500">
                            Отправляет заявку от имени выбранного workspace на support.funpay.com.
                          </p>
                        </div>
                        <div className="space-y-3">
                          <label className="text-xs font-semibold text-neutral-600">Тема</label>
                          <select
                            value={ticketTopic}
                            onChange={(e) => setTicketTopic(e.target.value)}
                            className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 outline-none"
                          >
                            <option value="problem_order">Проблема с заказом</option>
                            <option value="problem_payment">Проблема с платежом</option>
                            <option value="problem_account">Проблема с аккаунтом FunPay</option>
                            <option value="problem_chat">Нарушение в чате</option>
                            <option value="other">Другое</option>
                          </select>
                          <label className="text-xs font-semibold text-neutral-600">Вы покупатель или продавец?</label>
                          <div className="flex items-center gap-4 text-sm text-neutral-700">
                            <label className="flex items-center gap-2">
                              <input
                                type="radio"
                                checked={ticketRole === "buyer"}
                                onChange={() => setTicketRole("buyer")}
                              />
                              Покупатель
                            </label>
                            <label className="flex items-center gap-2">
                              <input
                                type="radio"
                                checked={ticketRole === "seller"}
                                onChange={() => setTicketRole("seller")}
                              />
                              Продавец
                            </label>
                          </div>
                          <div className="grid gap-2">
                            <label className="text-xs font-semibold text-neutral-600">Номер заказа</label>
                            <input
                              value={ticketOrderId}
                              onChange={(e) => setTicketOrderId(e.target.value)}
                              placeholder="Например RXD6QMP9"
                              className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 outline-none placeholder:text-neutral-400"
                            />
                          </div>
                          <div className="grid gap-2">
                            <label className="text-xs font-semibold text-neutral-600">Комментарий</label>
                            <textarea
                              value={ticketComment}
                              onChange={(e) => setTicketComment(e.target.value)}
                              rows={5}
                              className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 outline-none placeholder:text-neutral-400"
                              placeholder="Опишите проблему..."
                            />
                          </div>
                          <div className="flex items-center gap-3">
                            <button
                              onClick={async () => {
                                if (!ticketComment.trim() || !ticketTopic) {
                                  showToast("Заполните тему и комментарий.", "error");
                                  return;
                                }
                                if (ticketSubmitting) return;
                                setTicketSubmitting(true);
                                try {
                                  const res = await apiFetch<{ url?: string }>("/api/support/tickets", {
                                    method: "POST",
                                    headers: buildKeyHeader(),
                                    body: JSON.stringify({
                                      topic: ticketTopic,
                                      role: ticketRole,
                                      order_id: ticketOrderId.trim() || null,
                                      comment: ticketComment.trim(),
                                    }),
                                  });
                                  showToast("Заявка отправлена в поддержку.");
                                  setTicketComment("");
                                  setTicketOrderId("");
                                  setLastTicketUrl(res?.url || null);
                                } catch (error) {
                                  showToast((error as Error).message || "Не удалось отправить заявку.", "error");
                                } finally {
                                  setTicketSubmitting(false);
                                }
                              }}
                              disabled={ticketSubmitting}
                              className="rounded-lg bg-neutral-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-neutral-800 disabled:cursor-not-allowed disabled:bg-neutral-300"
                            >
                              {ticketSubmitting ? "Отправка..." : "Отправить"}
                            </button>
                            <button
                              onClick={async () => {
                                if (ticketAIDrafting) return;
                                setTicketAIDrafting(true);
                                try {
                                  const res = await apiFetch<{ text: string }>("/api/support/tickets/compose", {
                                    method: "POST",
                                    headers: buildKeyHeader(),
                                    body: JSON.stringify({
                                      topic: ticketTopic,
                                      role: ticketRole,
                                      order_id: ticketOrderId.trim() || null,
                                      comment: ticketComment.trim() || null,
                                    }),
                                  });
                                  setTicketComment(res?.text || ticketComment);
                                  setTicketAIAnalysis(res?.analysis || null);
                                  showToast("AI-сообщение обновлено.");
                                } catch (error) {
                                  showToast((error as Error).message || "Не удалось сгенерировать текст.", "error");
                                } finally {
                                  setTicketAIDrafting(false);
                                }
                              }}
                              disabled={ticketAIDrafting}
                              className="rounded-lg border border-neutral-200 bg-white px-4 py-2 text-sm font-semibold text-neutral-700 transition hover:bg-neutral-100 disabled:cursor-not-allowed disabled:text-neutral-400"
                            >
                              {ticketAIDrafting ? "AI..." : "AI текст"}
                            </button>
                            <span className="text-xs text-neutral-500">Используется выбранное workspace.</span>
                          </div>
                          {lastTicketUrl && (
                              <div className="text-xs text-neutral-600">
                                Последняя заявка:{" "}
                                <a
                                  className="text-blue-600 underline"
                                  href={lastTicketUrl.startsWith("http") ? lastTicketUrl : `https://support.funpay.com${lastTicketUrl}`}
                                  target="_blank"
                                  rel="noreferrer"
                                >
                                  {lastTicketUrl}
                                </a>
                              </div>
                            )}
                            {ticketAIAnalysis && (
                              <div className="mt-3 rounded-lg border border-neutral-200 bg-neutral-50 p-3 text-xs text-neutral-700">
                                <div className="mb-1 text-[11px] font-semibold uppercase text-neutral-500">AI Анализ</div>
                              <div className="space-y-1">
                                {ticketAIAnalysis.order_id && (
                                  <div><span className="font-semibold">Order:</span> {ticketAIAnalysis.order_id}</div>
                                )}
                                {ticketAIAnalysis.buyer && (
                                  <div><span className="font-semibold">Buyer:</span> {ticketAIAnalysis.buyer}</div>
                                )}
                                {ticketAIAnalysis.lot_number !== undefined && ticketAIAnalysis.lot_number !== null && (
                                  <div><span className="font-semibold">Lot:</span> {ticketAIAnalysis.lot_number}</div>
                                )}
                                <div><span className="font-semibold">Topic:</span> {ticketAIAnalysis.topic}</div>
                                <div><span className="font-semibold">Role:</span> {ticketAIAnalysis.role}</div>
                                {ticketAIAnalysis.ai_dispute && (
                                  <div className="pt-1">
                                    <span
                                      className={`inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide ${
                                        ticketAIAnalysis.ai_dispute.label === "dispute"
                                          ? "bg-rose-100 text-rose-700"
                                          : ticketAIAnalysis.ai_dispute.label === "clear"
                                            ? "bg-emerald-100 text-emerald-700"
                                            : "bg-neutral-200 text-neutral-700"
                                      }`}
                                    >
                                      AI: {ticketAIAnalysis.ai_dispute.label || "unknown"}
                                    </span>
                                    {ticketAIAnalysis.ai_dispute.reason && (
                                      <div className="mt-1 text-[11px] text-neutral-600 whitespace-pre-line">
                                        {ticketAIAnalysis.ai_dispute.reason}
                                      </div>
                                    )}
                                  </div>
                                )}
                                {!ticketAIAnalysis.ai_dispute?.reason && ticketAIAnalysis.base_comment && (
                                  <div className="text-neutral-600">
                                    <span className="font-semibold">Base comment:</span> {ticketAIAnalysis.base_comment}
                                  </div>
                                )}
                                {ticketAIAnalysis.chat_messages && Array.isArray(ticketAIAnalysis.chat_messages) && (
                                  <div className="pt-2">
                                    <div className="text-[11px] font-semibold uppercase text-neutral-500">Chat excerpt used</div>
                                    <div className="mt-1 space-y-1 rounded-lg bg-white p-2">
                                      {ticketAIAnalysis.chat_messages.slice(0, 8).map((m: any, midx: number) => (
                                        <div key={midx} className="flex gap-2">
                                          <span className="min-w-[56px] text-[11px] font-semibold uppercase text-neutral-500">
                                            {m.role || "MSG"}
                                          </span>
                                          <span className="text-neutral-800">{m.message}</span>
                                        </div>
                                      ))}
                                    </div>
                                  </div>
                                )}
                              </div>
                            </div>
                          )}
                        </div>
                      </div>
                      <div className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm shadow-neutral-200/70">
                        <div className="mb-4 flex items-center justify-between">
                          <div>
                            <h4 className="text-base font-semibold text-neutral-900">Ticket history</h4>
                            <p className="text-xs text-neutral-500">Последние локальные отправки.</p>
                          </div>
                          <div className="flex items-center gap-2">
                            <button
                              onClick={() => loadTicketHistory(true)}
                              className="rounded-lg border border-neutral-200 bg-white px-3 py-2 text-xs font-semibold text-neutral-700 transition hover:bg-neutral-100"
                            >
                              Refresh
                            </button>
                          </div>
                        </div>
                        {ticketHistoryLoading ? (
                          <div className="py-3 text-sm text-neutral-500">Loading history...</div>
                        ) : ticketHistory.length === 0 ? (
                          <div className="py-3 text-sm text-neutral-500">No tickets yet.</div>
                        ) : (
                          <div className="space-y-2">
                            {ticketHistory.slice(0, 50).map((item, idx) => (
                              <div
                                key={`${item.id}-${idx}`}
                                className="flex flex-wrap items-center gap-3 rounded-xl border border-neutral-100 bg-neutral-50 px-3 py-2"
                              >
                                <span className="text-sm font-semibold text-neutral-900">
                                  {item.topic || "ticket"} · {item.role || "role"}
                                </span>
                                {item.order_id && (
                                  <span className="text-xs text-neutral-600">• Order {item.order_id}</span>
                                )}
                                {item.status && <span className="text-xs text-neutral-500">• {item.status}</span>}
                                {item.source && (
                                  <span className="text-[11px] rounded-full bg-neutral-200 px-2 py-0.5 font-semibold text-neutral-700">
                                    {item.source}
                                  </span>
                                )}
                                {item.ticket_url && (
                                  <a
                                    className="text-xs font-semibold text-blue-600 underline"
                                    target="_blank"
                                    rel="noreferrer"
                                    href={
                                      String(item.ticket_url).startswith("http")
                                        ? item.ticket_url
                                        : `https://support.funpay.com${item.ticket_url}`
                                    }
                                  >
                                    open
                                  </a>
                                )}
                                {item.comment && (
                                  <div className="w-full text-xs text-neutral-600">
                                    <span className="font-semibold text-neutral-700">Comment:</span>{" "}
                                    <span>{String(item.comment).slice(0, 220)}{String(item.comment).length > 220 ? "…" : ""}</span>
                                  </div>
                                )}
                                <span className="ml-auto text-[11px] text-neutral-500">
                                  {item.created_at ? formatDate(item.created_at) : ""}
                                </span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </motion.div>
                  ) : activeNav === "chats" ? (
                    activeKeyId === "all" ? (
                      <div className="mt-8 rounded-2xl border border-dashed border-neutral-200 bg-neutral-50 p-6">
                        <div className="text-sm font-semibold text-neutral-900">
                          Select a workspace to open chats
                        </div>
                        <p className="mt-2 text-xs text-neutral-500">
                          Chats are tied to a specific golden key. Choose a workspace from the top bar to see its chat
                          list and history.
                        </p>
                      </div>
                    ) : (
                    <motion.div
                      key="chats"
                      initial={{ opacity: 0, y: 12 }}
                      animate={{ opacity: 1, y: 0, transition: { duration: 0.6, ease: EASE } }}
                      className="mt-8 grid gap-6 lg:grid-cols-5"
                    >
                      <div className="lg:col-span-2 rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm shadow-neutral-200/70 max-h-[calc(100vh-220px)] flex flex-col">
                        <div className="mb-4 flex items-center justify-between gap-3">
                          <h3 className="text-lg font-semibold text-neutral-900">Chats</h3>
                          <button
                            onClick={() => {
                              setSelectedChat(null);
                              loadChats(true);
                            }}
                            className="rounded-lg border border-neutral-200 bg-neutral-50 px-3 py-2 text-xs text-neutral-600"
                          >
                            Refresh
                          </button>
                        </div>
                        <div className="mb-3 flex items-center gap-3">
                          <input
                            type="search"
                            placeholder="Search chats"
                            className="w-full rounded-lg border border-neutral-200 bg-neutral-50 px-3 py-2 text-sm text-neutral-700 outline-none placeholder:text-neutral-400"
                            onChange={(e) => {
                              const q = e.target.value.toLowerCase();
                              setChats((prev: any[]) =>
                                prev.map((c) => ({
                                  ...c,
                                  _hidden:
                                    !c.name.toLowerCase().includes(q) &&
                                    !(c.last || "").toLowerCase().includes(q),
                                }))
                              );
                            }}
                          />
                        </div>
                        <div className="space-y-2 overflow-y-auto pr-1 flex-1 min-h-0">
                          {chatListLoading && (
                            <div className="rounded-xl border border-dashed border-neutral-200 bg-neutral-50 px-3 py-6 text-center text-sm text-neutral-500">
                              Loading chats...
                            </div>
                          )}
                          {!chatListLoading &&
                            chats
                              .filter((c: any) => !c._hidden)
                              .map((chat) => (
                                <button
                                  key={chat.id}
                                  onClick={() => {
                                    setSelectedChat(chat.id);
                                    clearAdminCall(chat.id);
                                  }}
                                  className={`flex w-full items-start justify-between gap-3 rounded-xl border px-3 py-3 text-left text-sm transition ${
                                    selectedChat === chat.id
                                      ? "border-neutral-300 bg-neutral-50"
                                      : `border-neutral-100 bg-white hover:border-neutral-200 ${
                                          chat.adminCalls ? "ring-1 ring-rose-200" : ""
                                        }`
                                  }`}
                                >
                                  <div className="flex min-w-0 items-start gap-3">
                                    <div
                                      className="flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-full text-xs font-semibold uppercase text-white"
                                      style={avatarStyle(chat.name)}
                                    >
                                      {chat.avatarUrl ? (
                                        <img
                                          src={chat.avatarUrl}
                                          alt={chat.name || "Avatar"}
                                          className="h-full w-full object-cover"
                                          loading="lazy"
                                        />
                                      ) : (
                                        getInitials(chat.name)
                                      )}
                                    </div>
                                    <div className="min-w-0">
                                      <div className="flex items-center gap-2">
                                        <span className="truncate font-semibold text-neutral-900">{chat.name}</span>
                                        {chat.unread && (
                                          <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-600">
                                            new
                                          </span>
                                        )}
                                        {chat.adminCalls ? (
                                          <span className="rounded-full bg-rose-100 px-2 py-0.5 text-[11px] font-semibold text-rose-600">
                                            {chat.adminCalls}
                                          </span>
                                        ) : null}
                                      </div>
                                      <p className="truncate text-xs text-neutral-500">
                                        {chat.last || "No messages yet"}
                                      </p>
                                    </div>
                                  </div>
                                  <span className="shrink-0 text-[11px] text-neutral-400">{chat.time || ""}</span>
                                </button>
                              ))}
                          {!chatListLoading && chats.filter((c: any) => !c._hidden).length === 0 && (
                            <div className="rounded-xl border border-dashed border-neutral-200 bg-neutral-50 px-3 py-6 text-center text-sm text-neutral-500">
                              No chats found.
                            </div>
                          )}
                        </div>
                      </div>
                      <div className="lg:col-span-3 flex min-h-[520px] max-h-[calc(100vh-220px)] flex-col rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm shadow-neutral-200/70">
                        <div className="mb-3 flex items-center justify-between">
                          <div>
                            <h3 className="text-lg font-semibold text-neutral-900">Conversation</h3>
                            <p className="text-sm text-neutral-500">
                              {selectedChat ? `Chat ID: ${selectedChat}` : "Select a chat to view messages."}
                            </p>
                          </div>
                        </div>
                        <div className="flex flex-1 flex-col gap-3 rounded-xl border border-neutral-100 bg-neutral-50 p-4 min-h-0">
                            <div
                              ref={chatScrollRef}
                              className="flex-1 space-y-3 overflow-y-auto pr-2 min-h-0"
                            >
                            {chatLoading && (
                              <div className="rounded-lg border border-dashed border-neutral-200 bg-white px-3 py-4 text-center text-sm text-neutral-500">
                                Loading messages...
                              </div>
                            )}
                            {!chatLoading && chatMessages.length === 0 && (
                              <div className="rounded-lg border border-dashed border-neutral-200 bg-white px-3 py-4 text-center text-sm text-neutral-500">
                                No messages.
                              </div>
                            )}
                            {!chatLoading &&
                              chatMessages.map((m) => (
                                <div
                                  key={m.id}
                                  className={`max-w-[86%] rounded-2xl px-4 py-3 shadow-sm ${
                                    m.byBot ? "ml-auto bg-neutral-900 text-white" : "bg-white text-neutral-900"
                                  } ${m.adminCall && !m.byBot ? "border border-amber-300 bg-amber-50" : ""}`}
                                >
                                  <div className="mb-1 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-neutral-500">
                                    <span className={m.byBot ? "text-neutral-200" : "text-neutral-500"}>{m.author || "User"}</span>
                                    <span className={m.byBot ? "text-neutral-300" : "text-neutral-400"}>{m.sentAt || ""}</span>
                                  </div>
                                  <div className="text-sm leading-relaxed">{m.text || "(empty)"}</div>
                                </div>
                              ))}
                          </div>
                          <form
                            onSubmit={(e) => {
                              e.preventDefault();
                              sendChatMessage();
                            }}
                            className="mt-auto flex items-center gap-3 rounded-lg border border-neutral-200 bg-white px-3 py-2 shadow-sm"
                          >
                            <textarea
                              value={chatInput}
                              onChange={(e) => setChatInput(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === "Enter" && !e.shiftKey) {
                                  e.preventDefault();
                                  if (selectedChat !== null && selectedChat !== undefined && chatInput.trim()) {
                                    sendChatMessage();
                                  }
                                }
                              }}
                              placeholder={selectedChat !== null && selectedChat !== undefined ? "Type a message..." : "Select a chat to start typing"}
                              disabled={selectedChat === null || selectedChat === undefined}
                              rows={2}
                              className="w-full min-h-[44px] max-h-[120px] resize-none rounded-md border border-neutral-200 bg-neutral-50 px-3 py-2 text-sm text-neutral-800 outline-none disabled:cursor-not-allowed disabled:bg-neutral-100"
                            />
                            <button
                              type="submit"
                              disabled={(selectedChat === null || selectedChat === undefined) || !chatInput.trim()}
                              className="h-[44px] rounded-lg bg-neutral-900 px-4 text-sm font-semibold text-white transition hover:bg-neutral-800 disabled:cursor-not-allowed disabled:bg-neutral-300"
                            >
                              Send
                            </button>
                          </form>
                        </div>
                      </div>

                    </motion.div>
                    )
                  ) : activeNav === "profile" ? (
                    <motion.div
                      key="profile"
                      initial={{ opacity: 0, y: 12 }}
                      animate={{ opacity: 1, y: 0, transition: { duration: 0.6, ease: EASE } }}
                      className="mt-8"
                    >
                      <div className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm shadow-neutral-200/70">
                        <div className="flex flex-wrap items-center gap-4">
                          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-neutral-900 text-xl font-semibold text-white">
                            {profileInitial}
                          </div>
                          <div>
                            <h3 className="text-lg font-semibold text-neutral-900">Profile</h3>
                            <p className="text-sm text-neutral-500">{profileName || "User"}</p>
                          </div>
                        </div>
                        <div className="mt-6 flex flex-wrap gap-3">
                          <button
                            onClick={handleLogout}
                            className="rounded-lg bg-neutral-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-neutral-800"
                          >
                            Log out
                          </button>
                        </div>
                      </div>

                    </motion.div>
                  ) : activeNav === "settings" ? (
                    <motion.div
                      key="settings"
                      initial={{ opacity: 0, y: 12 }}
                      animate={{ opacity: 1, y: 0, transition: { duration: 0.6, ease: EASE } }}
                      className="mt-8 flex flex-col gap-6"
                    >
                      <div className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm shadow-neutral-200/70">
                        <div className="mb-3">
                          <h3 className="text-lg font-semibold text-neutral-900">Funpay Profile Settings</h3>
                        </div>
                        <div className="space-y-3 max-h-[640px] overflow-y-auto pr-1">
                          <ToggleRow
                            label="Auto Tickets"
                            enabled={!!autoTickets}
                            onChange={(val) => handleToggleAutoTickets(val)}
                            disabled={autoTickets === null}
                          />
                          <ToggleRow label="Auto Online" enabled={autoOnline} onChange={setAutoOnline} />
                        </div>
                      </div>
                      <div className="space-y-4">
                        <div className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm shadow-neutral-200/70 max-h-[calc(100vh-260px)] overflow-y-auto">
                          <div className="mb-3">
                            <h3 className="text-lg font-semibold text-neutral-900">UI Settings</h3>
                          </div>
                          <div className="flex h-16 w-full items-center justify-between rounded-xl border border-neutral-200 bg-white px-4 shadow-sm">
                            <div className="text-sm font-semibold text-neutral-900">Mode</div>
                            <div className="flex rounded-full border border-neutral-200 bg-neutral-50 p-1 text-sm font-semibold text-neutral-600">
                              <button
                                type="button"
                                onClick={() => setUiMode("light")}
                                className={`rounded-full px-3 py-1 transition ${
                                  uiMode === "light" ? "bg-neutral-900 text-white shadow" : "hover:bg-white"
                                }`}
                              >
                                Light
                              </button>
                              <button
                                type="button"
                                onClick={() => setUiMode("dark")}
                                className={`rounded-full px-3 py-1 transition ${
                                  uiMode === "dark" ? "bg-neutral-900 text-white shadow" : "hover:bg-white"
                                }`}
                              >
                                Dark
                              </button>
                            </div>
                          </div>
                        </div>
                        <div className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm shadow-neutral-200/70 max-h-[calc(100vh-260px)] flex flex-col">
                          <div className="mb-4">
                            <h3 className="text-lg font-semibold text-neutral-900">Workspaces</h3>
                            <p className="text-xs text-neutral-500">
                              Connect multiple FunPay golden keys and switch between them without leaving the dashboard.
                            </p>
                          </div>
                          <div className="rounded-xl border border-neutral-200 bg-neutral-50 p-4">
                            <div className="mb-3 text-sm font-semibold text-neutral-800">Add workspace</div>
                            <div className="grid gap-3 md:grid-cols-2">
                              <input
                                value={newKeyLabel}
                                onChange={(e) => setNewKeyLabel(e.target.value)}
                                placeholder="Workspace name (e.g. Seller A)"
                                className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 outline-none placeholder:text-neutral-400"
                              />
                              <input
                                value={newKeyValue}
                                onChange={(e) => setNewKeyValue(e.target.value)}
                                placeholder="FunPay golden key"
                                type="password"
                                className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 outline-none placeholder:text-neutral-400"
                              />
                            </div>
                            <div className="grid gap-3">
                              <input
                                value={newKeyProxyUrl}
                                onChange={(e) => setNewKeyProxyUrl(e.target.value)}
                                placeholder="Proxy URL (e.g. socks5://host:port[:user:pass])"
                                className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 outline-none placeholder:text-neutral-400"
                              />
                              <div className="grid gap-3 md:grid-cols-2">
                                <input
                                  value={newKeyProxyUsername}
                                  onChange={(e) => setNewKeyProxyUsername(e.target.value)}
                                  placeholder="Proxy username (optional)"
                                  className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 outline-none placeholder:text-neutral-400"
                                />
                                <input
                                  value={newKeyProxyPassword}
                                  onChange={(e) => setNewKeyProxyPassword(e.target.value)}
                                  placeholder="Proxy password (optional)"
                                  type="password"
                                  className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 outline-none placeholder:text-neutral-400"
                                />
                              </div>
                              <p className="text-[11px] text-neutral-500">
                                Proxy is required for every workspace. FunPay traffic will be sent through this proxy.
                              </p>
                            </div>
                            <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
                              <label className="flex items-center gap-2 text-xs font-semibold text-neutral-600">
                                <input
                                  type="checkbox"
                                  checked={newKeyDefault}
                                  onChange={(e) => setNewKeyDefault(e.target.checked)}
                                  className="h-4 w-4 rounded border-neutral-300 text-neutral-900"
                                />
                                Make default
                              </label>
                              <button
                                onClick={handleCreateKey}
                                disabled={keyActionBusy || !newKeyValue.trim() || !newKeyProxyUrl.trim()}
                                className="rounded-lg bg-neutral-900 px-4 py-2 text-xs font-semibold text-white transition hover:bg-neutral-800 disabled:cursor-not-allowed disabled:bg-neutral-300"
                              >
                                Add workspace
                              </button>
                            </div>
                          </div>
                          <div className="mt-4 space-y-3">
                            {keysLoading ? (
                              <div className="rounded-xl border border-dashed border-neutral-200 bg-neutral-50 px-4 py-6 text-center text-sm text-neutral-500">
                                Loading workspaces...
                              </div>
                            ) : userKeys.length ? (
                              userKeys.map((item) => {
                                const isEditing = editingKeyId === item.id;
                                return (
                                  <div
                                    key={item.id}
                                    className="rounded-xl border border-neutral-200 bg-white p-4"
                                  >
                                    <div className="flex flex-wrap items-start justify-between gap-3">
                                      <div>
                                        <div className="text-sm font-semibold text-neutral-900">{item.label}</div>
                                        <div className="text-xs text-neutral-500">
                                          {item.is_default ? "Default workspace" : "Workspace"}
                                          {item.created_at ? ` · Added ${new Date(item.created_at).toLocaleDateString()}` : ""}
                                        </div>
                                      </div>
                                      <div className="flex flex-wrap items-center gap-2">
                                        {!item.is_default && (
                                          <button
                                            onClick={() => handleSetDefaultKey(item.id)}
                                            className="rounded-lg border border-neutral-200 px-3 py-1 text-xs font-semibold text-neutral-600"
                                          >
                                            Set default
                                          </button>
                                        )}
                                        <button
                                          onClick={() => (isEditing ? cancelEditKey() : startEditKey(item))}
                                          className="rounded-lg border border-neutral-200 px-3 py-1 text-xs font-semibold text-neutral-600"
                                        >
                                          {isEditing ? "Close" : "Edit"}
                                        </button>
                                        <button
                                          onClick={() => handleDeleteKey(item.id)}
                                          className="rounded-lg border border-rose-200 px-3 py-1 text-xs font-semibold text-rose-600"
                                        >
                                          Remove
                                        </button>
                                      </div>
                                    </div>
                                    {isEditing && (
                                      <div className="mt-3 space-y-3">
                                        <div className="grid gap-3 md:grid-cols-2">
                                          <input
                                            value={editKeyLabel}
                                            onChange={(e) => setEditKeyLabel(e.target.value)}
                                            placeholder="Workspace name"
                                            className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 outline-none"
                                          />
                                          <input
                                            value={editKeyValue}
                                            onChange={(e) => setEditKeyValue(e.target.value)}
                                            placeholder="New golden key (optional)"
                                            type="password"
                                            className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 outline-none"
                                          />
                                        </div>
                                        <div className="grid gap-3">
                                          <input
                                            value={editKeyProxyUrl}
                                            onChange={(e) => setEditKeyProxyUrl(e.target.value)}
                                            placeholder="Proxy URL (socks5://host:port[:user:pass])"
                                            className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 outline-none"
                                          />
                                          <div className="grid gap-3 md:grid-cols-2">
                                            <input
                                              value={editKeyProxyUsername}
                                              onChange={(e) => setEditKeyProxyUsername(e.target.value)}
                                              placeholder="Proxy username"
                                              className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 outline-none"
                                            />
                                            <input
                                              value={editKeyProxyPassword}
                                              onChange={(e) => setEditKeyProxyPassword(e.target.value)}
                                              placeholder="Proxy password"
                                              type="password"
                                              className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 outline-none"
                                            />
                                          </div>
                                          <p className="text-[11px] text-neutral-500">
                                            Proxy must stay valid; bots refresh sessions through it.
                                          </p>
                                        </div>
                                        <div className="flex flex-wrap items-center gap-2">
                                          <button
                                            onClick={handleSaveKeyEdit}
                                            className="rounded-lg bg-neutral-900 px-3 py-2 text-xs font-semibold text-white"
                                          >
                                            Save changes
                                          </button>
                                          <button
                                            onClick={cancelEditKey}
                                            className="rounded-lg border border-neutral-200 px-3 py-2 text-xs font-semibold text-neutral-600"
                                          >
                                            Cancel
                                          </button>
                                        </div>
                                      </div>
                                    )}
                                  </div>
                                );
                              })
                            ) : (
                              <div className="rounded-xl border border-dashed border-neutral-200 bg-neutral-50 px-4 py-6 text-center text-sm text-neutral-500">
                                No workspaces connected yet.
                              </div>
                            )}
                          </div>
                        </div>
                      </div>

                      <div className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm shadow-neutral-200/70">
                        <div className="flex flex-wrap items-center justify-between gap-3">
                          <div>
                            <h3 className="text-lg font-semibold text-neutral-900">Auto Raise</h3>
                            <p className="text-sm text-neutral-500">Pick categories and we'll bump them on cooldown.</p>
                          </div>
                          <div className="flex items-center gap-2">
                            <span className="text-xs text-neutral-500">Enable</span>
                            <ToggleRow
                              label=""
                              enabled={!!autoRaise}
                              onChange={(val) => handleToggleAutoRaise(val)}
                              disabled={autoRaise === null}
                            />
                          </div>
                        </div>
                        <div className="mt-4 flex flex-wrap items-center gap-3 text-[11px] text-neutral-600">
                          <button
                            type="button"
                            onClick={reloadCategories}
                            disabled={categoryLoading}
                            className="rounded border border-neutral-200 px-3 py-2 text-xs font-semibold text-neutral-700 hover:bg-neutral-100 disabled:opacity-50"
                          >
                            {categoryLoading ? "Reloading..." : "Reload from FunPay"}
                          </button>
                          {categoryMeta.ts && (
                            <span className="text-neutral-500">
                              Loaded {categoryMeta.count || 0} · {new Date(categoryMeta.ts).toLocaleTimeString()}
                            </span>
                          )}
                        </div>
                        <div className="mt-3 grid gap-2 md:grid-cols-[2fr_1fr]">
                          <input
                            value={categorySearch}
                            onChange={(e) => setCategorySearch(e.target.value)}
                            className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 outline-none"
                            placeholder="Search by game/category..."
                          />
                          <input
                            value={categoryIdSearch}
                            onChange={(e) => setCategoryIdSearch(e.target.value)}
                            className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 outline-none"
                            placeholder="Search by ID..."
                          />
                        </div>
                        <div className="mt-3 rounded-xl border border-neutral-200 bg-neutral-50 px-4 py-3 text-[12px] text-neutral-600">
                          Auto-raise loops roughly every 2h (longer if FunPay cooldowns apply). Leave all unchecked to raise everything.
                        </div>
                        {groupedCategories.length ? (
                          <div className="mt-4 rounded-2xl border border-neutral-200 bg-white shadow-[0_1px_3px_rgba(0,0,0,0.06)]">
                            <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-[12px] text-neutral-600 border-b border-neutral-100">
                              <div className="flex items-center gap-2">
                                <span className="font-semibold text-neutral-800">
                                  {groupedCategories.length} categories
                                </span>
                                <span className="text-neutral-400">·</span>
                                <span>
                                  Selected{" "}
                                  {
                                    autoRaiseCategories
                                      .split(",")
                                      .map((s) => s.trim())
                                      .filter(Boolean).length
                                  }
                                </span>
                              </div>
                              <div className="flex gap-2">
                                <button
                                  type="button"
                                  onClick={() => {
                                    const selected = new Set(
                                      autoRaiseCategories
                                        .split(",")
                                        .map((s) => s.trim())
                                        .filter(Boolean)
                                    );
                                    groupedCategories.forEach((c) => selected.add(String(c.id)));
                                    setAutoRaiseCategories(Array.from(selected).join(","));
                                  }}
                                  className="rounded border border-neutral-200 px-3 py-2 text-xs font-semibold text-neutral-700 hover:bg-neutral-50"
                                >
                                  Select visible
                                </button>
                                <button
                                  type="button"
                                  onClick={() => setAutoRaiseCategories("")}
                                  className="rounded border border-neutral-200 px-3 py-2 text-xs font-semibold text-neutral-600 hover:bg-neutral-50"
                                >
                                  Clear
                                </button>
                              </div>
                            </div>
                            <div className="grid grid-cols-[90px_240px_1fr] items-center bg-neutral-50 px-4 py-2 text-[11px] font-semibold text-neutral-600 uppercase tracking-[0.02em]">
                              <span>ID</span>
                              <span>Game</span>
                              <span>Category</span>
                            </div>
                            <div className="max-h-[560px] overflow-y-auto divide-y divide-neutral-100">
                              {groupedCategories.map((c) => {
                                const selectedIds = autoRaiseCategories
                                  .split(",")
                                  .map((s) => s.trim())
                                  .filter(Boolean);
                                const isSelected = selectedIds.includes(String(c.id));
                                const label = c.category || c.name;
                                const gameLabel = c.game || "Other";
                                return (
                                  <label
                                    key={c.id}
                                    className="grid grid-cols-[90px_240px_1fr] items-center gap-2 px-4 py-2 text-sm text-neutral-800 hover:bg-neutral-50"
                                  >
                                    <div className="flex items-center gap-2">
                                      <input
                                        type="checkbox"
                                        checked={isSelected}
                                        onChange={(e) => {
                                          const next = new Set(selectedIds);
                                          if (e.target.checked) next.add(String(c.id));
                                          else next.delete(String(c.id));
                                          setAutoRaiseCategories(Array.from(next).join(","));
                                        }}
                                      />
                                      <span className="font-mono text-xs text-neutral-500">{c.id}</span>
                                    </div>
                                    <span className="truncate text-neutral-600">{gameLabel}</span>
                                    <span className="truncate">{label}</span>
                                  </label>
                                );
                              })}
                            </div>
                          </div>
                        ) : (
                          <div className="mt-4 rounded-lg border border-neutral-200 bg-white px-3 py-2 text-neutral-500 text-sm">
                            No categories loaded.
                          </div>
                        )}
                      </div>
                    </motion.div>
                  ) : activeNav === "add" ? (
                    <motion.div
                      key="add"
                      initial={{ opacity: 0, y: 12 }}
                      animate={{ opacity: 1, y: 0, transition: { duration: 0.6, ease: EASE } }}
                      className="mt-8"
                    >
                      <div className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm shadow-neutral-200/70">
                        <div className="mb-4 flex items-center justify-between">
                          <div>
                            <h3 className="text-lg font-semibold text-neutral-900">Add Account</h3>
                            <p className="text-sm text-neutral-500">Quickly onboard a new Steam account.</p>
                          </div>
                          <div className="text-xs rounded-full bg-neutral-100 px-3 py-1 font-semibold text-neutral-600">
                            Secure fields stay local
                          </div>
                        </div>
                        <AddAccountForm
                          onToast={(msg, err) => showToast(msg, err ? "error" : "success")}
                          onSubmit={handleCreateAccount}
                          keys={userKeys}
                          defaultKeyId={activeKeyId}
                        />
                        {submittingAccount && (
                          <div className="mt-3 text-sm text-neutral-500">Creating account...</div>
                        )}
                      </div>
                    </motion.div>
                  ) : activeNav === "rentals" ? (
                    <motion.div
                      key="rentals"
                      initial={{ opacity: 0, y: 12 }}
                      animate={{ opacity: 1, y: 0, transition: { duration: 0.6, ease: EASE } }}
                      className="mt-8 space-y-4"
                    >
                      <div className="flex flex-wrap items-center gap-3">
                        <div className="rounded-full bg-neutral-900 px-4 py-2 text-sm font-semibold text-white">
                          {rentalsTable.length} active rentals
                        </div>
                        <div className="text-sm text-neutral-500">Updated live every second</div>
                      </div>
                      <div className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm shadow-neutral-200/70">
                        <div className="overflow-x-auto">
                          <div className="min-w-[1100px]">
                            <div
                              className="grid gap-3 px-6 text-xs font-semibold text-neutral-500"
                              style={{ gridTemplateColumns: RENTALS_GRID }}
                            >
                              <span>ID</span>
                              <span>Account</span>
                              <span>Buyer</span>
                              <span>Started</span>
                              <span>Time Left</span>
                              <span>Match Time</span>
                              <span>Hero</span>
                              <span>Status</span>
                            </div>
                            <div className="mt-3 space-y-3 overflow-y-auto overflow-x-hidden pr-1" style={{ maxHeight: "640px" }}>
                            {rentalsTable.map((r, idx) => {
                              const presence = r.presence ?? null;
                              const timer = getMatchTimeLabel(presence);
                              const frozen = !!r.rentalFrozen;
                            const presenceLabel = frozen
                              ? "Frozen"
                              : presence?.in_match
                                ? "In match"
                                : presence?.in_game
                                  ? "In game"
                                  : "Offline";
                            const pill = statusPill(presenceLabel);
                            const adminCalls = Number(r.adminCalls || 0);
                            const hasAdminCall = adminCalls > 0;
                            const timeLeft =
                              r.durationSec != null && r.startedAt != null
                                ? formatDuration(
                                    r.durationSec,
                                    r.startedAt,
                                    now,
                                    frozen ? r.rentalFrozenAt ?? null : null
                                  )
                                : "-";
                            const rowId = r.id ?? idx;
                            const isSelected =
                              selectedRentalId !== null && String(selectedRentalId) === String(rowId);
                            return (
                              <motion.div
                                key={rowId}
                                role="button"
                                tabIndex={0}
                                onKeyDown={(event) => {
                                  if (event.key === "Enter" || event.key === " ") {
                                    event.preventDefault();
                                    const nextSelected =
                                      selectedRentalId !== null && String(selectedRentalId) === String(rowId)
                                        ? null
                                        : rowId;
                                    setSelectedRentalId(nextSelected);
                                    if (nextSelected !== null) {
                                      setSelectedAccountId(rowId);
                                    }
                                  }
                                }}
                                onClick={() => {
                                  const nextSelected =
                                    selectedRentalId !== null && String(selectedRentalId) === String(rowId)
                                      ? null
                                      : rowId;
                                  setSelectedRentalId(nextSelected);
                                  if (nextSelected !== null) {
                                    setSelectedAccountId(rowId);
                                  }
                                }}
                                initial={{ opacity: 0, y: 10 }}
                                animate={{ opacity: 1, y: 0, transition: { duration: 0.25, delay: idx * 0.03, ease: EASE } }}
                                className={`grid items-center gap-3 rounded-xl border px-6 py-4 text-sm shadow-[0_4px_18px_-14px_rgba(0,0,0,0.18)] transition ${
                                  isSelected
                                    ? "border-neutral-900/20 bg-white ring-2 ring-neutral-900/10"
                                    : `border-neutral-100 bg-neutral-50 hover:border-neutral-200 ${
                                        hasAdminCall ? "ring-1 ring-rose-200 bg-rose-50/60" : ""
                                      }`
                                } cursor-pointer`}
                                style={{ gridTemplateColumns: RENTALS_GRID }}
                              >
                                <span className="min-w-0 truncate font-semibold text-neutral-900">{rowId}</span>
                                <div className="min-w-0">
                                  <div className="truncate text-neutral-800">{r.accountName || ""}</div>
                                  <span className="mt-1 inline-flex w-fit rounded-full bg-neutral-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-neutral-600">
                                    {resolveKeyLabel(r.keyId)}
                                  </span>
                                </div>
                                {r.buyer ? (
                                  r.chatUrl ? (
                                    <a
                                      href={r.chatUrl}
                                      target="_blank"
                                      rel="noreferrer"
                                      className="min-w-0 truncate font-semibold text-neutral-800 hover:underline"
                                      onClick={(event) => event.stopPropagation()}
                                    >
                                      {r.buyer}
                                    </a>
                                  ) : (
                                    <span className="min-w-0 truncate text-neutral-700">{r.buyer}</span>
                                  )
                                ) : (
                                  <span className="min-w-0 truncate text-neutral-400">-</span>
                                )}
                                <span className="min-w-0 truncate text-neutral-600">{formatStartTime(r.startedAt) || "-"}</span>
                                <span className="min-w-0 truncate font-mono text-neutral-900">{timeLeft}</span>
                                <span className="min-w-0 truncate font-mono text-neutral-900">{timer}</span>
                                <span className="min-w-0 truncate text-neutral-700">{presence?.hero_name || r.hero || ""}</span>
                                <div className="flex items-center gap-2">
                                  {hasAdminCall && (
                                    <span className="rounded-full bg-rose-100 px-2 py-1 text-[11px] font-semibold text-rose-600">
                                      Admin call {adminCalls}
                                    </span>
                                  )}
                                  {r.steamId ? (
                                    <a
                                      href={`${PRESENCE_BASE}/${r.steamId}`}
                                      target="_blank"
                                      rel="noreferrer"
                                      className={`inline-flex w-fit justify-self-start rounded-full px-3 py-1 text-xs font-semibold ${pill.className}`}
                                      onClick={(event) => event.stopPropagation()}
                                    >
                                      {presenceLabel}
                                    </a>
                                  ) : (
                                    <span className={`inline-flex w-fit justify-self-start rounded-full px-3 py-1 text-xs font-semibold ${pill.className}`}>
                                      {presenceLabel}
                                    </span>
                                  )}
                                </div>
                              </motion.div>
                            );
                          })}
                          {rentalsTable.length === 0 && (
                            <div
                              className={`rounded-xl border border-dashed border-neutral-200 bg-neutral-50 px-4 py-6 text-center text-sm text-neutral-500 ${
                                authState !== "guest" && !overviewHydrated ? "animate-pulse" : ""
                              }`}
                            >
                              {authState !== "guest" && !overviewHydrated ? "Loading rentals..." : "No active rentals yet."}
                            </div>
                          )}
                            </div>
                          </div>
                        </div>
                      </div>
                    </motion.div>
                  ) : activeNav === "blacklist" ? (
                    <motion.div
                      key="blacklist"
                      initial={{ opacity: 0, y: 12 }}
                      animate={{ opacity: 1, y: 0, transition: { duration: 0.6, ease: EASE } }}
                      className="mt-8 space-y-6"
                    >
                      <div className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm shadow-neutral-200/70">
                        <div className="mb-5 flex flex-wrap items-center justify-between gap-4">
                          <div>
                            <h3 className="text-lg font-semibold text-neutral-900">Blacklist</h3>
                            <p className="text-sm text-neutral-500">
                              Block buyers from renting and auto-reply with an admin notice.
                            </p>
                          </div>
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="text-xs rounded-full bg-neutral-100 px-3 py-1 font-semibold text-neutral-600">
                              {blacklistEntries.length} blocked
                            </span>
                              <button
                                onClick={() => loadBlacklist(blacklistQuery, true)}
                                className="rounded-lg border border-neutral-200 bg-neutral-50 px-3 py-2 text-xs text-neutral-600"
                              >
                                Refresh
                              </button>
                          </div>
                        </div>
                        <div className="grid gap-4 lg:grid-cols-[1.15fr_1fr]">
                          <div className="rounded-xl border border-neutral-200 bg-neutral-50 p-4">
                            <div className="mb-2 text-sm font-semibold text-neutral-800">Add to blacklist</div>
                            {activeKeyId === "all" && (
                              <div className="mb-3 rounded-lg border border-dashed border-neutral-200 bg-neutral-50 px-3 py-2 text-xs text-neutral-500">
                                Select a workspace to add or edit blacklist entries.
                              </div>
                            )}
                            <div className="space-y-3">
                              <div className="grid gap-3 md:grid-cols-[1fr_auto]">
                                <input
                                  value={blacklistOrderId}
                                  onChange={(e) => setBlacklistOrderId(e.target.value)}
                                  placeholder="Order ID (optional)"
                                  disabled={activeKeyId === "all" || blacklistResolving}
                                  className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 outline-none placeholder:text-neutral-400"
                                />
                                <button
                                  onClick={handleResolveBlacklistOrder}
                                  disabled={activeKeyId === "all" || blacklistResolving}
                                  className="rounded-lg border border-neutral-200 bg-white px-3 py-2 text-xs font-semibold text-neutral-700 transition hover:bg-neutral-100 disabled:cursor-not-allowed disabled:text-neutral-400"
                                >
                                  Find buyer
                                </button>
                              </div>
                              <input
                                value={blacklistOwner}
                                onChange={(e) => setBlacklistOwner(e.target.value)}
                                placeholder="Buyer username"
                                disabled={activeKeyId === "all"}
                                className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 outline-none placeholder:text-neutral-400"
                              />
                              <input
                                value={blacklistReason}
                                onChange={(e) => setBlacklistReason(e.target.value)}
                                placeholder="Reason (optional)"
                                disabled={activeKeyId === "all"}
                                className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 outline-none placeholder:text-neutral-400"
                              />
                              <button
                                onClick={handleAddBlacklist}
                                disabled={
                                  activeKeyId === "all" ||
                                  blacklistResolving ||
                                  (!blacklistOwner.trim() && !blacklistOrderId.trim())
                                }
                                className="w-full rounded-lg bg-neutral-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-neutral-800 disabled:cursor-not-allowed disabled:bg-neutral-300"
                              >
                                {blacklistResolving ? "Resolving..." : "Add user"}
                              </button>
                            </div>
                          </div>
                          <div className="rounded-xl border border-neutral-200 bg-neutral-50 p-4">
                            <div className="mb-2 text-sm font-semibold text-neutral-800">Manage</div>
                            <input
                              value={blacklistQuery}
                              onChange={(e) => setBlacklistQuery(e.target.value)}
                              placeholder="Search by buyer"
                              type="search"
                              disabled={activeKeyId === "all"}
                              className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 outline-none placeholder:text-neutral-400"
                            />
                            <div className="mt-3 flex flex-wrap gap-2">
                              <button
                                onClick={handleRemoveSelected}
                                disabled={activeKeyId === "all" || !blacklistSelected.length}
                                className="rounded-lg border border-neutral-200 bg-white px-3 py-2 text-xs font-semibold text-neutral-700 transition hover:bg-neutral-100 disabled:cursor-not-allowed disabled:text-neutral-400"
                              >
                                Unblacklist selected
                              </button>
                              <button
                                onClick={handleClearBlacklist}
                                disabled={activeKeyId === "all" || !blacklistEntries.length}
                                className="rounded-lg border border-neutral-200 bg-white px-3 py-2 text-xs font-semibold text-neutral-700 transition hover:bg-neutral-100 disabled:cursor-not-allowed disabled:text-neutral-400"
                              >
                                Unblacklist all
                              </button>
                            </div>
                          </div>
                        </div>
                        <div className="mt-5 rounded-2xl border border-neutral-200 bg-white">
                          <div className="overflow-x-auto">
                            <div className="min-w-[680px]">
                              <div
                                className="grid gap-3 px-6 py-3 text-xs font-semibold text-neutral-500"
                                style={{ gridTemplateColumns: BLACKLIST_GRID }}
                              >
                                <label className="flex items-center justify-center">
                                  <input
                                    type="checkbox"
                                    checked={allBlacklistSelected}
                                    onChange={toggleBlacklistSelectAll}
                                    className="h-4 w-4 rounded border-neutral-300 text-neutral-900"
                                  />
                                </label>
                                <span>Buyer</span>
                                <span>Reason</span>
                                <span>Added</span>
                                <span>Actions</span>
                              </div>
                              <div className="divide-y divide-neutral-100 overflow-x-hidden">
                                {blacklistLoading ? (
                                  <div className="px-6 py-6 text-center text-sm text-neutral-500">
                                    Loading blacklist...
                                  </div>
                                ) : blacklistEntries.length ? (
                                  blacklistEntries.map((entry, idx) => {
                                    const isSelected = blacklistSelected.includes(entry.owner);
                                    const isEditing =
                                      blacklistEditingId !== null &&
                                      entry.id !== undefined &&
                                      String(blacklistEditingId) === String(entry.id);
                                    return (
                                      <div
                                        key={entry.id ?? entry.owner ?? idx}
                                        className={`grid items-center gap-3 px-6 py-3 text-sm ${
                                          isSelected ? "bg-neutral-50" : "bg-white"
                                        }`}
                                        style={{ gridTemplateColumns: BLACKLIST_GRID }}
                                      >
                                        <label className="flex items-center justify-center">
                                          <input
                                            type="checkbox"
                                            checked={isSelected}
                                            onChange={() => toggleBlacklistSelected(entry.owner)}
                                            className="h-4 w-4 rounded border-neutral-300 text-neutral-900"
                                          />
                                        </label>
                                        {isEditing ? (
                                          <input
                                            value={blacklistEditOwner}
                                            onChange={(e) => setBlacklistEditOwner(e.target.value)}
                                            className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 outline-none"
                                          />
                                        ) : (
                                          <span className="min-w-0 truncate font-semibold text-neutral-900">{entry.owner}</span>
                                        )}
                                        {isEditing ? (
                                          <input
                                            value={blacklistEditReason}
                                            onChange={(e) => setBlacklistEditReason(e.target.value)}
                                            placeholder="Reason (optional)"
                                            className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 outline-none"
                                          />
                                        ) : (
                                          <span className="min-w-0 truncate text-neutral-600">{entry.reason || "-"}</span>
                                        )}
                                        <span className="text-xs text-neutral-500">
                                          {entry.createdAt ? new Date(entry.createdAt).toLocaleString() : "-"}
                                        </span>
                                        <div className="flex items-center gap-2">
                                          {isEditing ? (
                                            <>
                                              <button
                                                onClick={handleSaveBlacklistEdit}
                                                className="rounded-lg bg-neutral-900 px-3 py-1 text-xs font-semibold text-white"
                                              >
                                                Save
                                              </button>
                                              <button
                                                onClick={cancelEditBlacklist}
                                                className="rounded-lg border border-neutral-200 px-3 py-1 text-xs font-semibold text-neutral-600"
                                              >
                                                Cancel
                                              </button>
                                            </>
                                          ) : (
                                            <button
                                              onClick={() => startEditBlacklist(entry)}
                                              className="rounded-lg border border-neutral-200 px-3 py-1 text-xs font-semibold text-neutral-600"
                                            >
                                              Edit
                                            </button>
                                          )}
                                        </div>
                                      </div>
                                    );
                                  })
                                ) : (
                                  <div className="px-6 py-6 text-center text-sm text-neutral-500">
                                    Blacklist is empty.
                                  </div>
                                )}
                              </div>
                            </div>
                          </div>
                        </div>
                        <div className="mt-5 rounded-2xl border border-neutral-200 bg-white p-4">
                          <div className="mb-3 flex items-center justify-between">
                            <div>
                              <div className="text-sm font-semibold text-neutral-900">Activity</div>
                              <div className="text-xs text-neutral-500">Latest blacklist / unblacklist events.</div>
                            </div>
                            <button
                              onClick={() => loadBlacklistLogs(true)}
                              disabled={activeKeyId === "all" || blacklistLogsLoading}
                              className="rounded-lg border border-neutral-200 bg-white px-3 py-2 text-xs font-semibold text-neutral-700 transition hover:bg-neutral-100 disabled:cursor-not-allowed disabled:text-neutral-400"
                            >
                              Refresh
                            </button>
                          </div>
                          {blacklistLogsLoading ? (
                            <div className="py-4 text-sm text-neutral-500">Loading activity...</div>
                          ) : blacklistLogs.length === 0 ? (
                            <div className="py-4 text-sm text-neutral-500">No activity yet.</div>
                          ) : (
                            <div className="space-y-2">
                              {blacklistLogs.map((log, idx) => {
                                const action = (log.action || "").toLowerCase();
                                const badge =
                                  action === "add"
                                    ? { label: "Added", className: "bg-blue-100 text-blue-700" }
                                    : action.includes("unblacklist")
                                    ? { label: "Unblocked", className: "bg-green-100 text-green-700" }
                                    : action === "blocked_order"
                                    ? { label: "Blocked order", className: "bg-red-100 text-red-700" }
                                    : action === "compensation_payment"
                                    ? { label: "Payment", className: "bg-amber-100 text-amber-700" }
                                    : action === "update"
                                    ? { label: "Updated", className: "bg-neutral-100 text-neutral-700" }
                                    : action === "clear_all"
                                    ? { label: "Cleared", className: "bg-neutral-100 text-neutral-700" }
                                    : { label: action || "Event", className: "bg-neutral-100 text-neutral-700" };
                                return (
                                  <div
                                    key={`${log.owner}-${log.action}-${idx}`}
                                    className="flex flex-wrap items-center gap-3 rounded-xl border border-neutral-100 bg-neutral-50 px-3 py-2"
                                  >
                                    <span
                                      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold ${badge.className}`}
                                    >
                                      {badge.label}
                                    </span>
                                    <span className="text-sm font-semibold text-neutral-900">{log.owner}</span>
                                    {log.reason && (
                                      <span className="text-xs text-neutral-600">• {log.reason}</span>
                                    )}
                                    {log.details && (
                                      <span className="text-xs text-neutral-500">• {log.details}</span>
                                    )}
                                    <span className="ml-auto text-[11px] text-neutral-500">
                                      {log.created_at ? formatDate(log.created_at) : ""}
                                    </span>
                                  </div>
                                );
                              })}
                            </div>
                          )}
                        </div>
                      </div>
                    </motion.div>
                  ) : activeNav === "orders" ? (
                    <motion.div
                      key="orders"
                      initial={{ opacity: 0, y: 12 }}
                      animate={{ opacity: 1, y: 0, transition: { duration: 0.6, ease: EASE } }}
                      className="mt-8 space-y-4"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-4">
                        <div>
                          <h3 className="text-lg font-semibold text-neutral-900">Orders History</h3>
                          <p className="text-sm text-neutral-500">
                            Search by buyer, order ID, account, or SteamID64.
                          </p>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="text-xs rounded-full bg-neutral-100 px-3 py-1 font-semibold text-neutral-600">
                            {ordersHistory.length} records
                          </span>
                          <button
                            onClick={() => loadOrdersHistory(ordersQuery.trim(), true)}
                            className="rounded-lg border border-neutral-200 bg-neutral-50 px-3 py-2 text-xs text-neutral-600"
                          >
                            Refresh
                          </button>
                        </div>
                      </div>
                      <div className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm shadow-neutral-200/70">
                        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                          <label className="relative flex h-11 w-full max-w-xl items-center gap-3 rounded-lg border border-neutral-200 bg-neutral-50 px-4 text-sm text-neutral-500 shadow-sm shadow-neutral-200">
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                              <path
                                d="M11 19C15.4183 19 19 15.4183 19 11C19 6.58172 15.4183 3 11 3C6.58172 3 3 6.58172 3 11C3 15.4183 6.58172 19 11 19Z"
                                stroke="#9CA3AF"
                                strokeWidth="2"
                                strokeLinecap="round"
                                strokeLinejoin="round"
                              />
                              <path d="M21 21L16.65 16.65" stroke="#9CA3AF" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                            </svg>
                            <input
                              type="search"
                              placeholder="Search by buyer, order ID, account, Steam ID"
                              value={ordersQuery}
                              onChange={(event) => setOrdersQuery(event.target.value)}
                              className="w-full bg-transparent text-neutral-700 placeholder:text-neutral-400 outline-none"
                            />
                          </label>
                          <div className="text-xs text-neutral-500">Tip: paste SteamID64 to find who rented it.</div>
                        </div>
                        <div className="overflow-x-auto">
                          <div className="min-w-[1200px]">
                            <div
                              className="grid gap-3 px-6 text-xs font-semibold text-neutral-500"
                              style={{ gridTemplateColumns: ORDERS_GRID }}
                            >
                              <span>Order</span>
                              <span>Buyer</span>
                              <span>Account</span>
                              <span>Steam ID</span>
                              <span>Duration</span>
                              <span>Price</span>
                              <span>Action</span>
                              <span>Date</span>
                              <span>Chat</span>
                            </div>
                            <div className="mt-3 space-y-3 overflow-y-auto overflow-x-hidden pr-1" style={{ maxHeight: "640px" }}>
                              {ordersLoading && (
                                <div className="rounded-xl border border-dashed border-neutral-200 bg-neutral-50 px-4 py-6 text-center text-sm text-neutral-500">
                                  Loading orders...
                                </div>
                              )}
                              {!ordersLoading &&
                                ordersHistory.map((order, idx) => {
                                  const pill = orderActionPill(order.action);
                                  const priceLabel =
                                    order.price !== null && order.price !== undefined && !Number.isNaN(Number(order.price))
                                      ? `RUB ${Number(order.price).toLocaleString()}`
                                      : "-";
                                  const accountLabel = order.accountName || order.login || "-";
                                  const subLabel = order.lotNumber ? `Lot ${order.lotNumber}` : order.accountId ? `ID ${order.accountId}` : "";
                                  return (
                                    <motion.div
                                      key={order.id ?? idx}
                                      initial={{ opacity: 0, y: 8 }}
                                      animate={{ opacity: 1, y: 0, transition: { duration: 0.2, delay: idx * 0.02, ease: EASE } }}
                                      className="grid items-center gap-3 rounded-xl border border-neutral-100 bg-neutral-50 px-6 py-4 text-sm shadow-[0_4px_18px_-14px_rgba(0,0,0,0.18)]"
                                      style={{ gridTemplateColumns: ORDERS_GRID }}
                                    >
                                      <span className="min-w-0 truncate font-mono text-xs text-neutral-700">
                                        {order.orderId || "-"}
                                      </span>
                                      {order.buyer ? (
                                        order.chatUrl ? (
                                          <a
                                            href={order.chatUrl}
                                            target="_blank"
                                            rel="noreferrer"
                                            className="min-w-0 truncate font-semibold text-neutral-800 hover:underline"
                                          >
                                            {order.buyer}
                                          </a>
                                        ) : (
                                          <span className="min-w-0 truncate font-semibold text-neutral-800">{order.buyer}</span>
                                        )
                                      ) : (
                                        <span className="min-w-0 truncate text-neutral-400">-</span>
                                      )}
                                      <div className="min-w-0">
                                        <div className="truncate font-semibold text-neutral-900">{accountLabel}</div>
                                        {subLabel ? (
                                          <div className="text-xs text-neutral-400">{subLabel}</div>
                                        ) : (
                                          <div className="text-xs text-neutral-300">-</div>
                                        )}
                                      </div>
                                      <span className="min-w-0 truncate font-mono text-xs text-neutral-700">
                                        {order.steamId || "-"}
                                      </span>
                                      <span className="min-w-0 truncate font-mono text-neutral-900">
                                        {formatMinutesLabel(order.rentalMinutes)}
                                      </span>
                                      <span className="min-w-0 truncate font-semibold text-neutral-900">{priceLabel}</span>
                                      <span className={`inline-flex w-fit justify-self-start rounded-full px-3 py-1 text-xs font-semibold ${pill.className}`}>
                                        {pill.label}
                                      </span>
                                      <span className="min-w-0 truncate text-xs text-neutral-500">
                                        {formatMoscowDateTime(order.createdAt)}
                                      </span>
                                      {order.chatUrl ? (
                                        <a
                                          href={order.chatUrl}
                                          target="_blank"
                                          rel="noreferrer"
                                          className="inline-flex w-fit items-center justify-center rounded-full bg-neutral-900 px-3 py-1 text-xs font-semibold text-white"
                                        >
                                          Open
                                        </a>
                                      ) : (
                                        <span className="text-xs text-neutral-400">-</span>
                                      )}
                                    </motion.div>
                                  );
                                })}
                              {!ordersLoading && ordersHistory.length === 0 && (
                                <div className="rounded-xl border border-dashed border-neutral-200 bg-neutral-50 px-4 py-6 text-center text-sm text-neutral-500">
                                  No orders found.
                                </div>
                              )}
                            </div>
                          </div>
                        </div>
                      </div>
                    </motion.div>
                  ) : activeNav === "lots" ? (
                    <motion.div
                      key="lots"
                      initial={{ opacity: 0, y: 12 }}
                      animate={{ opacity: 1, y: 0, transition: { duration: 0.6, ease: EASE } }}
                      className="mt-8 space-y-6"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-4">
                        <div>
                          <h3 className="text-lg font-semibold text-neutral-900">Lots</h3>
                          <p className="text-sm text-neutral-500">
                            Map FunPay lot numbers to Steam accounts. Each workspace has its own lots.
                          </p>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="text-xs rounded-full bg-neutral-100 px-3 py-1 font-semibold text-neutral-600">
                            {filteredLots.length} mapped
                          </span>
                          <button
                            onClick={() => loadLots(true)}
                            className="rounded-lg border border-neutral-200 bg-neutral-50 px-3 py-2 text-xs text-neutral-600"
                          >
                            Refresh
                          </button>
                        </div>
                      </div>
                      <div className="grid gap-6 lg:grid-cols-[1.05fr_1.5fr]">
                        <div className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm shadow-neutral-200/70">
                          <div className="mb-4">
                            <h4 className="text-base font-semibold text-neutral-900">Lot setup</h4>
                            <p className="text-xs text-neutral-500">
                              Choose a workspace, link the lot number, and pick the account to deliver.
                            </p>
                          </div>
                          <div className="space-y-4">
                            {activeKeyId === "all" && (
                              <div className="rounded-lg border border-dashed border-neutral-200 bg-neutral-50 px-4 py-3 text-xs text-neutral-500">
                                Select a workspace to save a lot mapping.
                              </div>
                            )}
                            {userKeys.length > 0 && (
                              <div className="space-y-1">
                                <label className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
                                  Workspace
                                </label>
                                <select
                                  value={activeKeyId === "all" ? lotKeyId : String(activeKeyId)}
                                  onChange={(e) => setLotKeyId(e.target.value)}
                                  disabled={activeKeyId !== "all"}
                                  className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 outline-none disabled:bg-neutral-100"
                                >
                                  <option value="">Select workspace</option>
                                  {userKeys.map((item) => (
                                    <option key={item.id} value={item.id}>
                                      {item.label || `Workspace ${item.id}`}
                                    </option>
                                  ))}
                                </select>
                              </div>
                            )}
                            <div className="grid gap-3 md:grid-cols-2">
                              <div className="space-y-1">
                                <label className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
                                  Lot number
                                </label>
                                <input
                                  value={lotNumber}
                                  onChange={(e) => setLotNumber(e.target.value)}
                                  type="number"
                                  min="1"
                                  placeholder="e.g. 128392"
                                  className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 outline-none"
                                />
                              </div>
                              <div className="space-y-1">
                                <label className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
                                  Account
                                </label>
                                <select
                                  value={lotAccountId}
                                  onChange={(e) => setLotAccountId(e.target.value)}
                                  disabled={activeKeyId === "all" && !lotKeyId}
                                  className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 outline-none disabled:bg-neutral-100"
                                >
                                  <option value="">
                                    {activeKeyId === "all" && !lotKeyId
                                      ? "Select workspace first"
                                      : "Select account"}
                                  </option>
                                  {lotAccounts.map((acc, idx) => {
                                    const label = acc.name || acc.login || `ID ${acc.id ?? idx}`;
                                    const rented = isAccountRented(acc);
                                    const mapped = mappedAccountIds.has(String(acc.id ?? ""));
                                    return (
                                      <option key={acc.id ?? idx} value={acc.id ?? idx} disabled={mapped}>
                                        {label} {rented ? "• rented" : "• available"} {mapped ? "• mapped" : ""}
                                      </option>
                                    );
                                  })}
                                </select>
                              </div>
                            </div>
                            <div className="space-y-1">
                              <label className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
                                Lot URL (optional)
                              </label>
                              <input
                                value={lotUrl}
                                onChange={(e) => setLotUrl(e.target.value)}
                                type="url"
                                placeholder="https://funpay.com/lots/..."
                                className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 outline-none"
                              />
                            </div>
                            <button
                              onClick={handleCreateLot}
                              disabled={lotActionBusy || (activeKeyId === "all" && !lotKeyId)}
                              className="w-full rounded-lg bg-neutral-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-neutral-800 disabled:cursor-not-allowed disabled:bg-neutral-300"
                            >
                              Save mapping
                            </button>
                          </div>
                        </div>
                        <div className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm shadow-neutral-200/70">
                          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                            <div className="text-sm font-semibold text-neutral-900">Mapped lots</div>
                            <div className="text-xs text-neutral-500">
                              Showing {filteredLots.length} {filteredLots.length === 1 ? "lot" : "lots"}
                            </div>
                          </div>
                          <div className="mb-3">
                            <input
                              value={lotsQuery}
                              onChange={(e) => setLotsQuery(e.target.value)}
                              placeholder="Search by lot number, account, or owner"
                              type="search"
                              className="w-full rounded-lg border border-neutral-200 bg-neutral-50 px-3 py-2 text-sm text-neutral-700 outline-none placeholder:text-neutral-400"
                            />
                          </div>
                          <div className="overflow-x-auto">
                            <div className="min-w-[980px]">
                              <div
                                className="grid gap-3 px-6 text-xs font-semibold text-neutral-500"
                                style={{ gridTemplateColumns: LOTS_GRID }}
                              >
                                <span>Lot</span>
                                <span>Account</span>
                                <span>Workspace</span>
                                <span>Owner</span>
                                <span>URL</span>
                                <span className="text-right">Actions</span>
                              </div>
                              <div className="mt-3 space-y-3 max-h-[520px] overflow-y-auto pr-1">
                                {lotsLoading && (
                                  <div className="rounded-xl border border-dashed border-neutral-200 bg-neutral-50 px-4 py-6 text-center text-sm text-neutral-500">
                                    Loading lots...
                                  </div>
                                )}
                                {!lotsLoading &&
                                  filteredLots.map((item) => (
                                    (() => {
                                      const isEditing = editingLotNumber === item.lotNumber;
                                      const editKey = editingLotKeyId ?? item.keyId ?? null;
                                      const editAccounts =
                                        activeKeyId === "all" && editKey !== null
                                          ? accountsTable.filter((acc) => {
                                              const keyValue = acc.keyId ?? null;
                                              return keyValue === editKey || keyValue === null;
                                            })
                                          : lotAccounts;
                                      return (
                                        <div
                                          key={`${item.lotNumber}-${item.accountId}`}
                                          className="grid items-center gap-3 rounded-xl border border-neutral-100 bg-neutral-50 px-6 py-4 text-sm shadow-[0_4px_18px_-14px_rgba(0,0,0,0.18)]"
                                          style={{ gridTemplateColumns: LOTS_GRID }}
                                        >
                                          <div className="font-semibold text-neutral-900">
                                            {isEditing ? (
                                              <input
                                                value={editLotNumber}
                                                onChange={(e) => setEditLotNumber(e.target.value)}
                                                type="number"
                                                min="1"
                                                className="w-full rounded-lg border border-neutral-200 bg-white px-2 py-1 text-sm text-neutral-700 outline-none"
                                              />
                                            ) : (
                                              `#${item.lotNumber}`
                                            )}
                                          </div>
                                          <div className="min-w-0">
                                            {isEditing ? (
                                              <select
                                                value={editLotAccountId}
                                                onChange={(e) => setEditLotAccountId(e.target.value)}
                                                className="w-full rounded-lg border border-neutral-200 bg-white px-2 py-1 text-sm text-neutral-700 outline-none"
                                              >
                                                {editAccounts.map((acc, idx) => {
                                                  const label = acc.name || acc.login || `ID ${acc.id ?? idx}`;
                                                  const mapped = mappedAccountIds.has(String(acc.id ?? ""));
                                                  const isCurrent = String(acc.id ?? "") === String(item.accountId);
                                                  return (
                                                    <option
                                                      key={acc.id ?? idx}
                                                      value={acc.id ?? idx}
                                                      disabled={mapped && !isCurrent}
                                                    >
                                                      {label} {mapped && !isCurrent ? "• mapped" : ""}
                                                    </option>
                                                  );
                                                })}
                                              </select>
                                            ) : (
                                              <>
                                                <div className="truncate font-semibold text-neutral-900">
                                                  {item.accountName || `ID ${item.accountId}`}
                                                </div>
                                                <div className="text-xs text-neutral-400">ID {item.accountId}</div>
                                              </>
                                            )}
                                          </div>
                                          <span className="text-xs font-semibold text-neutral-600">
                                            {resolveKeyLabel(editKey)}
                                          </span>
                                          <span className="text-xs text-neutral-500">{item.owner || "-"}</span>
                                          {isEditing ? (
                                            <input
                                              value={editLotUrl}
                                              onChange={(e) => setEditLotUrl(e.target.value)}
                                              placeholder="https://funpay.com/lots/..."
                                              className="w-full rounded-lg border border-neutral-200 bg-white px-2 py-1 text-xs text-neutral-700 outline-none"
                                            />
                                          ) : item.lotUrl ? (
                                            <a
                                              href={item.lotUrl}
                                              target="_blank"
                                              rel="noreferrer"
                                              className="min-w-0 truncate text-xs font-semibold text-neutral-700 hover:underline"
                                            >
                                              Open
                                            </a>
                                          ) : (
                                            <span className="text-xs text-neutral-400">-</span>
                                          )}
                                          <div className="flex justify-end gap-2">
                                            {isEditing ? (
                                              <>
                                                <button
                                                  onClick={handleSaveLotEdit}
                                                  className="rounded-lg bg-neutral-900 px-3 py-1 text-xs font-semibold text-white"
                                                >
                                                  Save
                                                </button>
                                                <button
                                                  onClick={cancelEditLot}
                                                  className="rounded-lg border border-neutral-200 px-3 py-1 text-xs font-semibold text-neutral-600"
                                                >
                                                  Cancel
                                                </button>
                                              </>
                                            ) : (
                                              <>
                                                <button
                                                  onClick={() => startEditLot(item)}
                                                  className="rounded-lg border border-neutral-200 px-3 py-1 text-xs font-semibold text-neutral-600"
                                                >
                                                  Edit
                                                </button>
                                                <button
                                                  onClick={() => handleDeleteLot(item)}
                                                  className="rounded-lg border border-neutral-200 px-3 py-1 text-xs font-semibold text-neutral-600"
                                                >
                                                  Remove
                                                </button>
                                              </>
                                            )}
                                          </div>
                                        </div>
                                      );
                                    })()
                                  ))}
                                {!lotsLoading && filteredLots.length === 0 && (
                                  <div className="rounded-xl border border-dashed border-neutral-200 bg-neutral-50 px-4 py-6 text-center text-sm text-neutral-500">
                                    No lots mapped yet.
                                  </div>
                                )}
                              </div>
                            </div>
                          </div>
                        </div>
                      </div>
                    </motion.div>
                  ) : activeNav === "notifications" ? (
                    <motion.div
                      key="notifications"
                      initial={{ opacity: 0, y: 12 }}
                      animate={{ opacity: 1, y: 0, transition: { duration: 0.6, ease: EASE } }}
                      className="mt-8"
                    >
                      <div className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm shadow-neutral-200/70">
                        <div className="mb-4 flex items-center justify-between">
                          <h3 className="text-lg font-semibold text-neutral-900">System Notifications</h3>
                          <span className="text-xs rounded-full bg-neutral-100 px-3 py-1 font-semibold text-neutral-600">
                            {notifications.length} items
                          </span>
                        </div>
                        <div className="space-y-3">
                          {notifications.map((n, idx) => (
                            <motion.div
                              key={n.id ?? idx}
                              initial={{ opacity: 0, y: 8 }}
                              animate={{ opacity: 1, y: 0, transition: { duration: 0.2, delay: idx * 0.02, ease: EASE } }}
                              className="rounded-xl border border-neutral-100 bg-neutral-50 px-4 py-3 text-sm text-neutral-800"
                            >
                              <div className="mb-1 flex items-center gap-2 text-xs uppercase tracking-wide text-neutral-500">
                                <span className="font-semibold">{n.level?.toUpperCase() || "INFO"}</span>
                                <span>{n.createdAt ? new Date(n.createdAt).toLocaleString() : ""}</span>
                              </div>
                              <div className="text-neutral-900">{n.message || "-"}</div>
                              <div className="text-xs text-neutral-500">
                                Owner: {n.owner || "-"} - Account: {n.accountId || "-"}
                              </div>
                            </motion.div>
                          ))}
                          {notifications.length === 0 && (
                            <div className="rounded-xl border border-dashed border-neutral-200 bg-neutral-50 px-4 py-6 text-center text-sm text-neutral-500">
                              No notifications yet.
                            </div>
                          )}
                        </div>
                      </div>
                    </motion.div>
                  ) : activeNav === "inventory" ? (
                    <motion.div
                      key="inventory"
                      initial={{ opacity: 0, y: 12 }}
                      animate={{ opacity: 1, y: 0, transition: { duration: 0.6, ease: EASE } }}
                      className="mt-8"
                    >
                      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
                        <div className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm shadow-neutral-200/70">
                          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                            <div>
                              <h3 className="text-lg font-semibold text-neutral-900">Inventory</h3>
                              <p className="text-xs text-neutral-500">Select an account to manage rentals.</p>
                            </div>
                            <div className="flex flex-wrap items-center gap-2">
                              <div className="flex items-center gap-2 rounded-lg border border-neutral-200 bg-neutral-50 px-3 py-2 text-[11px] font-semibold text-neutral-600">
                                <span className="uppercase tracking-wide text-neutral-500">Workspace</span>
                                <select
                                  value={activeKeyId === "all" ? "all" : String(activeKeyId)}
                                  onChange={(event) => {
                                    const next = event.target.value;
                                    const parsed = Number(next);
                                    setActiveKeyId(next === "all" || !Number.isFinite(parsed) ? "all" : parsed);
                                  }}
                                  className="bg-transparent text-xs font-semibold text-neutral-700 outline-none"
                                >
                                  <option value="all">All workspaces</option>
                                  {userKeys.map((item) => (
                                    <option key={item.id} value={item.id}>
                                      {item.label || `Workspace ${item.id}`}
                                    </option>
                                  ))}
                                </select>
                              </div>
                              {selectedAccount ? (
                                <span className="text-xs rounded-full bg-neutral-100 px-3 py-1 font-semibold text-neutral-600">
                                  Selected ID {selectedAccount.id ?? "-"}
                                </span>
                              ) : (
                                <span className="text-xs rounded-full bg-neutral-100 px-3 py-1 font-semibold text-neutral-600">
                                  No account selected
                                </span>
                              )}
                            </div>
                          </div>
                          <div className="overflow-x-auto">
                            <div className="min-w-[1000px]">
                              <div
                                className="grid gap-3 px-6 text-xs font-semibold text-neutral-500"
                                style={{ gridTemplateColumns: INVENTORY_GRID }}
                              >
                                <span>ID</span>
                                <span>Name</span>
                                <span>Login</span>
                                <span>Password</span>
                                <span>Steam ID</span>
                                <span>MMR</span>
                                <span className="text-right">State</span>
                              </div>
                              <div className="mt-3 space-y-3 overflow-y-auto overflow-x-hidden pr-1" style={{ maxHeight: "640px" }}>
                                {accountsTable.map((acc, idx) => {
                                  const rented = isAccountRented(acc);
                                  const frozen = !!acc.accountFrozen;
                                  const stateLabel = frozen ? "Frozen" : rented ? "Rented out" : "Available";
                                  const stateClass = frozen
                                    ? "bg-slate-100 text-slate-700"
                                    : rented
                                      ? "bg-amber-50 text-amber-700"
                                      : "bg-emerald-50 text-emerald-600";
                                  const rowId = acc.id ?? idx;
                                  const isSelected =
                                    selectedAccountId !== null && String(selectedAccountId) === String(rowId);
                                  return (
                                    <motion.div
                                      key={rowId}
                                      role="button"
                                      tabIndex={0}
                                      onKeyDown={(event) => {
                                        if (event.key === "Enter" || event.key === " ") {
                                          event.preventDefault();
                                          setSelectedAccountId((prev) =>
                                            prev !== null && String(prev) === String(rowId) ? null : rowId
                                          );
                                        }
                                      }}
                                      onClick={() =>
                                        setSelectedAccountId((prev) =>
                                          prev !== null && String(prev) === String(rowId) ? null : rowId
                                        )
                                      }
                                      initial={{ opacity: 0, y: 10 }}
                                      animate={{
                                        opacity: 1,
                                        y: 0,
                                        transition: { duration: 0.25, delay: idx * 0.03, ease: EASE },
                                      }}
                                      className={`grid min-w-full items-center gap-3 rounded-xl border px-6 py-4 text-sm shadow-[0_4px_18px_-14px_rgba(0,0,0,0.18)] transition ${
                                        isSelected
                                          ? "border-neutral-900/20 bg-white ring-2 ring-neutral-900/10"
                                          : "border-neutral-100 bg-neutral-50 hover:border-neutral-200"
                                      } cursor-pointer`}
                                      style={{ gridTemplateColumns: INVENTORY_GRID }}
                                    >
                                      <span className="min-w-0 font-semibold text-neutral-900" title={String(rowId)}>
                                        {rowId}
                                      </span>
                                      <div className="min-w-0">
                                        <div
                                          className="truncate font-semibold leading-tight text-neutral-900"
                                          title={acc.name || "Account"}
                                        >
                                          {acc.name || "Account"}
                                        </div>
                                        <span className="mt-1 inline-flex w-fit rounded-full bg-neutral-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-neutral-600">
                                          {resolveKeyLabel(acc.keyId)}
                                        </span>
                                      </div>
                                      <span className="min-w-0 truncate text-neutral-700" title={acc.login || ""}>
                                        {acc.login || ""}
                                      </span>
                                      <span className="min-w-0 truncate text-neutral-700" title={acc.password || ""}>
                                        {acc.password || ""}
                                      </span>
                                      <span
                                        className="min-w-0 truncate font-mono text-xs leading-tight text-neutral-800 tabular-nums"
                                        title={acc.steamId || ""}
                                      >
                                        {acc.steamId || ""}
                                      </span>
                                      <span className="min-w-0 truncate text-neutral-700" title={acc.mmr ?? ""}>
                                        {acc.mmr ?? ""}
                                      </span>
                                      <span
                                        className={`justify-self-end rounded-full px-3 py-1 text-xs font-semibold ${stateClass}`}
                                      >
                                        {stateLabel}
                                      </span>
                                    </motion.div>
                                  );
                                })}
                                {accountsTable.length === 0 && (
                                  <div
                                    className={`rounded-xl border border-dashed border-neutral-200 bg-neutral-50 px-4 py-6 text-center text-sm text-neutral-500 ${
                                      authState !== "guest" && !overviewHydrated ? "animate-pulse" : ""
                                    }`}
                                  >
                                    {authState !== "guest" && !overviewHydrated ? "Loading accounts..." : "No accounts loaded yet."}
                                  </div>
                                )}
                              </div>
                            </div>
                          </div>
                        </div>
                        <div className="mt-6 grid gap-6 lg:grid-cols-2">
                          {renderAccountActionsPanel("Account actions")}
                          {renderInventoryActionsPanel()}
                        </div>
                      </div>
                    </motion.div>
                  ) : (
                    <div className="mt-8 space-y-6">
                      <div className="grid gap-6 lg:grid-cols-2">
                        <div className="min-h-[520px] rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm shadow-neutral-200/70">
                        <div className="mb-4 flex items-center justify-between">
                          <h3 className="text-lg font-semibold text-neutral-900">Inventory</h3>
                        </div>
                        <div className="overflow-x-auto">
                          <div className="min-w-[1000px]">
                            <div
                              className="grid gap-3 px-6 text-xs font-semibold text-neutral-500"
                              style={{ gridTemplateColumns: INVENTORY_GRID }}
                            >
                              <span>ID</span>
                              <span>Name</span>
                              <span>Login</span>
                              <span>Password</span>
                              <span>Steam ID</span>
                              <span>MMR</span>
                              <span className="text-right">State</span>
                            </div>
                            <div className="mt-3 space-y-3 overflow-y-auto overflow-x-hidden pr-1" style={{ maxHeight: "640px" }}>
                          {accountsTable.map((acc, idx) => {
                            const rented = isAccountRented(acc);
                            const frozen = !!acc.accountFrozen;
                            const stateLabel = frozen ? "Frozen" : rented ? "Rented out" : "Available";
                            const stateClass = frozen
                              ? "bg-slate-100 text-slate-700"
                              : rented
                                ? "bg-amber-50 text-amber-700"
                                : "bg-emerald-50 text-emerald-600";
                            const rowId = acc.id ?? idx;
                            const isSelected =
                              selectedAccountId !== null && String(selectedAccountId) === String(rowId);
                            return (
                              <motion.div
                                key={rowId}
                                role="button"
                                tabIndex={0}
                                onKeyDown={(event) => {
                                  if (event.key === "Enter" || event.key === " ") {
                                    event.preventDefault();
                                    setSelectedAccountId((prev) =>
                                      prev !== null && String(prev) === String(rowId) ? null : rowId
                                    );
                                  }
                                }}
                                onClick={() =>
                                  setSelectedAccountId((prev) =>
                                    prev !== null && String(prev) === String(rowId) ? null : rowId
                                  )
                                }
                                initial={{ opacity: 0, y: 10 }}
                                animate={{ opacity: 1, y: 0, transition: { duration: 0.25, delay: idx * 0.03, ease: EASE } }}
                                className={`grid items-center gap-3 rounded-xl border px-6 py-4 text-sm shadow-[0_4px_18px_-14px_rgba(0,0,0,0.18)] transition ${
                                  isSelected
                                    ? "border-neutral-900/20 bg-white ring-2 ring-neutral-900/10"
                                    : "border-neutral-100 bg-neutral-50 hover:border-neutral-200"
                                } cursor-pointer`}
                                style={{ gridTemplateColumns: INVENTORY_GRID, minWidth: "100%" }}
                              >
                                <span className="min-w-0 font-semibold text-neutral-900" title={String(rowId)}>{rowId}</span>
                                <div className="min-w-0">
                                  <div
                                    className="truncate font-semibold leading-tight text-neutral-900"
                                    title={acc.name || "Account"}
                                  >
                                    {acc.name || "Account"}
                                  </div>
                                  <span className="mt-1 inline-flex w-fit rounded-full bg-neutral-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-neutral-600">
                                    {resolveKeyLabel(acc.keyId)}
                                  </span>
                                </div>
                                <span className="min-w-0 truncate text-neutral-700" title={acc.login || ""}>{acc.login || ""}</span>
                                <span className="min-w-0 truncate text-neutral-700" title={acc.password || ""}>{acc.password || ""}</span>
                                <span className="min-w-0 truncate font-mono text-xs leading-tight text-neutral-800 tabular-nums" title={acc.steamId || ""}>
                                  {acc.steamId || ""}
                                </span>
                                <span className="min-w-0 truncate text-neutral-700" title={acc.mmr ?? ""}>{acc.mmr ?? ""}</span>
                                <span className={`justify-self-end rounded-full px-3 py-1 text-xs font-semibold ${stateClass}`}>
                                  {stateLabel}
                                </span>
                              </motion.div>
                            );
                          })}
                          {accountsTable.length === 0 && (
                            <div
                              className={`rounded-xl border border-dashed border-neutral-200 bg-neutral-50 px-4 py-6 text-center text-sm text-neutral-500 ${
                                authState !== "guest" && !overviewHydrated ? "animate-pulse" : ""
                              }`}
                            >
                              {authState !== "guest" && !overviewHydrated ? "Loading accounts..." : "No accounts loaded yet."}
                            </div>
                          )}
                            </div>
                          </div>
                        </div>
                      </div>
                      <div className="min-h-[520px] rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm shadow-neutral-200/70">
                        <div className="mb-4 flex items-center justify-between">
                          <h3 className="text-lg font-semibold text-neutral-900">Active rentals</h3>
                          <button className="rounded-lg border border-neutral-200 bg-neutral-50 px-3 py-2 text-xs text-neutral-600">Status</button>
                        </div>
                        <div className="overflow-x-auto">
                          <div className="min-w-[1100px]">
                            <div
                              className="grid gap-3 px-6 text-xs font-semibold text-neutral-500"
                              style={{ gridTemplateColumns: RENTALS_GRID }}
                            >
                              <span>ID</span>
                              <span>Account</span>
                              <span>Buyer</span>
                              <span>Started</span>
                              <span>Time Left</span>
                              <span>Match Time</span>
                              <span>Hero</span>
                              <span>Status</span>
                            </div>
                            <div className="mt-3 space-y-3 overflow-y-auto overflow-x-hidden pr-1" style={{ maxHeight: "640px" }}>
                          {rentalsTable.map((r, idx) => {
            const presence = r.presence ?? null;
            const timer = getMatchTimeLabel(presence, r.presenceObservedAt ?? null);
                            const frozen = !!r.rentalFrozen;
                            const presenceLabel = frozen
                              ? "Frozen"
                              : presence?.in_match
                                ? "In match"
                                : presence?.in_game
                                  ? "In game"
                                  : "Offline";
                            const pill = statusPill(presenceLabel);
                            const adminCalls = Number(r.adminCalls || 0);
                            const hasAdminCall = adminCalls > 0;
                            const timeLeft =
                              r.durationSec != null && r.startedAt != null
                                ? formatDuration(
                                    r.durationSec,
                                    r.startedAt,
                                    now,
                                    frozen ? r.rentalFrozenAt ?? null : null
                                  )
                                : "-";
                            const rowId = r.id ?? idx;
                            const isSelected =
                              selectedRentalId !== null && String(selectedRentalId) === String(rowId);
                            return (
                              <motion.div
                                key={rowId}
                                role="button"
                                tabIndex={0}
                                onKeyDown={(event) => {
                                  if (event.key === "Enter" || event.key === " ") {
                                    event.preventDefault();
                                    const nextSelected =
                                      selectedRentalId !== null && String(selectedRentalId) === String(rowId)
                                        ? null
                                        : rowId;
                                    setSelectedRentalId(nextSelected);
                                    if (nextSelected !== null) {
                                      setSelectedAccountId(rowId);
                                    }
                                  }
                                }}
                                onClick={() => {
                                  const nextSelected =
                                    selectedRentalId !== null && String(selectedRentalId) === String(rowId)
                                      ? null
                                      : rowId;
                                  setSelectedRentalId(nextSelected);
                                  if (nextSelected !== null) {
                                    setSelectedAccountId(rowId);
                                  }
                                }}
                                initial={{ opacity: 0, y: 10 }}
                                animate={{ opacity: 1, y: 0, transition: { duration: 0.25, delay: idx * 0.03, ease: EASE } }}
                                className={`grid items-center gap-3 rounded-xl border px-6 py-4 text-sm shadow-[0_4px_18px_-14px_rgba(0,0,0,0.18)] transition ${
                                  isSelected
                                    ? "border-neutral-900/20 bg-white ring-2 ring-neutral-900/10"
                                    : `border-neutral-100 bg-neutral-50 hover:border-neutral-200 ${
                                        hasAdminCall ? "ring-1 ring-rose-200 bg-rose-50/60" : ""
                                      }`
                                } cursor-pointer`}
                                style={{ gridTemplateColumns: RENTALS_GRID }}
                              >
                                <span className="min-w-0 truncate font-semibold text-neutral-900">{rowId}</span>
                                <div className="min-w-0">
                                  <div className="truncate text-neutral-800">{r.accountName || ""}</div>
                                  <span className="mt-1 inline-flex w-fit rounded-full bg-neutral-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-neutral-600">
                                    {resolveKeyLabel(r.keyId)}
                                  </span>
                                </div>
                                {r.buyer ? (
                                  r.chatUrl ? (
                                    <a
                                      href={r.chatUrl}
                                      target="_blank"
                                      rel="noreferrer"
                                      className="min-w-0 truncate font-semibold text-neutral-800 hover:underline"
                                      onClick={(event) => event.stopPropagation()}
                                    >
                                      {r.buyer}
                                    </a>
                                  ) : (
                                    <span className="min-w-0 truncate text-neutral-700">{r.buyer}</span>
                                  )
                                ) : (
                                  <span className="min-w-0 truncate text-neutral-400">-</span>
                                )}
                                <span className="min-w-0 truncate text-neutral-600">{formatStartTime(r.startedAt) || "-"}</span>
                                <span className="min-w-0 truncate font-mono text-neutral-900">{timeLeft}</span>
                                <span className="min-w-0 truncate font-mono text-neutral-900">{timer}</span>
                                <span className="min-w-0 truncate text-neutral-700">{presence?.hero_name || r.hero || ""}</span>
                                <div className="flex items-center gap-2">
                                  {hasAdminCall && (
                                    <span className="rounded-full bg-rose-100 px-2 py-1 text-[11px] font-semibold text-rose-600">
                                      Admin call {adminCalls}
                                    </span>
                                  )}
                                  {r.steamId ? (
                                    <a
                                      href={`${PRESENCE_BASE}/${r.steamId}`}
                                      target="_blank"
                                      rel="noreferrer"
                                      className={`inline-flex w-fit justify-self-start rounded-full px-3 py-1 text-xs font-semibold ${pill.className}`}
                                      onClick={(event) => event.stopPropagation()}
                                    >
                                      {presenceLabel}
                                    </a>
                                  ) : (
                                    <span className={`inline-flex w-fit justify-self-start rounded-full px-3 py-1 text-xs font-semibold ${pill.className}`}>
                                      {presenceLabel}
                                    </span>
                                  )}
                                </div>
                              </motion.div>
                            );
                          })}
                          {rentalsTable.length === 0 && (
                            <div
                              className={`rounded-xl border border-dashed border-neutral-200 bg-neutral-50 px-4 py-6 text-center text-sm text-neutral-500 ${
                                authState !== "guest" && !overviewHydrated ? "animate-pulse" : ""
                              }`}
                            >
                              {authState !== "guest" && !overviewHydrated ? "Loading rentals..." : "No active rentals yet."}
                            </div>
                          )}
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                    <div className="grid gap-6 lg:grid-cols-2">
                      {renderAccountActionsPanel("Account actions")}
                      {renderRentalActionsPanel()}
                    </div>
                  </div>
                  ))}
                </motion.div>
              </main>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
      <Toast toast={toast} />
    </>
  );
};

export default App;
type PresenceData = {
  in_game?: boolean;
  in_match?: boolean;
  hero_name?: string | null;
  hero_token?: string | null;
  lobby_info?: string | null;
  hero_level?: number | null;
  match_time?: string | null;
  match_seconds?: number | null;
  fetched_at?: number | null;
};

