import React, { useEffect, useMemo, useState } from "react";
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
};

type AccountRow = {
  id?: string | number;
  login?: string;
  password?: string;
  steamId?: string;
  name?: string;
  mmr?: number | string | null;
};

  type RentalRow = {
    id?: string | number;
    accountName?: string;
    buyer?: string;
    durationSec?: number;
    startedAt?: string;
    status?: string;
    hero?: string;
    steamId?: string;
    presence?: PresenceData | null;
    presenceLabel?: string | null;
  };

  type NotificationItem = {
  id?: string | number;
  level?: string;
  message?: string;
  createdAt?: string;
  owner?: string;
  accountId?: string | number;
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
  { id: "inventory", label: "Inventory", Icon: InventoryIcon },
  { id: "lots", label: "Lots", Icon: LotsIcon },
  { id: "chats", label: "Chats", Icon: ChatsIcon },
  { id: "add", label: "Add Account", Icon: AddIcon },
  { id: "notifications", label: "Notifications", Icon: NotificationsIcon },
  { id: "settings", label: "Settings", Icon: SettingsIcon },
];

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

const App: React.FC = () => {
  const [token, setToken] = useState(() => sessionStorage.getItem("adminToken") || "");
  const [pathname, setPathname] = useState(() => window.location.pathname);
  const [activeNav, setActiveNav] = useState<string>("overview");
  const [overview, setOverview] = useState<OverviewData>({
    totalAccounts: null,
    activeRentals: null,
    freeAccounts: null,
    past24: null,
  });
  const [accountsTable, setAccountsTable] = useState<AccountRow[]>([]);
  const [rentalsTable, setRentalsTable] = useState<RentalRow[]>([]);
  const [chats, setChats] = useState<ChatItem[]>([]);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [selectedChat, setSelectedChat] = useState<string | number | null>(null);
  const [chatLoading, setChatLoading] = useState(false);
  const [chatListLoading, setChatListLoading] = useState(false);
  const [chatInput, setChatInput] = useState("");
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [autoRaise, setAutoRaise] = useState<boolean>(() => localStorage.getItem("autoRaise") === "1");
  const [autoOnline, setAutoOnline] = useState<boolean>(() => localStorage.getItem("autoOnline") === "1");
  const [uiMode, setUiMode] = useState<"light" | "dark">(
    () => (localStorage.getItem("uiMode") as "light" | "dark") || "light"
  );
  const [submittingAccount, setSubmittingAccount] = useState(false);
  const [presenceCache, setPresenceCache] = useState<Record<string, PresenceData>>({});
  const [presenceURL, setPresenceURL] = useState<string>(() => PRESENCE_BASE);
  const [, setTick] = useState(0);
  const { toast, showToast } = useToast();

  const api = useMemo(
    () =>
      createApiClient({
        getToken: () => token,
        onUnauthorized: () => {
          sessionStorage.removeItem("adminToken");
          sessionStorage.removeItem("adminUser");
          setToken("");
        },
      }),
    [token]
  );

  const apiFetch = api.apiFetch;

  useEffect(() => {
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
  }, [token, pathname]);

  // fetch presence for rentals
  useEffect(() => {
    const ids = rentalsTable
      .filter((r) => !r.presence)
      .map((r) => r.steamId)
      .filter((id): id is string => !!id && !(presenceCache as any)[id]);
    if (!ids.length) return;
    const controller = new AbortController();
    const base = PRESENCE_BASE;
    setPresenceURL(base);
    Promise.all(
      ids.map(async (id) => {
        try {
          const res = await fetch(`${base}/${id}`, { signal: controller.signal });
          if (!res.ok) throw new Error("bad status");
          const data = (await res.json()) as PresenceData;
          setPresenceCache((prev) => ({ ...prev, [id]: data }));
        } catch {
          // ignore per-id errors
        }
      })
    );
    return () => controller.abort();
  }, [rentalsTable]);

  const handleRegister = async (payload: { username: string; password: string; golden_key: string }) => {
    try {
      const data = await apiFetch<{ token: string; username: string }>("/api/auth/register", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      sessionStorage.setItem("adminToken", data.token);
      sessionStorage.setItem("adminUser", data.username);
      setToken(data.token);
      showToast("??????????? ?????????, ?? ?????.");
    } catch (error) {
      showToast((error as Error).message || "?? ??????? ??????????????????", "error");
    }
  };

  const handleLogin = async (payload: { username: string; password: string }) => {
    try {
      const data = await apiFetch<{ token: string; username: string }>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      sessionStorage.setItem("adminToken", data.token);
      sessionStorage.setItem("adminUser", data.username);
      setToken(data.token);
      showToast("???? ????????.");
    } catch (error) {
      showToast((error as Error).message || "?? ??????? ?????", "error");
    }
  };

  useEffect(() => {
    const loadOverview = async () => {
      try {
        const [stats, activeRentals, accounts] = await Promise.all([
          apiFetch<Record<string, number>>("/api/stats").catch(() => null),
          apiFetch<{ items: unknown[] }>("/api/rentals/active?fast=1&expand=presence").catch(() => ({ items: [] })),
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

        const past24 = stats?.rentals_last24 ?? null;

        const freeAccounts =
          stats?.free_accounts ??
          (totalAccounts != null && active != null ? Math.max(totalAccounts - active, 0) : null);

        setOverview({
          totalAccounts,
          activeRentals: active,
          freeAccounts,
          past24,
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
            return {
              id: a.id ?? idx,
              name,
              login,
              password: a.password ?? a.pass ?? "",
              steamId,
              mmr: a.mmr ?? a.mmr_estimate ?? a.rank ?? a.elo ?? null,
            };
          });
          setAccountsTable(mappedAccounts);
        }

        // rentals table
        if (Array.isArray(activeRentals?.items)) {
          setRentalsTable(
            (activeRentals.items as any[]).map((r, idx) => {
              const hasPresence =
                r.in_match !== undefined ||
                r.in_game !== undefined ||
                r.match_time ||
                r.hero_name ||
                r.presence_label;
              const presence = hasPresence
                ? {
                    in_match: !!r.in_match,
                    in_game: !!r.in_game,
                    hero_name: r.hero_name ?? null,
                    match_time: r.match_time ?? null,
                  }
                : null;
              const derivedStatus = presence
                ? presence.in_match
                  ? "In match"
                  : presence.in_game
                    ? "In game"
                    : "Offline"
                : r.status ?? r.presence ?? "";
              return {
                id: r.id ?? idx,
                accountName: r.account_name ?? r.login ?? `Rental ${idx + 1}`,
                buyer: r.buyer ?? r.rented_by ?? "",
                durationSec: r.duration ?? r.duration_sec ?? r.seconds ?? null,
                startedAt: r.started_at ?? r.start_time ?? r.created_at,
                status: derivedStatus,
                hero: r.hero ?? r.character ?? "",
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
              };
            })
          );
        }
      } catch {
        // ignore overview load errors
      }
    };

    const loadNotifications = async () => {
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
    };

    if (token) {
      loadOverview();
      loadNotifications();
    }
  }, [token, apiFetch]);

  // load chat list when on chats tab
  useEffect(() => {
    if (!token || activeNav !== "chats") return;
    loadChats();
  }, [token, activeNav]);

  // load chat history when selection changes
  useEffect(() => {
    if (!token || activeNav !== "chats") return;
    loadChatHistory(selectedChat);
  }, [token, activeNav, selectedChat]);

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

  const formatDuration = (seconds: number | null | undefined, startedAt?: string) => {
    let remaining = seconds ?? 0;
    if (startedAt && seconds != null) {
      const elapsed = Math.max(0, Math.floor((Date.now() - new Date(startedAt).getTime()) / 1000));
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

  const loadChats = async () => {
    if (!token) return;
    setChatListLoading(true);
    try {
      const data = await apiFetch<{ items: any[] }>("/api/chats?fast=1").catch(() => ({ items: [] }));
      const mapped: ChatItem[] = (data.items || []).map((c, idx) => ({
        id: c.id ?? idx,
        name: c.name || c.chat_name || `Chat ${idx + 1}`,
        last: c.last_message_text || c.preview || "",
        time: c.last_message_time || c.time || "",
        unread: !!c.unread,
      }));
      setChats(mapped);
      if ((selectedChat === null || selectedChat === undefined) && mapped.length) {
        setSelectedChat(mapped[0].id);
      }
    } finally {
      setChatListLoading(false);
    }
  };

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

  const loadChatHistory = async (chatId: string | number | null) => {
    if (!token || !chatId) return;
    setChatLoading(true);
    try {
      const data = await apiFetch<{ items: any[] }>(`/api/chats/${chatId}/history?limit=80`).catch(() => ({ items: [] }));
      const mapped: ChatMessage[] = (data.items || []).map((m, idx) => ({
        id: m.id ?? idx,
        author: m.author || m.user || (m.by_bot ? "Bot" : "User"),
        text: m.text || m.body || "",
        sentAt: m.sent_time || m.sent_at || m.time || "",
        byBot: !!m.by_bot,
      }));
      setChatMessages(mapped);
    } finally {
      setChatLoading(false);
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
      loadChatHistory(selectedChat);
    } catch (error) {
      showToast((error as Error).message || "Failed to send", "error");
      setChatMessages((prev) => prev.filter((m) => m.id !== optimistic.id));
    }
  };

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
                <nav className="relative mt-8 flex flex-1 flex-col space-y-2">
                  <AnimatePresence>
                    {NAV_ITEMS.filter((i) => i.id !== "settings").map((item) => {
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
                  {(() => {
                    const item = NAV_ITEMS.find((i) => i.id === "settings");
                    if (!item) return null;
                    const isActive = activeNav === item.id;
                    return (
                      <AnimatePresence>
                        <motion.button
                          key={item.id}
                          type="button"
                          onClick={() => {
                            setActiveNav(item.id);
                            const nextPath = navIdToPath[item.id] || "/dashboard";
                            window.history.replaceState(null, "", nextPath);
                            setPathname(nextPath);
                          }}
                          className="relative mt-auto flex w-full items-center gap-3 overflow-hidden rounded-xl px-4 py-3 text-left text-sm font-semibold transition focus:outline-none"
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
                      </AnimatePresence>
                    );
                  })()}
                </nav>
              </aside>
              <main className="relative flex-1 bg-white">
                <div className="absolute left-0 top-0 h-full w-px bg-neutral-200" />
                <motion.div
                  initial={{ opacity: 0, y: 16 }}
                  animate={{ opacity: 1, y: 0, transition: { duration: 0.7, ease: EASE } }}
                  className="pl-10 pr-10 pt-5 pb-12"
                >
                  <div className="flex items-center justify-between gap-6 border-b border-neutral-200 pb-4">
                    <div>
                      <h1 className="text-2xl font-semibold text-neutral-900">
                        {NAV_ITEMS.find((n) => n.id === activeNav)?.label || "Dashboard"}
                      </h1>
                    </div>
                    <label className="relative flex h-11 w-80 items-center gap-3 rounded-lg border border-neutral-200 bg-neutral-50 px-4 text-sm text-neutral-500 shadow-sm shadow-neutral-200">
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
                  </div>
                  {(activeNav === "overview" || activeNav === "funpay-stats") && (
                    <div className="mt-6">
                      <div className="mb-4 text-lg font-semibold text-neutral-800">
                        {activeNav === "funpay-stats" ? "Funpay Statistics" : "Overview"}
                      </div>
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
                      {activeNav === "funpay-stats" && (
                        <div className="mt-6 grid gap-4 lg:grid-cols-3">
                          <div className="rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm shadow-neutral-200/70">
                            <div className="text-sm font-semibold text-neutral-700">Active Rental Ratio</div>
                            <div className="mt-2 text-3xl font-bold text-neutral-900">
                              {overview.totalAccounts && overview.activeRentals
                                ? `${Math.round((overview.activeRentals / overview.totalAccounts) * 100)}%`
                                : "–"}
                            </div>
                            <div className="mt-1 text-xs text-neutral-500">Active / Total accounts</div>
                          </div>
                          <div className="rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm shadow-neutral-200/70">
                            <div className="text-sm font-semibold text-neutral-700">Free Accounts</div>
                            <div className="mt-2 text-3xl font-bold text-neutral-900">
                              {overview.freeAccounts === null ? "–" : overview.freeAccounts}
                            </div>
                            <div className="mt-1 text-xs text-neutral-500">Available for issuance</div>
                          </div>
                          <div className="rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm shadow-neutral-200/70">
                            <div className="text-sm font-semibold text-neutral-700">Rentals Last 24h</div>
                            <div className="mt-2 text-3xl font-bold text-neutral-900">
                              {overview.past24 === null ? "0" : overview.past24}
                            </div>
                            <div className="mt-1 text-xs text-neutral-500">Completed in past day</div>
                          </div>
                        </div>
                      )}
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
                              loadChats();
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
                                      : "border-neutral-100 bg-white hover:border-neutral-200"
                                  }`}
                                >
                                  <div className="min-w-0">
                                    <div className="flex items-center gap-2">
                                      <span className="truncate font-semibold text-neutral-900">{chat.name}</span>
                                      {chat.unread && (
                                        <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-600">
                                          new
                                        </span>
                                      )}
                                    </div>
                                    <p className="truncate text-xs text-neutral-500">{chat.last || "No messages yet"}</p>
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
                                  }`}
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
                        <div className="space-y-3">
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
                        <div className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm shadow-neutral-200/70">
                          <div className="mb-4 flex items-center justify-between">
                            <div>
                              <h3 className="text-lg font-semibold text-neutral-900">System notifications</h3>
                              <p className="text-sm text-neutral-500">Latest events from the bot.</p>
                            </div>
                          </div>
                          <div className="space-y-3">
                            {notifications.slice(0, 6).map((n) => (
                              <div
                                key={n.id}
                                className="rounded-xl border border-neutral-100 bg-neutral-50 px-4 py-3 text-sm text-neutral-800"
                              >
                                <div className="mb-1 flex items-center gap-2 text-xs uppercase tracking-wide text-neutral-500">
                                  <span className="font-semibold">{n.level?.toUpperCase() || "INFO"}</span>
                                  <span>{n.createdAt ? new Date(n.createdAt).toLocaleString() : ""}</span>
                                </div>
                                <div className="text-neutral-900">{n.message || "—"}</div>
                                <div className="text-xs text-neutral-500">
                                  Owner: {n.owner || "—"} • Account: {n.accountId || "—"}
                                </div>
                              </div>
                            ))}
                            {notifications.length === 0 && (
                              <div className="rounded-xl border border-dashed border-neutral-200 bg-neutral-50 px-4 py-6 text-center text-sm text-neutral-500">
                                No notifications yet.
                              </div>
                            )}
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
                          <div className="mt-3 text-sm text-neutral-500">Creating account…</div>
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
                        <div className="text-sm text-neutral-500">Updated live every minute</div>
                      </div>
                      <div className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm shadow-neutral-200/70">
                        <div className="grid grid-cols-7 gap-2 text-xs font-semibold text-neutral-500">
                          <span>ID</span>
                          <span>Account</span>
                          <span>Buyer</span>
                          <span>Started</span>
                          <span>Match Time</span>
                          <span>Hero</span>
                          <span className="text-right">Presence</span>
                        </div>
                        <div className="mt-3 space-y-3 overflow-y-auto pr-1" style={{ maxHeight: "640px" }}>
                          {rentalsTable.map((r, idx) => {
                            const pill = statusPill(r.status);
                            const presence = r.presence ?? (r.steamId ? presenceCache[r.steamId] : null);
                            const timer = presence?.match_time || "";
                            const presenceLabel = presence?.in_match
                              ? "In match"
                              : presence?.in_game
                                ? "In game"
                                : r.presenceLabel || pill.label;
                            return (
                              <motion.div
                                key={r.id ?? idx}
                                initial={{ opacity: 0, y: 10 }}
                                animate={{ opacity: 1, y: 0, transition: { duration: 0.25, delay: idx * 0.03, ease: EASE } }}
                                className="grid grid-cols-8 items-center gap-3 rounded-xl border border-neutral-100 bg-neutral-50 px-4 py-4 text-sm shadow-[0_4px_18px_-14px_rgba(0,0,0,0.18)]"
                              >
                                <span className="truncate font-semibold text-neutral-900">{r.id ?? ""}</span>
                                <span className="truncate text-neutral-800">{r.accountName || ""}</span>
                                <span className="truncate text-neutral-700">{r.buyer || ""}</span>
                                <span className="truncate text-neutral-600">
                                  {r.startedAt ? new Date(r.startedAt).toLocaleTimeString() : ""}
                                </span>
                                <span className="truncate font-mono text-neutral-900">
                                  {timer || "—"}
                                </span>
                                <span className="truncate text-neutral-700">{presence?.hero_name || r.hero || ""}</span>
                                <span className={`truncate text-neutral-700`}>
                                  {presenceLabel}
                                </span>
                                <button
                                  type="button"
                                  onClick={() => {
                                    if (r.steamId) {
                                      window.open(`${presenceURL}/${r.steamId}`, "_blank", "noopener");
                                    }
                                  }}
                                  className={`justify-self-end rounded-full px-3 py-1 text-xs font-semibold ${pill.className} ${
                                    r.steamId ? "hover:underline" : ""
                                  }`}
                                >
                                  {presenceLabel}
                                </button>
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
                              <div className="text-neutral-900">{n.message || "—"}</div>
                              <div className="text-xs text-neutral-500">
                                Owner: {n.owner || "—"} • Account: {n.accountId || "—"}
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
                      <div className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm shadow-neutral-200/70">
                        <div className="mb-4 flex items-center justify-between">
                          <h3 className="text-lg font-semibold text-neutral-900">Inventory</h3>
                        </div>
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
                        <div className="mt-3 space-y-3 overflow-x-auto pr-1" style={{ maxHeight: "640px" }}>
                          {accountsTable.map((acc, idx) => {
                            return (
                              <motion.div
                                key={acc.id ?? idx}
                                initial={{ opacity: 0, y: 10 }}
                                animate={{ opacity: 1, y: 0, transition: { duration: 0.25, delay: idx * 0.03, ease: EASE } }}
                                className="grid min-w-full items-center gap-3 rounded-xl border border-neutral-100 bg-neutral-50 px-6 py-4 text-sm shadow-[0_4px_18px_-14px_rgba(0,0,0,0.18)]"
                                style={{ gridTemplateColumns: INVENTORY_GRID }}
                              >
                                <span className="min-w-0 font-semibold text-neutral-900" title={String(acc.id ?? "")}>{acc.id ?? ""}</span>
                                <span className="min-w-0 truncate font-semibold leading-tight text-neutral-900" title={acc.name || "Account"}>
                                  {acc.name || "Account"}
                                </span>
                                <span className="min-w-0 truncate text-neutral-700" title={acc.login || ""}>{acc.login || ""}</span>
                                <span className="min-w-0 truncate text-neutral-700" title={acc.password || ""}>{acc.password || ""}</span>
                                <span className="min-w-0 truncate font-mono text-xs leading-tight text-neutral-800 tabular-nums" title={acc.steamId || ""}>
                                  {acc.steamId || ""}
                                </span>
                                <span className="min-w-0 truncate text-neutral-700" title={acc.mmr ?? ""}>{acc.mmr ?? ""}</span>
                                <span className="justify-self-end rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-600">
                                  Available
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
                    </motion.div>
                  ) : (
                    <div className="mt-8 grid gap-6 lg:grid-cols-2">
                      <div className="min-h-[520px] rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm shadow-neutral-200/70">
                        <div className="mb-4 flex items-center justify-between">
                          <h3 className="text-lg font-semibold text-neutral-900">Inventory</h3>
                        </div>
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
                        <div className="mt-3 space-y-3 overflow-y-auto pr-1" style={{ maxHeight: "640px" }}>
                          {accountsTable.map((acc, idx) => {
                            return (
                              <motion.div
                                key={acc.id ?? idx}
                                initial={{ opacity: 0, y: 10 }}
                                animate={{ opacity: 1, y: 0, transition: { duration: 0.25, delay: idx * 0.03, ease: EASE } }}
                                className="grid items-center gap-3 rounded-xl border border-neutral-100 bg-neutral-50 px-6 py-4 text-sm shadow-[0_4px_18px_-14px_rgba(0,0,0,0.18)]"
                                style={{ gridTemplateColumns: INVENTORY_GRID, minWidth: "100%" }}
                              >
                                <span className="min-w-0 font-semibold text-neutral-900" title={String(acc.id ?? "")}>{acc.id ?? ""}</span>
                                <span className="min-w-0 truncate font-semibold leading-tight text-neutral-900" title={acc.name || "Account"}>
                                  {acc.name || "Account"}
                                </span>
                                <span className="min-w-0 truncate text-neutral-700" title={acc.login || ""}>{acc.login || ""}</span>
                                <span className="min-w-0 truncate text-neutral-700" title={acc.password || ""}>{acc.password || ""}</span>
                                <span className="min-w-0 truncate font-mono text-xs leading-tight text-neutral-800 tabular-nums" title={acc.steamId || ""}>
                                  {acc.steamId || ""}
                                </span>
                                <span className="min-w-0 truncate text-neutral-700" title={acc.mmr ?? ""}>{acc.mmr ?? ""}</span>
                                <span className="justify-self-end rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-600">
                                  Available
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
                      <div className="min-h-[520px] rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm shadow-neutral-200/70">
                        <div className="mb-4 flex items-center justify-between">
                          <h3 className="text-lg font-semibold text-neutral-900">Active rentals</h3>
                          <button className="rounded-lg border border-neutral-200 bg-neutral-50 px-3 py-2 text-xs text-neutral-600">Status</button>
                        </div>
                        <div className="grid grid-cols-8 gap-2 text-xs font-semibold text-neutral-500">
                          <span>ID</span>
                          <span>Account</span>
                          <span>Buyer</span>
                          <span>Started</span>
                          <span>Match Time</span>
                          <span>Hero</span>
                          <span>Status</span>
                          <span className="text-right">Presence</span>
                        </div>
                        <div className="mt-3 space-y-3 overflow-y-auto pr-1" style={{ maxHeight: "640px" }}>
                          {rentalsTable.map((r, idx) => {
                            const pill = statusPill(r.status);
                            const presence = r.presence ?? (r.steamId ? presenceCache[r.steamId] : null);
                            const timer = presence?.match_time || "";
                            const presenceLabel = presence?.in_match
                              ? "In match"
                              : presence?.in_game
                                ? "In game"
                                : r.presenceLabel || pill.label;
                            return (
                              <motion.div
                                key={r.id ?? idx}
                                initial={{ opacity: 0, y: 10 }}
                                animate={{ opacity: 1, y: 0, transition: { duration: 0.25, delay: idx * 0.03, ease: EASE } }}
                                className="grid grid-cols-7 items-center gap-3 rounded-xl border border-neutral-100 bg-neutral-50 px-4 py-4 text-sm shadow-[0_4px_18px_-14px_rgba(0,0,0,0.18)]"
                              >
                                <span className="truncate font-semibold text-neutral-900">{r.id ?? ""}</span>
                                <span className="truncate text-neutral-800">{r.accountName || ""}</span>
                                <span className="truncate text-neutral-700">{r.buyer || ""}</span>
                                <span className="truncate text-neutral-600">
                                  {r.startedAt ? new Date(r.startedAt).toLocaleTimeString() : ""}
                                </span>
                                <span className="truncate font-mono text-neutral-900">
                                  {timer || "—"}
                                </span>
                                <span className="truncate text-neutral-700">{presence?.hero_name || r.hero || ""}</span>
                                <button
                                  type="button"
                                  onClick={() => {
                                    if (r.steamId) window.open(`${presenceURL}/${r.steamId}`, "_blank", "noopener");
                                  }}
                                  className={`justify-self-end rounded-full px-3 py-1 text-xs font-semibold ${pill.className} ${
                                    r.steamId ? "hover:underline cursor-pointer" : "opacity-60 cursor-not-allowed"
                                  }`}
                                  title={r.steamId ? `${presenceURL}/${r.steamId}` : "No SteamID found for this rental"}
                                >
                                  {presenceLabel}
                                </button>
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
};
