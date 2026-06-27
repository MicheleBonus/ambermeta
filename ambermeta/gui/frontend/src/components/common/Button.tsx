import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "ghost" | "danger";
const styles: Record<Variant, string> = {
  primary: "bg-accent text-white hover:brightness-110",
  ghost: "bg-transparent text-ink hover:bg-app border border-hairline",
  danger: "bg-transparent text-error hover:bg-app border border-hairline",
};

export function Button(
  { variant = "ghost", className = "", ...props }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }
) {
  return (
    <button
      {...props}
      className={`px-3 py-1.5 rounded text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed ${styles[variant]} ${className}`}
    />
  );
}
