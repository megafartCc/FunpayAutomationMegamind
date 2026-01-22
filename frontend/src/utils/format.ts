import { Rental } from "../types";

export const formatDate = (value?: string | null): string => {
  if (!value) return "-";
  const parsed = new Date(value.replace(" ", "T"));
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
};

export const getDurationMinutes = (item?: { rental_duration_minutes?: number | null; rental_duration?: number | null }) => {
  if (!item) return 0;
  const minutes = Number(item.rental_duration_minutes);
  if (Number.isFinite(minutes) && minutes > 0) return minutes;
  const hours = Number(item.rental_duration || 0);
  if (!Number.isFinite(hours)) return 0;
  return hours * 60;
};

export const formatDuration = (item?: { rental_duration_minutes?: number | null; rental_duration?: number | null }) => {
  const totalMinutes = getDurationMinutes(item);
  if (!totalMinutes) return "-";
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours && minutes) return `${hours}ч ${minutes}м`;
  if (hours) return `${hours}ч`;
  return `${minutes}м`;
};

export const formatRentalEnd = (start?: string | null, durationMinutes?: number) => {
  if (!start || !durationMinutes) return "-";
  const parsed = new Date(start.replace(" ", "T"));
  if (Number.isNaN(parsed.getTime())) return "-";
  parsed.setMinutes(parsed.getMinutes() + Number(durationMinutes));
  return parsed.toLocaleString();
};

export const formatRemainingSeconds = (seconds?: number | null) => {
  if (!Number.isFinite(seconds)) return "-";
  const total = Math.max(0, Math.floor(seconds || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  return `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
};

export const getRentalEndTimestamp = (item?: Rental) => {
  if (!item) return null;
  const durationMinutes = getDurationMinutes(item);
  const start = item.rental_start;
  if (!start || !durationMinutes) return null;
  const parsed = new Date(start.replace(" ", "T"));
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed.getTime() + Number(durationMinutes) * 60 * 1000;
};

export const parseMatchTimeSeconds = (value?: string | null) => {
  if (!value) return null;
  const parts = String(value).trim().split(":").map((part) => Number(part));
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

export const formatMatchTimeSeconds = (seconds?: number | null) => {
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

export const buildMatchLabel = (heroName?: string | null, matchSeconds?: number | null, matchTime?: string | null) => {
  const extras: string[] = [];
  if (heroName) extras.push(heroName);
  const display =
    typeof matchSeconds === "number" && Number.isFinite(matchSeconds)
      ? formatMatchTimeSeconds(matchSeconds)
      : matchTime;
  if (display) extras.push(display);
  return extras.length ? `В матче(${extras.join(")(")})` : "В матче";
};

export const presenceLabel = (item: Rental, matchSecondsOverride?: number | null) => {
  if (item?.in_match) {
    const rawSeconds =
      typeof matchSecondsOverride === "number" && Number.isFinite(matchSecondsOverride)
        ? matchSecondsOverride
        : Number(item?.match_seconds);
    const matchSeconds = Number.isFinite(rawSeconds)
      ? Math.floor(rawSeconds)
      : parseMatchTimeSeconds(item?.match_time || undefined);
    return buildMatchLabel(item?.hero_name, matchSeconds ?? null, item?.match_time || null);
  }
  if (item?.presence_label) return item.presence_label;
  if (item?.in_game) return "В игре";
  return "Оффлайн";
};
