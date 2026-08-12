import { cn } from "@/lib/utils";

// Reusable Crescendo wordmark. Pass `inverse` for always-dark surfaces (auth
// brand panel, dark heroes). `mark` uses the same lockup at a compact size
// (sidebar). Height is controlled by the caller via className (e.g. "h-7").
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
      src="/crescendo-logo.png"
      alt="Crescendo Worldwide"
      className={cn(
        "w-auto select-none",
        inverse && "brightness-0 invert",
        className,
      )}
    />
  );
}
