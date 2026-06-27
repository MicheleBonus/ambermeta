import type { ReactNode } from "react";

type Tone = "neutral" | "valid" | "warning" | "error";
const tones: Record<Tone, string> = {
  neutral: "bg-app text-ink-secondary border-hairline",
  valid: "bg-app text-valid border-valid/30",
  warning: "bg-app text-warning border-warning/30",
  error: "bg-app text-error border-error/30",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded border text-xs ${tones[tone]}`}>
      {children}
    </span>
  );
}
