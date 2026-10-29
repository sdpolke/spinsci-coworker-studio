"use client";

import posthog from "posthog-js";
import { createContext, type ReactNode, useCallback, useContext, useMemo, useState } from "react";

import { EnterpriseModal } from "@/components/lead-forms/EnterpriseModal";
import type { LeadSource } from "@/components/lead-forms/leadFieldOptions";
import { PostHogEvent } from "@/constants/posthog-events";

interface LeadFormsContextValue {
  openEnterprise: (source: LeadSource, prefill?: { company?: string }) => void;
}

const LeadFormsContext = createContext<LeadFormsContextValue | null>(null);

export function LeadFormsProvider({ children }: { children: ReactNode }) {
  const [enterpriseOpen, setEnterpriseOpen] = useState(false);
  // Track the originating source so the *_OPENED and submit events agree.
  const [enterpriseSource, setEnterpriseSource] = useState<LeadSource>("sidebar");
  const [enterprisePrefill, setEnterprisePrefill] = useState<{ company?: string } | undefined>(undefined);

  const openEnterprise = useCallback((source: LeadSource, prefill?: { company?: string }) => {
    setEnterpriseSource(source);
    setEnterprisePrefill(prefill);
    setEnterpriseOpen(true);
    posthog.capture(PostHogEvent.ENTERPRISE_LEAD_OPENED, { source });
  }, []);

  const value = useMemo(() => ({ openEnterprise }), [openEnterprise]);

  return (
    <LeadFormsContext.Provider value={value}>
      {children}
      <EnterpriseModal
        open={enterpriseOpen}
        onOpenChange={setEnterpriseOpen}
        source={enterpriseSource}
        prefill={enterprisePrefill}
      />
    </LeadFormsContext.Provider>
  );
}

export function useLeadForms(): LeadFormsContextValue {
  const ctx = useContext(LeadFormsContext);
  if (!ctx) throw new Error("useLeadForms must be used within a LeadFormsProvider");
  return ctx;
}
