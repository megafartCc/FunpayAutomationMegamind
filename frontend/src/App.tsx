import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import Toast from "./components/common/Toast";
import LoginPage from "./pages/LoginPage";
import { createApiClient } from "./services/api";
import { useToast } from "./hooks/useToast";
import AddAccountForm from "./components/account/AddAccountForm";

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

type BlacklistEntry = {
  id?: string | number;
  owner: string;
  reason?: string | null;
  createdAt?: string | null;
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
const CHAT_LIST_CACHE_KEY = `${CACHE_PREFIX}chat_list`;
const CHAT_HISTORY_CACHE_PREFIX = `${CACHE_PREFIX}chat_history:`;
const ORDERS_HISTORY_CACHE_PREFIX = `${CACHE_PREFIX}orders_history:`;
type CacheEntry<T> = { data: T; ts: number; etag?: string };
const memoryCache = new Map<string, CacheEntry<any>>();
const inflightRequests = new Map<string, Promise<CacheEntry<any> | null>>();
const revalidateGuards = new Map<string, number>();
const REVALIDATE_THROTTLE_MS = 4000;
const CACHE_TTLS = {
  stats: 10 * 60 * 1000,
  chatList: 15 * 1000,
  chatHistory: 8 * 1000,
  orders: 5 * 60 * 1000,
  blacklist: 2 * 60 * 1000,
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
  const [sessionChecked, setSessionChecked] = useState(false);
  const [pathname, setPathname] = useState(() => window.location.pathname);
  const [activeNav, setActiveNav] = useState<string>("overview");
  const [overview, setOverview] = useState<OverviewData>(createEmptyOverview);
  const [funpayStats, setFunpayStats] = useState<FunpayStatsPayload>(createEmptyFunpayStats);
  const [funpayStatsLoading, setFunpayStatsLoading] = useState(false);
  const [accountsTable, setAccountsTable] = useState<AccountRow[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState<string | number | null>(null);
  const [assignOwner, setAssignOwner] = useState("");
  const [extendHours, setExtendHours] = useState("");
  const [extendMinutes, setExtendMinutes] = useState("");
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
  const [chatInput, setChatInput] = useState("");
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [ordersHistory, setOrdersHistory] = useState<OrderHistoryItem[]>([]);
  const [ordersQuery, setOrdersQuery] = useState("");
  const [ordersLoading, setOrdersLoading] = useState(false);
  const [autoRaise, setAutoRaise] = useState<boolean>(() => localStorage.getItem("autoRaise") === "1");
  const [autoOnline, setAutoOnline] = useState<boolean>(() => localStorage.getItem("autoOnline") === "1");
  const [uiMode, setUiMode] = useState<"light" | "dark">(
    () => (localStorage.getItem("uiMode") as "light" | "dark") || "light"
  );
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
  const [profileName, setProfileName] = useState("");
  const [tick, setTick] = useState(0);
  const now = useMemo(() => Date.now(), [tick]);
  const { toast, showToast } = useToast();
  const sessionKey = useMemo(() => (token ? profileName || "session" : ""), [token, profileName]);
  const lastSessionRef = useRef<string>("");
  const presenceWarmupRef = useRef<number>(0);
  const scopedKey = useCallback(
    (key: string) => `${key}:u:${sessionKey || "anon"}`,
    [sessionKey]
  );
  const adminCallCountsRef = useRef<Record<string, number>>({});
  const adminCallToastRef = useRef<number>(0);

  useEffect(() => {
    const root = document.documentElement;
    if (uiMode === "dark") {
      root.classList.add("dark");
    } else {
      root.classList.remove("dark");
    }
  }, [uiMode]);

  const api = useMemo(
    () =>
      createApiClient({
        onUnauthorized: () => {
          setToken("");
          setProfileName("");
        },
      }),
    []
  );

  const { apiFetch, apiFetchWithMeta } = api;

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
      const cached = readCache<T>(key, ttl);
      if (cached?.data) {
        onData(cached.data);
      }
      if (onLoading) {
        onLoading(!cached?.data);
      }
      const shouldRevalidate = revalidate || !cached || cached.isStale;
      if (!shouldRevalidate) {
        if (onLoading) onLoading(false);
        return;
      }
      if (typeof navigator !== "undefined" && "onLine" in navigator && !navigator.onLine) {
        if (onLoading) onLoading(false);
        return;
      }
      if (revalidate) {
        const last = revalidateGuards.get(key) || 0;
        const nowTs = Date.now();
        if (nowTs - last < REVALIDATE_THROTTLE_MS) {
          if (onLoading) onLoading(false);
          return;
        }
        revalidateGuards.set(key, nowTs);
      }
      const inflight = inflightRequests.get(key);
      if (inflight) {
        await inflight.catch(() => null);
        if (onLoading) onLoading(false);
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
        if (next?.data) {
          onData(next.data);
        }
      } catch {
        // keep cached data
      } finally {
        inflightRequests.delete(key);
        if (onLoading) onLoading(false);
      }
    },
    [apiFetchWithMeta]
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
      return;
    }
    const owner =
      selectedAccount.owner && String(selectedAccount.owner).trim().toUpperCase() !== "OTHER_ACCOUNT"
        ? selectedAccount.owner
        : "";
    setAssignOwner(owner);
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
        const data = await apiFetch<{ username?: string }>("/api/auth/me");
        if (!active) return;
        if (data?.username) {
          setToken("session");
          setProfileName(data.username);
        } else {
          setToken("");
          setProfileName("");
        }
      } catch {
        if (!active) return;
        setToken("");
        setProfileName("");
      } finally {
        if (active) setSessionChecked(true);
      }
    };
    checkSession();
    return () => {
      active = false;
    };
  }, [apiFetch]);

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
    if (!sessionChecked) return;
    const targetNav = pathToNavId(pathname);
    setActiveNav(targetNav);
    const desired = token
      ? navIdToPath[targetNav]
      : pathname === "/login" || pathname === "/authentication" || pathname === "/authencation"
        ? pathname
        : "/authencation";
    if (pathname !== desired) {
      window.history.replaceState(null, "", desired);
      setPathname(desired);
    }
  }, [token, pathname, sessionChecked]);

  useEffect(() => {
    if (!sessionChecked) return;
    if (sessionKey === lastSessionRef.current) return;
    setOverview(createEmptyOverview());
    setFunpayStats(createEmptyFunpayStats());
    setAccountsTable([]);
    setRentalsTable([]);
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
    lastSessionRef.current = sessionKey;
  }, [sessionChecked, sessionKey]);

  const handleRegister = async (payload: { username: string; password: string; golden_key: string }) => {
    try {
      const data = await apiFetch<{ username: string }>("/api/auth/register", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setToken("session");
      setProfileName(data.username || payload.username);
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

  const loadOverview = useCallback(async () => {
    try {
      const [stats, activeRentals, accounts] = await Promise.all([
        apiFetch<Record<string, number>>("/api/stats").catch(() => null),
        apiFetch<{ items: unknown[] }>("/api/rentals/active?fast=1&expand=presence,chat").catch(() => ({ items: [] })),
        apiFetch<{ items: unknown[] }>(
          "/api/accounts?fast=1&include_steamid=1&include_mafile=1"
        ).catch(() => ({ items: [] })),
      ]);

      const totalAccounts =
        stats?.accounts_total ??
        (Array.isArray(accounts?.items) ? accounts.items.length : null);

      const active =
        stats?.active_rentals ??
        (Array.isArray(activeRentals?.items) ? activeRentals.items.length : null);

      const past24 = stats?.rentals_last24 ?? stats?.recent_rentals ?? null;
      const totalHours = stats?.total_hours ?? null;

      const freeAccounts =
        stats?.free_accounts ??
        (totalAccounts != null && active != null ? Math.max(totalAccounts - active, 0) : null);

      setOverview({
        totalAccounts,
        activeRentals: active,
        freeAccounts,
        past24,
        totalHours,
      });

      const accountsList = Array.isArray(accounts?.items) ? (accounts.items as any[]) : [];
      const accountSteamMap = new Map<string, string>();

      // inventory table
      if (accountsList.length) {
        const mappedAccounts = accountsList.map((a, idx) => {
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
          };
        });
        setAccountsTable(mappedAccounts);
      }

      // rentals table
      if (Array.isArray(activeRentals?.items)) {
        setRentalsTable(
          (activeRentals.items as any[]).map((r, idx) => {
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
            };
          })
        );
      }
    } catch {
      // ignore overview load errors
    }
  }, [apiFetch]);

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

  const loadChats = useCallback(
    async (revalidate = false) => {
      if (!token) return;
      await swrFetch<ChatItem[]>({
        key: scopedKey(CHAT_LIST_CACHE_KEY),
        url: "/api/chats?fast=1",
        ttl: CACHE_TTLS.chatList,
        revalidate,
        onLoading: setChatListLoading,
        onData: (items) => {
          setChats(items);
          if ((selectedChat === null || selectedChat === undefined) && items.length) {
            setSelectedChat(items[0].id);
          }
        },
        map: mapChatItems,
      });
    },
    [token, selectedChat, swrFetch, mapChatItems, scopedKey]
  );

  const loadChatHistory = useCallback(
    async (chatId: string | number | null, revalidate = false) => {
      if (!token || !chatId) return;
      const cacheKey = scopedKey(`${CHAT_HISTORY_CACHE_PREFIX}${chatId}`);
      await swrFetch<ChatMessage[]>({
        key: cacheKey,
        url: `/api/chats/${chatId}/history?limit=80`,
        ttl: CACHE_TTLS.chatHistory,
        revalidate,
        onLoading: setChatLoading,
        onData: setChatMessages,
        map: mapChatMessages,
      });
    },
    [token, swrFetch, mapChatMessages, scopedKey]
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

  useEffect(() => {
    if (token) {
      loadOverview();
      loadNotifications();
      loadChats(false);
    }
  }, [token, sessionKey, loadOverview, loadNotifications, loadChats]);

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

  // load chat list when on chats tab
  useEffect(() => {
    if (!token || activeNav !== "chats") return;
    loadChats(true);
  }, [token, sessionKey, activeNav, loadChats]);

  // load chat history when selection changes
  useEffect(() => {
    if (!token || activeNav !== "chats") return;
    loadChatHistory(selectedChat, true);
  }, [token, sessionKey, activeNav, selectedChat, loadChatHistory]);

  useEffect(() => {
    if (!token) {
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
      source = new EventSource("/api/stream/chats");
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
        setChats(items);
        writeCache(scopedKey(CHAT_LIST_CACHE_KEY), items);
        if (items.length) {
          setSelectedChat((prev) => (prev === null || prev === undefined ? items[0].id : prev));
        }

        const nowTs = Date.now();
        const prevCounts = adminCallCountsRef.current;
        const nextCounts: Record<string, number> = {};
        items.forEach((chat) => {
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
  }, [token, sessionKey, activeNav, mapChatItems, scopedKey, showToast]);

  useEffect(() => {
    if (!token || activeNav !== "chats" || !selectedChat) {
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
      source = new EventSource(`/api/stream/chats/${selectedChat}/history`);
    } catch {
      return;
    }
    if (chatHistoryStreamRef.current) {
      chatHistoryStreamRef.current.close();
    }
    chatHistoryStreamRef.current = source;

    const handleHistory = (event: MessageEvent) => {
      try {
        const payload = JSON.parse(event.data || "{}");
        const items = mapChatMessages(payload);
        setChatMessages(items);
        writeCache(scopedKey(`${CHAT_HISTORY_CACHE_PREFIX}${selectedChat}`), items);
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
  }, [token, sessionKey, activeNav, selectedChat, mapChatMessages]);

  useEffect(() => {
    if (!token || activeNav !== "chats" || !selectedChat) return;
    const chatIdValue = selectedChat;
    const chatKey = String(chatIdValue);
    const existing = adminCallCountsRef.current[chatKey] || 0;
    if (!existing) return;
    const clearCall = async () => {
      try {
        await apiFetch(`/api/admin-calls/${encodeURIComponent(String(chatIdValue))}/clear`, { method: "POST" });
        adminCallCountsRef.current[chatKey] = 0;
        setChats((prev) =>
          prev.map((chat) =>
            String(chat.id) === chatKey ? { ...chat, adminCalls: 0, adminLastCalledAt: null } : chat
          )
        );
      } catch {
        // ignore clear errors
      }
    };
    clearCall();
  }, [token, activeNav, selectedChat, apiFetch]);

  useEffect(() => {
    if (!token || activeNav !== "blacklist") return;
    const handle = setTimeout(() => {
      loadBlacklist(blacklistQuery, true);
    }, 250);
    return () => clearTimeout(handle);
  }, [token, sessionKey, activeNav, blacklistQuery, loadBlacklist]);

  useEffect(() => {
    if (!token || activeNav !== "funpay-stats") return;
    loadFunpayStats(false, true);
  }, [token, sessionKey, activeNav, loadFunpayStats]);

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
      loadFunpayStats(false, true);
      return;
    }
    if (activeNav === "chats") {
      loadChats(true);
      loadChatHistory(selectedChat, true);
      return;
    }
    if (activeNav === "orders") {
      loadOrdersHistory(ordersQuery.trim(), true);
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
    } else if (activeNav === "chats" && !chatStreamActive) {
      intervalId = window.setInterval(() => {
        loadChats(true);
        loadChatHistory(selectedChat, true);
      }, 15000);
    } else if (activeNav === "orders") {
      intervalId = window.setInterval(() => {
        loadOrdersHistory(ordersQuery.trim(), true);
      }, 60000);
    } else if (activeNav === "funpay-stats") {
      intervalId = window.setInterval(() => {
        loadFunpayStats(false, true);
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
    loadChats,
    loadChatHistory,
    loadOrdersHistory,
    loadFunpayStats,
  ]);

  useEffect(() => {
    localStorage.setItem("autoRaise", autoRaise ? "1" : "0");
  }, [autoRaise]);

  useEffect(() => {
    localStorage.setItem("autoOnline", autoOnline ? "1" : "0");
  }, [autoOnline]);

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
    nowMs?: number
  ) => {
    let remaining = seconds ?? 0;
    if (startedAt !== null && startedAt !== undefined && seconds != null) {
      const startedAtMs = parseDateTime(startedAt);
      const currentMs = Number.isFinite(nowMs) ? (nowMs as number) : Date.now();
      const elapsed = startedAtMs ? Math.max(0, Math.floor((currentMs - startedAtMs) / 1000)) : 0;
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

  const getMatchSecondsFromPresence = (presence?: PresenceData | null) => {
    if (!presence || !presence.in_match) return null;
    const rawSeconds = Number(presence.match_seconds);
    const baseSeconds = Number.isFinite(rawSeconds)
      ? Math.max(0, Math.floor(rawSeconds))
      : parseMatchTimeSeconds(presence.match_time ?? null);
    return baseSeconds === null ? null : baseSeconds;
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
            const stateLabel = rented ? "Rented out" : "Available";
            const stateClass = rented ? "bg-amber-50 text-amber-700" : "bg-emerald-50 text-emerald-600";
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
            const canAssign = !ownerKey;
            const canExtend = ownerKey && ownerKey !== "other_account";
            const canRelease = !!ownerKey;
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
                        Release the account before assigning a new buyer.
                      </div>
                    )}
                  </div>
                </div>
                <div className="rounded-xl border border-neutral-200 bg-neutral-50 p-4">
                  <div className="mb-2 text-sm font-semibold text-neutral-800">Extend rental</div>
                  <div className="grid grid-cols-2 gap-3">
                    <input
                      value={extendHours}
                      onChange={(e) => setExtendHours(e.target.value)}
                      placeholder="Hours"
                      type="number"
                      min="0"
                      className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 outline-none placeholder:text-neutral-400"
                    />
                    <input
                      value={extendMinutes}
                      onChange={(e) => setExtendMinutes(e.target.value)}
                      placeholder="Minutes"
                      type="number"
                      min="0"
                      className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 outline-none placeholder:text-neutral-400"
                    />
                  </div>
                  <button
                    onClick={handleExtendAccount}
                    disabled={accountActionBusy || !canExtend}
                    className="mt-3 w-full rounded-lg bg-neutral-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-neutral-800 disabled:cursor-not-allowed disabled:bg-neutral-300"
                  >
                    Extend time
                  </button>
                  {!canExtend && (
                    <div className="mt-2 text-xs text-neutral-500">Extension is available only for active rentals.</div>
                  )}
                </div>
                <div className="rounded-xl border border-neutral-200 bg-neutral-50 p-4">
                  <div className="mb-2 text-sm font-semibold text-neutral-800">End rental</div>
                  <p className="text-xs text-neutral-500">Clears the owner and stops the rental immediately.</p>
                  <button
                    onClick={handleReleaseAccount}
                    disabled={accountActionBusy || !canRelease}
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
            Select an account to unlock rental actions.
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
            const presenceLabel = presence?.in_match
              ? "In match"
              : presence?.in_game
                ? "In game"
                : "Offline";
            const pill = statusPill(presenceLabel);
            const timeLeft =
              selectedRental.durationSec != null && selectedRental.startedAt != null
                ? formatDuration(selectedRental.durationSec, selectedRental.startedAt, now)
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
                    <span>
                      Started: {selectedRental.startedAt ? formatStartTime(selectedRental.startedAt) : "-"}
                    </span>
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

  const ToggleRow: React.FC<{
    label: string;
    enabled: boolean;
    onChange: (next: boolean) => void;
  }> = ({ label, enabled, onChange }) => (
    <button
      type="button"
      onClick={() => onChange(!enabled)}
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
      await apiFetch("/api/accounts", { method: "POST", body: JSON.stringify(payload) });
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

  const handleExtendAccount = async () => {
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
    const hoursValue = parseInt(extendHours, 10);
    const minutesValue = parseInt(extendMinutes, 10);
    const hours = Number.isFinite(hoursValue) && hoursValue > 0 ? hoursValue : 0;
    const minutes = Number.isFinite(minutesValue) && minutesValue > 0 ? minutesValue : 0;
    if (!hours && !minutes) {
      showToast("Enter a time extension.", "error");
      return;
    }
    setAccountActionBusy(true);
    try {
      await apiFetch(`/api/accounts/${encodeURIComponent(String(accountId))}/extend`, {
        method: "POST",
        body: JSON.stringify({ hours, minutes }),
      });
      showToast("Rental extended.");
      setExtendHours("");
      setExtendMinutes("");
      await Promise.all([loadOverview()]);
    } catch (error) {
      showToast((error as Error).message || "Failed to extend rental.", "error");
    } finally {
      setAccountActionBusy(false);
    }
  };

  const handleReleaseAccount = async () => {
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
      await apiFetch(`/api/accounts/${encodeURIComponent(String(accountId))}/release`, { method: "POST" });
      showToast("Rental released.");
      await Promise.all([loadOverview()]);
    } catch (error) {
      showToast((error as Error).message || "Failed to release rental.", "error");
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
      await apiFetch(`/api/accounts/${encodeURIComponent(String(accountId))}/release`, { method: "POST" });
      showToast("Rental released.");
      await Promise.all([loadOverview()]);
    } catch (error) {
      showToast((error as Error).message || "Failed to release rental.", "error");
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

  const sendChatMessage = async () => {
    const text = chatInput.trim();
    if (!text || selectedChat === null || selectedChat === undefined) {
      showToast("Select a chat and type a message.", "error");
      return;
    }
    setChatInput("");
    const optimistic: ChatMessage = {
      id: `local-${Date.now()}`,
      author: "You",
      text,
      sentAt: new Date().toLocaleTimeString(),
      byBot: true,
    };
    setChatMessages((prev) => [...prev, optimistic]);
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

  if (!sessionChecked) {
    return null;
  }

  return (
    <>
      <AnimatePresence mode="wait">
        {!token ? (
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
                  )}
                  {activeNav === "funpay-stats" ? null : activeNav === "chats" ? (
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
                                  onClick={() => setSelectedChat(chat.id)}
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
                          <div className="flex-1 space-y-3 overflow-y-auto pr-2 min-h-0">
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
                      className="mt-8 grid gap-6 lg:grid-cols-[420px_auto] items-start"
                    >
                      <div className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm shadow-neutral-200/70">
                        <div className="mb-3">
                          <h3 className="text-lg font-semibold text-neutral-900">Funpay Profile Settings</h3>
                        </div>
                        <div className="space-y-3 max-h-[640px] overflow-y-auto pr-1">
                          <ToggleRow label="Auto Raise" enabled={autoRaise} onChange={setAutoRaise} />
                          <ToggleRow label="Auto Online" enabled={autoOnline} onChange={setAutoOnline} />
                        </div>
                      </div>
                      <div className="space-y-4">
                        <div className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm shadow-neutral-200/70">
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
                            const presenceLabel = presence?.in_match
                              ? "In match"
                              : presence?.in_game
                                ? "In game"
                                : "Offline";
                            const pill = statusPill(presenceLabel);
                            const adminCalls = Number(r.adminCalls || 0);
                            const hasAdminCall = adminCalls > 0;
                            const timeLeft =
                              r.durationSec != null && r.startedAt != null
                                ? formatDuration(r.durationSec, r.startedAt, now)
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
                                <span className="min-w-0 truncate text-neutral-800">{r.accountName || ""}</span>
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
                            <div className="rounded-xl border border-dashed border-neutral-200 bg-neutral-50 px-4 py-6 text-center text-sm text-neutral-500">
                              No active rentals yet.
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
                            <div className="space-y-3">
                              <div className="grid gap-3 md:grid-cols-[1fr_auto]">
                                <input
                                  value={blacklistOrderId}
                                  onChange={(e) => setBlacklistOrderId(e.target.value)}
                                  placeholder="Order ID (optional)"
                                  className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 outline-none placeholder:text-neutral-400"
                                />
                                <button
                                  onClick={handleResolveBlacklistOrder}
                                  disabled={blacklistResolving}
                                  className="rounded-lg border border-neutral-200 bg-white px-3 py-2 text-xs font-semibold text-neutral-700 transition hover:bg-neutral-100 disabled:cursor-not-allowed disabled:text-neutral-400"
                                >
                                  Find buyer
                                </button>
                              </div>
                              <input
                                value={blacklistOwner}
                                onChange={(e) => setBlacklistOwner(e.target.value)}
                                placeholder="Buyer username"
                                className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 outline-none placeholder:text-neutral-400"
                              />
                              <input
                                value={blacklistReason}
                                onChange={(e) => setBlacklistReason(e.target.value)}
                                placeholder="Reason (optional)"
                                className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 outline-none placeholder:text-neutral-400"
                              />
                              <button
                                onClick={handleAddBlacklist}
                                disabled={blacklistResolving || (!blacklistOwner.trim() && !blacklistOrderId.trim())}
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
                              className="w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700 outline-none placeholder:text-neutral-400"
                            />
                            <div className="mt-3 flex flex-wrap gap-2">
                              <button
                                onClick={handleRemoveSelected}
                                disabled={!blacklistSelected.length}
                                className="rounded-lg border border-neutral-200 bg-white px-3 py-2 text-xs font-semibold text-neutral-700 transition hover:bg-neutral-100 disabled:cursor-not-allowed disabled:text-neutral-400"
                              >
                                Unblacklist selected
                              </button>
                              <button
                                onClick={handleClearBlacklist}
                                disabled={!blacklistEntries.length}
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
                                  const stateLabel = rented ? "Rented out" : "Available";
                                  const stateClass = rented ? "bg-amber-50 text-amber-700" : "bg-emerald-50 text-emerald-600";
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
                                      <span
                                        className="min-w-0 truncate font-semibold leading-tight text-neutral-900"
                                        title={acc.name || "Account"}
                                      >
                                        {acc.name || "Account"}
                                      </span>
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
                                  <div className="rounded-xl border border-dashed border-neutral-200 bg-neutral-50 px-4 py-6 text-center text-sm text-neutral-500">
                                    No accounts loaded yet.
                                  </div>
                                )}
                              </div>
                            </div>
                          </div>
                        </div>
                        {renderAccountActionsPanel("Rental controls")}
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
                            const stateLabel = rented ? "Rented out" : "Available";
                            const stateClass = rented ? "bg-amber-50 text-amber-700" : "bg-emerald-50 text-emerald-600";
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
                                <span className="min-w-0 truncate font-semibold leading-tight text-neutral-900" title={acc.name || "Account"}>
                                  {acc.name || "Account"}
                                </span>
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
                            <div className="rounded-xl border border-dashed border-neutral-200 bg-neutral-50 px-4 py-6 text-center text-sm text-neutral-500">
                              No accounts loaded yet.
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
                            const timer = getMatchTimeLabel(presence);
                            const presenceLabel = presence?.in_match
                              ? "In match"
                              : presence?.in_game
                                ? "In game"
                                : "Offline";
                            const pill = statusPill(presenceLabel);
                            const adminCalls = Number(r.adminCalls || 0);
                            const hasAdminCall = adminCalls > 0;
                            const timeLeft =
                              r.durationSec != null && r.startedAt != null
                                ? formatDuration(r.durationSec, r.startedAt, now)
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
                                <span className="min-w-0 truncate text-neutral-800">{r.accountName || ""}</span>
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
                            <div className="rounded-xl border border-dashed border-neutral-200 bg-neutral-50 px-4 py-6 text-center text-sm text-neutral-500">
                              No active rentals yet.
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
                  )}
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
  match_time?: string | null;
  match_seconds?: number | null;
  fetched_at?: number | null;
};
