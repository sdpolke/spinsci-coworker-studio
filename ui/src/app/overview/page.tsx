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
    { value: "In + Out", label: "Voice Automation" },
    { value: "10+", label: "Telephony Integrations" },
    { value: "24/7", label: "Inbound Coverage" },
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
        <div className="overview-crescendo -mx-4 -mt-2 md:-mx-6">
            {/* Hero — Crescendo dark banner treatment */}
            <section className="relative overflow-hidden bg-[#0e0e16] text-white">
                <div
                    aria-hidden
                    className="pointer-events-none absolute inset-0 opacity-40"
                    style={{
                        background:
                            "radial-gradient(ellipse 80% 60% at 70% 40%, #ff7d4a 0%, transparent 55%), radial-gradient(ellipse 50% 40% at 20% 80%, #ff214f 0%, transparent 50%)",
                    }}
                />
                <div
                    aria-hidden
                    className="pointer-events-none absolute inset-0 bg-[linear-gradient(to_bottom,rgba(0,0,0,0.35),rgba(0,0,0,0.75))]"
                />

                <div className="relative mx-auto max-w-6xl px-6 py-14 md:px-10 md:py-20">
                    <div className="mb-10">
                        <BrandLogo inverse className="h-8 md:h-9" />
                    </div>

                    <p className="mb-2 text-sm font-semibold uppercase tracking-[0.2em] text-[#ff7d4a]">
                        Crescendo Worldwide
                    </p>

                    <h1 className="overview-crescendo-display mb-3 text-3xl font-light leading-tight tracking-tight text-white md:text-4xl lg:text-[2.75rem]">
                        {isOSSMode
                            ? "Automate Inbound and Outbound"
                            : `Welcome${firstName ? `, ${firstName}` : ""}!`}
                    </h1>

                    <p className="overview-crescendo-heading mb-6 text-xl font-medium text-white/90 md:text-2xl">
                        Outbound voice sales. Inbound voice support. One platform.
                    </p>

                    <p className="mb-8 max-w-2xl text-base leading-relaxed text-white/75 md:text-lg">
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
                        <Button
                            asChild
                            size="lg"
                            className="rounded-sm bg-[#ff7d4a] px-7 font-medium text-[#0e0e16] shadow-none hover:bg-[#f37744]"
                        >
                            <Link href="/workflow">
                                Get Started
                                <ArrowRight className="size-4" />
                            </Link>
                        </Button>
                        <Button
                            asChild
                            variant="outline"
                            size="lg"
                            className="rounded-sm border-white/25 bg-transparent text-white hover:bg-white/10 hover:text-white"
                        >
                            <a
                                href="https://www.crescendoworldwide.com/"
                                target="_blank"
                                rel="noopener noreferrer"
                            >
                                About Crescendo
                            </a>
                        </Button>
                    </div>
                </div>
            </section>

            {/* Stats — Crescendo 360° Growth band */}
            <section className="border-b border-[#e8eaed] bg-white px-6 py-12 md:px-10">
                <div className="mx-auto max-w-6xl">
                    <div className="mb-10 flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
                        <h2 className="overview-crescendo-heading text-2xl font-medium text-[#202124] md:text-3xl">
                            Voice Sales & Support
                        </h2>
                        <p className="max-w-md text-sm text-[#6f6f6f]">
                            Outbound pipeline growth and inbound resolution under one roof — design,
                            connect, call, and optimize from a single workspace.
                        </p>
                    </div>

                    <div className="grid grid-cols-2 gap-8 md:grid-cols-4">
                        {STATS.map((stat) => (
                            <div key={stat.label} className="text-center md:text-left">
                                <p className="overview-crescendo-stat text-3xl font-semibold text-[#ff214f] md:text-4xl">
                                    {stat.value}
                                </p>
                                <p className="mt-1 text-sm font-medium text-[#626262]">{stat.label}</p>
                            </div>
                        ))}
                    </div>
                </div>
            </section>

            {/* Highlights strip */}
            <section className="bg-[#F8FAFB] px-6 py-8 md:px-10">
                <div className="mx-auto flex max-w-6xl flex-wrap justify-center gap-3">
                    {HIGHLIGHTS.map((point) => (
                        <span
                            key={point}
                            className="inline-flex items-center gap-2 rounded-full border border-[#e0e0e0] bg-white px-4 py-2 text-xs font-medium text-[#232323]"
                        >
                            <Sparkles className="size-3.5 text-[#ff214f]" />
                            {point}
                        </span>
                    ))}
                </div>
            </section>

            {/* About + Resources */}
            <section className="border-t border-[#e8eaed] bg-white px-6 py-14 md:px-10">
                <div className="mx-auto grid max-w-6xl gap-10 md:grid-cols-2">
                    <div>
                        <div className="mb-4 flex items-center gap-2">
                            <Globe className="size-5 text-[#ff214f]" />
                            <h2 className="overview-crescendo-heading text-xl font-medium text-[#202124]">
                                About Crescendo
                            </h2>
                        </div>
                        <p className="text-sm leading-relaxed text-[#6f6f6f]">
                            Crescendo Worldwide helps teams automate the calls that fill the calendar and the
                            ones that keep customers happy. Deploy AI voice agents for outbound prospecting and
                            inbound support — with full control over models, telephony, and data.
                        </p>
                    </div>

                    <div>
                        <div className="mb-4 flex items-center gap-2">
                            <Mic className="size-5 text-[#ff214f]" />
                            <h2 className="overview-crescendo-heading text-xl font-medium text-[#202124]">
                                Resources
                            </h2>
                        </div>
                        <p className="mb-5 text-sm text-[#6f6f6f]">
                            Learn more about automating inbound and outbound voice with Crescendo.
                        </p>
                        <Button
                            asChild
                            variant="outline"
                            className="rounded-sm border-[#d1d1d1] bg-white text-[#232323] hover:border-[#ff214f] hover:text-[#ff214f]"
                        >
                            <a
                                href="https://www.crescendoworldwide.com/"
                                target="_blank"
                                rel="noopener noreferrer"
                            >
                                Crescendo Worldwide
                            </a>
                        </Button>
                    </div>
                </div>
            </section>
        </div>
    );
}
