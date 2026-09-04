import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import React, { createContext, useContext } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { CredentialResponse, EndpointResponse } from '@/client/types.gen';

import { type EndpointFormValue, LangGraphEndpointForm } from './LangGraphEndpointForm';

const { api, auth } = vi.hoisted(() => ({
  api: { list: vi.fn(), create: vi.fn() },
  auth: { value: { user: { id: 1 }, loading: false } as { user: { id: number } | null; loading: boolean } },
}));

vi.mock('@/client', () => ({
  listCredentialsApiV1CredentialsGet: api.list,
  createCredentialApiV1CredentialsPost: api.create,
}));
vi.mock('@/lib/auth', () => ({ useAuth: () => auth.value }));

const SelectContext = createContext<{ value?: string; onValueChange: (value: string) => void }>({
  onValueChange: () => undefined,
});
vi.mock('@/components/ui/select', () => ({
  Select: ({ value, onValueChange, children }: { value?: string; onValueChange: (value: string) => void; children: React.ReactNode }) => (
    <SelectContext.Provider value={{ value, onValueChange }}><div>{children}</div></SelectContext.Provider>
  ),
  SelectTrigger: ({ children, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) => <button type="button" role="combobox" aria-controls="mock-select-options" aria-expanded="true" {...props}>{children}</button>,
  SelectValue: ({ placeholder }: { placeholder?: string }) => <span>{placeholder}</span>,
  SelectContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SelectItem: ({ value, children }: { value: string; children: React.ReactNode }) => {
    const select = useContext(SelectContext);
    return <button type="button" role="option" aria-selected={select.value === value} onClick={() => select.onValueChange(value)}>{children}</button>;
  },
}));

const DialogContext = createContext(false);
vi.mock('@/components/ui/dialog', () => ({
  Dialog: ({ open, children }: { open: boolean; children: React.ReactNode }) => <DialogContext.Provider value={open}>{children}</DialogContext.Provider>,
  DialogContent: ({ children }: { children: React.ReactNode }) => useContext(DialogContext) ? <div role="dialog">{children}</div> : null,
  DialogDescription: ({ children }: { children: React.ReactNode }) => <p>{children}</p>,
  DialogFooter: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogHeader: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: React.ReactNode }) => <h2>{children}</h2>,
}));

const credential = (changes: Partial<CredentialResponse> = {}): CredentialResponse => ({
  uuid: 'credential-1',
  name: 'LangGraph service',
  description: null,
  credential_type: 'bearer_token',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: null,
  ...changes,
});

const fillRequiredFields = () => {
  fireEvent.change(screen.getByLabelText('Identity name'), { target: { value: 'Support agent' } });
  fireEvent.change(screen.getByLabelText('Endpoint URL'), { target: { value: 'https://agent.example.com' } });
};

describe('LangGraphEndpointForm credentials', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    auth.value = { user: { id: 1 }, loading: false };
    api.list.mockResolvedValue({ data: [credential()] });
    api.create.mockResolvedValue({ data: credential({ uuid: 'credential-new', name: 'New service credential' }) });
  });

  it('waits for authentication readiness before loading organization credentials', async () => {
    auth.value = { user: null, loading: true };
    const { rerender } = render(<LangGraphEndpointForm onSubmit={vi.fn()} />);

    expect(screen.getByRole('status').textContent).toContain('Loading credentials');
    expect(api.list).not.toHaveBeenCalled();

    auth.value = { user: { id: 1 }, loading: false };
    rerender(<LangGraphEndpointForm onSubmit={vi.fn()} />);
    await waitFor(() => expect(api.list).toHaveBeenCalledWith({}));
    expect(await screen.findByText('LangGraph service (bearer_token)')).toBeTruthy();
  });

  it('selects an existing credential and submits its UUID', async () => {
    const onSubmit = vi.fn<(value: EndpointFormValue) => Promise<void>>().mockResolvedValue(undefined);
    render(<LangGraphEndpointForm onSubmit={onSubmit} />);
    fillRequiredFields();
    fireEvent.click(await screen.findByText('LangGraph service (bearer_token)'));
    fireEvent.click(screen.getByRole('button', { name: 'Create endpoint' }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit.mock.calls[0][0]).toMatchObject({ credential_uuid: 'credential-1' });
  });

  it('shows a clear empty state and requires a credential before submission', async () => {
    api.list.mockResolvedValue({ data: [] });
    const onSubmit = vi.fn<(value: EndpointFormValue) => Promise<void>>().mockResolvedValue(undefined);
    render(<LangGraphEndpointForm onSubmit={onSubmit} />);

    expect(await screen.findByText(/No credentials found for this organization/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Create endpoint' }).hasAttribute('disabled')).toBe(true);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('shows loading and normalized credential API errors', async () => {
    let resolveList!: (value: unknown) => void;
    api.list.mockReturnValue(new Promise((resolve) => { resolveList = resolve; }));
    render(<LangGraphEndpointForm onSubmit={vi.fn()} />);
    expect(screen.getByRole('status').textContent).toContain('Loading credentials');

    resolveList({ error: { detail: [{ loc: ['credentials'], msg: 'Credential access denied' }] } });
    expect((await screen.findByRole('alert')).textContent).toContain('Credential access denied');
  });

  it('creates a credential inline, refreshes, auto-selects it, and never forwards the user token', async () => {
    api.list
      .mockResolvedValueOnce({ data: [] })
      .mockResolvedValueOnce({ data: [credential({ uuid: 'credential-new', name: 'New service credential' })] });
    const onSubmit = vi.fn<(value: EndpointFormValue) => Promise<void>>().mockResolvedValue(undefined);
    render(<LangGraphEndpointForm onSubmit={onSubmit} />);
    fillRequiredFields();
    await screen.findByText(/No credentials found for this organization/);

    fireEvent.click(screen.getByRole('button', { name: 'Add new credential' }));
    fireEvent.change(screen.getByLabelText('Name *'), { target: { value: 'New service credential' } });
    fireEvent.change(screen.getByLabelText('Token'), { target: { value: 'external-secret-value' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create' }));

    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1));
    expect(api.create.mock.calls[0][0]).toEqual({
      body: {
        name: 'New service credential',
        description: undefined,
        credential_type: 'bearer_token',
        credential_data: { token: 'external-secret-value' },
      },
    });
    expect(api.create.mock.calls[0][0]).not.toHaveProperty('headers');
    await waitFor(() => expect(api.list).toHaveBeenCalledTimes(2));
    expect(screen.queryByDisplayValue('external-secret-value')).toBeNull();
    expect(document.body.textContent).not.toContain('external-secret-value');

    fireEvent.click(screen.getByRole('button', { name: 'Create endpoint' }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit.mock.calls[0][0]).toMatchObject({ credential_uuid: 'credential-new' });
  });

  it('preserves the current masked credential in edit mode when it is absent from the list', async () => {
    api.list.mockResolvedValue({ data: [] });
    const endpoint = {
      name: 'Existing endpoint',
      endpoint_url: 'https://agent.example.com',
      credential: { reference_id: 'credential-current', credential_type: 'api_key', last_updated_at: null },
      selected_profile: 'chat',
      selected_capabilities: ['streaming'],
    } as EndpointResponse;
    render(<LangGraphEndpointForm endpoint={endpoint} onSubmit={vi.fn(async () => undefined)} />);

    expect(await screen.findByText('Current credential (api_key)')).toBeTruthy();
    expect(document.body.textContent).not.toContain('credential-secret-value');
    expect(screen.getByRole('button', { name: 'Save and revalidate' }).hasAttribute('disabled')).toBe(false);
  });
});
