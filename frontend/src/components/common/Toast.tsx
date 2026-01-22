import React from "react";
import { ToastState } from "../../hooks/useToast";

const Toast: React.FC<{ toast: ToastState | null }> = ({ toast }) => {
  if (!toast) return null;
  return (
    <div
      className={`toast ${toast.type === "error" ? "border-red-400/60" : "border-amber-500/40"}`}
      role="status"
    >
      {toast.message}
    </div>
  );
};

export default Toast;
