// Shared dark two-column auth shell, used by BOTH the Stack Auth handler
// (/handler/[...stack], cloud) and the local/OSS auth pages (/auth/login,
// /auth/signup). LEFT: a centered card that wraps the auth form (`children`).
// RIGHT (lg+ only): a brand/value panel with the SpinSci logo, proof points,
// and an enterprise CTA block at the bottom (passed in as `enterpriseSlot`).
// Mobile collapses to the single card column.

import type { ReactNode } from "react";

import { BrandLogo } from "@/components/BrandLogo";

const HIGHLIGHTS = [
  "Speech-to-speech",
  "MCP-native",
  "BYOK - any model",
];

export function AuthShell({
  children,
  enterpriseSlot,
}: {
  children: ReactNode;
  enterpriseSlot?: ReactNode;
}) {
  return (
    <div className="grid min-h-screen w-full bg-background lg:grid-cols-[55%_45%]">
      <main className="auth-imprint flex min-h-screen flex-col overflow-y-auto">
        <div className="flex min-h-full items-center justify-center p-6 sm:p-10">
          <div className="w-full max-w-md space-y-6 rounded-2xl border border-border bg-card p-6 spinsci-card-ring sm:p-8">
            <div className="lg:hidden">
              <BrandLogo className="h-7" />
            </div>
            {children}
          </div>
        </div>
      </main>

      <aside className="spinsci-platform-bg relative hidden flex-col justify-between overflow-hidden border-l border-border/60 p-10 lg:flex xl:p-14">
        <div
          aria-hidden
          className="pointer-events-none absolute -right-24 top-1/3 size-[28rem] rounded-full opacity-25 blur-3xl"
          style={{ background: "radial-gradient(circle, var(--spinsci-mint), transparent 70%)" }}
        />

        <div className="relative">
          <BrandLogo inverse className="h-8" />
        </div>

        <div className="relative max-w-md space-y-5">
          <h1 className="font-display text-3xl font-light leading-tight tracking-tight text-white xl:text-4xl">
            Intelligent voice AI for modern enterprises.
          </h1>
          <ul className="flex flex-wrap gap-2">
            {HIGHLIGHTS.map((point) => (
              <li
                key={point}
                className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-xs font-medium text-zinc-300"
              >
                {point}
              </li>
            ))}
          </ul>
        </div>

        <div className="relative mb-12 max-w-md space-y-3 rounded-xl border border-white/10 bg-white/[0.03] p-5 xl:mb-16">
          <h2 className="text-sm font-semibold text-zinc-100">
            Need on-prem, data residency &amp; a data perimeter?
          </h2>
          <p className="text-sm text-zinc-400">
            We deploy voice AI inside your environment for regulated and
            high-scale teams.
          </p>
          {enterpriseSlot}
        </div>
      </aside>
    </div>
  );
}
