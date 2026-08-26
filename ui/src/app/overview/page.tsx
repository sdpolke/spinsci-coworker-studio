"use client";

import {
    ArrowRight,
    Globe,
    Mic,
    Sparkles,
} from "lucide-react";
import Link from "next/link";

import { BrandLogo } from "@/components/BrandLogo";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth";

const STATS = [
    { value: "In + Out", label: "Voice automation" },
    { value: "10+", label: "Telephony integrations" },
    { value: "24/7", label: "Inbound coverage" },
    { value: "BYOK", label: "Any LLM / TTS / STT" },
] as const;

const HIGHLIGHTS = [
    "Outbound dialing & campaigns",
    "Inbound voice support",
    "Warm transfer with full context",
    "Real-time conversation analytics",
] as const;

export default function OverviewPage() {
    const { user, provider } = useAuth();
    const isOSSMode = provider !== "stack";
    const firstName = user?.displayName?.split(" ")[0];

    return (
        <div className="overview-spinsci -mx-4 md:-mx-6">
            <section className="spinsci-platform-bg relative overflow-hidden text-white">
                <div
                    aria-hidden
                    className="pointer-events-none absolute inset-0 opacity-60"
                    style={{
                        background:
                            "radial-gradient(ellipse 70% 50% at 80% 10%, rgba(92,224,176,0.22) 0%, transparent 55%)",
                    }}
                />

                <div className="relative mx-auto max-w-6xl px-6 py-14 md:px-10 md:py-20">
                    <div className="mb-10">
                        <BrandLogo inverse className="h-8 md:h-9" />
                    </div>

                    <p className="ds-eyebrow mb-4 text-white/90">PATIENT ACCESS</p>

                    <h1 className="overview-spinsci-display mb-3 text-3xl leading-tight text-white md:text-4xl lg:text-[2.75rem]">
                        {isOSSMode
                            ? "Automate inbound and outbound"
                            : `Welcome${firstName ? `, ${firstName}` : ""}`}
                    </h1>

                    <p className="overview-spinsci-heading mb-6 text-xl font-normal text-white/85 md:text-2xl">
                        Outbound voice sales. Inbound voice support. One platform.
                    </p>

                    <p className="mb-8 max-w-2xl text-base leading-relaxed text-white/70 md:text-lg">
                        {isOSSMode ? (
                            <>
                                Run AI voice agents that prospect, follow up, and book meetings on
                                outbound — and answer FAQs, order status, and service requests on
                                inbound. Design once, dial and answer at scale, and warm-transfer to
                                humans when it matters.
                            </>
                        ) : (
                            "Build and deploy inbound and outbound voice workflows — qualify leads, resolve support, and hand off with full context."
                        )}
                    </p>

                    <div className="flex flex-wrap items-center gap-3">
                        <Button asChild size="lg" className="bg-white text-[var(--spinsci-ink)] hover:bg-white/90">
                            <Link href="/workflow">
                                Get started
                                <ArrowRight className="size-4" />
                            </Link>
                        </Button>
                        <Button
                            asChild
                            variant="outline"
                            size="lg"
                            className="border-white/25 bg-transparent text-white hover:bg-white/10 hover:text-white"
                        >
                            <Link href="/workflow/create">Agent builder</Link>
                        </Button>
                    </div>
                </div>
            </section>

            <section className="border-b border-[var(--spinsci-border-hairline)] bg-white px-6 py-12 md:px-10">
                <div className="mx-auto max-w-6xl">
                    <div className="mb-10 flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
                        <h2 className="overview-spinsci-heading text-2xl text-[var(--spinsci-ink)] md:text-3xl">
                            Voice sales & support
                        </h2>
                        <p className="max-w-md text-sm text-[var(--spinsci-text-secondary)]">
                            Outbound pipeline growth and inbound resolution under one roof — design,
                            connect, call, and optimize from a single workspace.
                        </p>
                    </div>

                    <div className="grid grid-cols-2 gap-8 md:grid-cols-4">
                        {STATS.map((stat) => (
                            <div key={stat.label} className="text-center md:text-left">
                                <p className="overview-spinsci-stat text-3xl text-[var(--spinsci-violet)] md:text-4xl">
                                    {stat.value}
                                </p>
                                <p className="mt-1 text-sm font-medium uppercase tracking-wide text-[var(--spinsci-text-secondary)]">
                                    {stat.label}
                                </p>
                            </div>
                        ))}
                    </div>
                </div>
            </section>

            <section className="bg-[var(--spinsci-surface)] px-6 py-8 md:px-10">
                <div className="mx-auto flex max-w-6xl flex-wrap justify-center gap-3">
                    {HIGHLIGHTS.map((point) => (
                        <span
                            key={point}
                            className="inline-flex items-center gap-2 rounded-full border border-[var(--spinsci-border-hairline)] bg-white px-4 py-2 text-xs font-medium text-[var(--spinsci-ink)]"
                        >
                            <Sparkles className="size-3.5 text-[var(--spinsci-teal)]" strokeWidth={2} />
                            {point}
                        </span>
                    ))}
                </div>
            </section>

            <section className="border-t border-[var(--spinsci-border-hairline)] bg-white px-6 py-14 md:px-10">
                <div className="mx-auto grid max-w-6xl gap-10 md:grid-cols-2">
                    <div>
                        <div className="mb-4 flex items-center gap-2">
                            <Globe className="size-5 text-[var(--spinsci-teal)]" strokeWidth={2} />
                            <h2 className="overview-spinsci-heading text-xl text-[var(--spinsci-ink)]">
                                About the platform
                            </h2>
                        </div>
                        <p className="text-sm leading-relaxed text-[var(--spinsci-text-secondary)]">
                            Deploy AI voice agents for outbound prospecting and inbound support — with
                            full control over models, telephony, and data. Calm, clinical-grade
                            automation without rip-and-replace.
                        </p>
                    </div>

                    <div>
                        <div className="mb-4 flex items-center gap-2">
                            <Mic className="size-5 text-[var(--spinsci-violet)]" strokeWidth={2} />
                            <h2 className="overview-spinsci-heading text-xl text-[var(--spinsci-ink)]">
                                Resources
                            </h2>
                        </div>
                        <p className="mb-5 text-sm text-[var(--spinsci-text-secondary)]">
                            Start with a voice agent workflow or use the agent builder to clarify
                            requirements and generate a validated graph.
                        </p>
                        <Button asChild variant="outline">
                            <Link href="/workflow/create">Open agent builder</Link>
                        </Button>
                    </div>
                </div>
            </section>
        </div>
    );
}
