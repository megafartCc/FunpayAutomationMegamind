export type ApiClientOptions = {
  onUnauthorized: () => void;
};

export const createApiClient = ({ onUnauthorized }: ApiClientOptions) => {
  const apiFetch = async <T>(path: string, options: RequestInit = {}): Promise<T> => {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...(options.headers as Record<string, string> | undefined),
    };
    const response = await fetch(path, { ...options, headers, credentials: "include" });
    if (!response.ok) {
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
          message = "Запрос не выполнен";
        }
      } else {
        message = await response.text();
      }
      throw new Error(message || "Запрос не выполнен");
    }
    if (response.status === 204) {
      return null as T;
    }
    return response.json();
  };

  return { apiFetch };
};
