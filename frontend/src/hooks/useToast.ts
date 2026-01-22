import { useCallback, useState } from "react";

export type ToastState = {
  message: string;
  type: "error" | "success";
};

export const useToast = () => {
  const [toast, setToast] = useState<ToastState | null>(null);

  const showToast = useCallback((message: string, type: "error" | "success" = "success") => {
    setToast({ message, type });
    window.setTimeout(() => setToast(null), 2800);
  }, []);

  return { toast, showToast };
};
