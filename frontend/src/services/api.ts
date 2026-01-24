export type ApiClientOptions = {
  onUnauthorized: () => void;
  getKeyId?: () => string | number | null | undefined;
};

export const createApiClient = ({ onUnauthorized, getKeyId }: ApiClientOptions) => {
  const apiFetchWithMeta = async <T>(
    path: string,
    options: RequestInit = {}
  ): Promise<{ data: T | null; status: number; headers: Headers }> => {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...(options.headers as Record<string, string> | undefined),
    };
    try {
      const hasKeyHeader = Object.keys(headers).some((key) => {
        const normalized = key.toLowerCase();
        return normalized === "x-key-id" || normalized === "x-fp-key-id";
      });
      if (!hasKeyHeader && typeof window !== "undefined") {
        let keyId: string | number | null | undefined;
        if (getKeyId) {
          try {
            keyId = getKeyId();
          } catch {
            keyId = undefined;
          }
        }
        if (keyId === undefined || keyId === null || keyId === "") {
          keyId = window.localStorage.getItem("fpa_active_key_id");
        }
        if (keyId && keyId !== "all") {
          headers["x-key-id"] = String(keyId);
        }
      }
    } catch {
      // ignore storage errors
    }
    const response = await fetch(path, { ...options, headers, credentials: "include" });
    if (!response.ok && response.status !== 304) {
      if (response.status === 401) {
        onUnauthorized();
      }
      const contentType = response.headers.get("content-type") || "";
      let message = "";
      if (contentType.includes("application/json")) {
        try {
          const data = await response.json();
          if (typeof data?.detail === "string") {
            message = data.detail;
          } else if (data?.detail != null) {
            message = JSON.stringify(data.detail);
          } else {
            message = JSON.stringify(data);
          }
        } catch (error) {
          message = "Ð—Ð°Ð¿Ñ€Ð¾Ñ Ð½Ðµ Ð²Ñ‹Ð¿Ð¾Ð»Ð½ÐµÐ½";
        }
      } else {
        message = await response.text();
      }
      throw new Error(message || "Ð—Ð°Ð¿Ñ€Ð¾Ñ Ð½Ðµ Ð²Ñ‹Ð¿Ð¾Ð»Ð½ÐµÐ½");
    }
    if (response.status === 204 || response.status === 304) {
      return { data: null, status: response.status, headers: response.headers };
    }
    const data = (await response.json()) as T;
    return { data, status: response.status, headers: response.headers };
  };

  const apiFetch = async <T>(path: string, options: RequestInit = {}): Promise<T> => {
    const result = await apiFetchWithMeta<T>(path, options);
    return result.data as T;
  };

  return { apiFetch, apiFetchWithMeta };
};
