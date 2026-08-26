import { cn } from "@/lib/utils";

// SpinSci wordmark from docs/spinsci-design-system. Pass `inverse` on dark surfaces.
export function BrandLogo({
  className,
  inverse = false,
}: {
  className?: string;
  inverse?: boolean;
  /** @deprecated Kept for call-site compatibility; mark uses the same logo. */
  mark?: boolean;
}) {
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={inverse ? "/spinsci-logo-white.svg" : "/spinsci-logo.svg"}
      alt="SpinSci"
      className={cn("w-auto select-none", className)}
    />
  );
}
