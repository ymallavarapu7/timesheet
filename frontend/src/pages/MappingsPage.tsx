import React, { useState } from 'react';
import { Plus, Trash2, X } from 'lucide-react';

import { Badge, EmptyState, Loading } from '@/components';
import { BulkSelectBar } from '@/components/ui/BulkSelectBar';
import { useBulkDeleteMappings, useClients, useCreateMapping, useDeleteMapping, useMappings, useUpdateMapping, useUsers } from '@/hooks';
import type { Mapping, MappingPayload } from '@/types';

type MappingFormState = {
  match_type: string;
  match_value: string;
  client_id: string;
  employee_id: string;
};

const emptyForm = (): MappingFormState => ({
  match_type: 'email',
  match_value: '',
  client_id: '',
  employee_id: '',
});

const toPayload = (form: MappingFormState): MappingPayload => ({
  match_type: form.match_type,
  match_value: form.match_value.trim(),
  client_id: form.client_id ? Number(form.client_id) : undefined,
  employee_id: form.employee_id ? Number(form.employee_id) : null,
});

export const MappingsPage: React.FC = () => {
  const { data: mappings = [], isLoading } = useMappings();
  const { data: clients = [] } = useClients();
  const { data: users = [] } = useUsers();
  const createMapping = useCreateMapping();
  const updateMapping = useUpdateMapping();
  const deleteMapping = useDeleteMapping();
  const bulkDeleteMappings = useBulkDeleteMappings();

  const [isPanelOpen, setIsPanelOpen] = React.useState(false);
  const [editing, setEditing] = React.useState<Mapping | null>(null);
  const [form, setForm] = React.useState<MappingFormState>(emptyForm());
  const [message, setMessage] = React.useState<string | null>(null);
  const [selectedMappingIds, setSelectedMappingIds] = useState<Set<number>>(new Set());

  if (isLoading) {
    return <Loading message="Loading sender mappings..." />;
  }

  const clientMap = new Map<number, string>(clients.map((client: { id: number; name: string }) => [client.id, client.name] as const));
  const userMap = new Map<number, string>(users.map((user) => [user.id, user.full_name] as const));

  const openCreate = () => {
    setEditing(null);
    setForm(emptyForm());
    setIsPanelOpen(true);
  };

  const openEdit = (mapping: Mapping) => {
    setEditing(mapping);
    setForm({
      match_type: String(mapping.match_type),
      match_value: mapping.match_value,
      client_id: String(mapping.client_id),
      employee_id: mapping.employee_id ? String(mapping.employee_id) : '',
    });
    setIsPanelOpen(true);
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    const payload = toPayload(form);

    try {
      if (editing) {
        await updateMapping.mutateAsync({ id: editing.id, data: payload });
        setMessage(`Updated mapping for ${payload.match_value}.`);
      } else if (payload.match_type && payload.match_value && payload.client_id) {
        await createMapping.mutateAsync({
          match_type: payload.match_type,
          match_value: payload.match_value,
          client_id: payload.client_id,
          employee_id: payload.employee_id ?? null,
        });
        setMessage(`Created mapping for ${payload.match_value}.`);
      }
      setIsPanelOpen(false);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Unable to save mapping.');
    }
  };

  const handleDelete = async (mapping: Mapping) => {
    if (!window.confirm(`Delete mapping "${mapping.match_value}"?`)) return;
    try {
      await deleteMapping.mutateAsync(mapping.id);
      setMessage(`Deleted mapping ${mapping.match_value}.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Unable to delete mapping.');
    }
  };

  const toggleMapping = (id: number) => {
    setSelectedMappingIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectAllMappings = () => {
    setSelectedMappingIds(new Set(mappings.map((m) => m.id)));
  };

  const clearSelection = () => {
    setSelectedMappingIds(new Set());
  };

  const handleBulkDelete = async () => {
    const count = selectedMappingIds.size;
    if (!window.confirm(`Delete ${count} selected mapping${count === 1 ? '' : 's'}?`)) return;
    try {
      await bulkDeleteMappings.mutateAsync(Array.from(selectedMappingIds));
      setMessage(`Deleted ${count} mapping${count === 1 ? '' : 's'}.`);
      setSelectedMappingIds(new Set());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Unable to delete mappings.');
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-4 md:flex-row md:items-end">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground">Ingestion</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight">Sender Mappings</h1>
          <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
            Route incoming email senders to known clients and, when possible, the employee record reviewers should confirm.
          </p>
        </div>
        <button type="button" onClick={openCreate} className="action-button">
          <Plus className="mr-2 h-4 w-4" />
          New Mapping
        </button>
      </div>

      {message && (
        <div className="surface-card px-5 py-4">
          <p className="text-sm text-muted-foreground">{message}</p>
        </div>
      )}

      <div className="rounded-md bg-[var(--info-light)] px-3 py-2 text-sm text-[var(--text-secondary)]">
        Auto-assigns client and employee from sender address.
      </div>

      {mappings.length === 0 ? (
        <EmptyState message="No sender mappings yet. Add one to help the reviewer inbox pre-match incoming emails." />
      ) : (
        <>
        <BulkSelectBar
          selectedCount={selectedMappingIds.size}
          totalCount={mappings.length}
          onSelectAll={selectAllMappings}
          onClearSelection={clearSelection}
          onDelete={handleBulkDelete}
          isDeleting={bulkDeleteMappings.isPending}
          itemLabel="mapping"
        />
        <div className="surface-card overflow-hidden">
          <table className="min-w-full text-left text-sm">
            <thead className="border-b border-border">
              <tr className="text-[11px] uppercase tracking-[0.06em] text-muted-foreground">
                <th className="w-10 px-4 py-3"><input type="checkbox" checked={selectedMappingIds.size === mappings.length && mappings.length > 0} onChange={selectedMappingIds.size === mappings.length ? clearSelection : selectAllMappings} /></th>
                <th className="px-4 py-3 font-medium">Type</th>
                <th className="px-4 py-3 font-medium">Value</th>
                <th className="px-4 py-3 font-medium">Client</th>
                <th className="px-4 py-3 font-medium">Employee</th>
                <th className="px-4 py-3 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {mappings.map((mapping) => (
                <tr key={mapping.id} className="group h-11 hover:bg-muted">
                  <td className="px-4 py-3"><input type="checkbox" checked={selectedMappingIds.has(mapping.id)} onChange={() => toggleMapping(mapping.id)} /></td>
                  <td className="px-4 py-3"><Badge tone={mapping.match_type === 'email' ? 'info' : 'warning'}>{String(mapping.match_type)}</Badge></td>
                  <td className="px-4 py-3 text-foreground">{mapping.match_value}</td>
                  <td className="px-4 py-3 text-foreground">{clientMap.get(mapping.client_id) ?? `Client #${mapping.client_id}`}</td>
                  <td className="px-4 py-3 text-foreground">{mapping.employee_id ? userMap.get(mapping.employee_id) ?? `User #${mapping.employee_id}` : 'No employee pinned'}</td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex justify-end gap-2 opacity-0 transition group-hover:opacity-100">
                      <button type="button" onClick={() => openEdit(mapping)} className="action-button-secondary">Edit</button>
                      <button type="button" onClick={() => handleDelete(mapping)} className="action-button-secondary"><Trash2 className="mr-2 h-4 w-4" />Delete</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        </>
      )}

      {isPanelOpen && (
        <div className="fixed inset-0 z-[90] bg-[rgba(0,0,0,0.15)]" onClick={() => setIsPanelOpen(false)}>
          <aside className="ml-auto h-full w-full max-w-[380px] overflow-y-auto bg-card p-6 shadow-[0_4px_16px_rgba(0,0,0,0.08)]" onClick={(event) => event.stopPropagation()}>
            <div className="mb-5 flex items-center justify-between">
              <h2 className="text-base font-semibold text-foreground">{editing ? `Edit ${editing.match_value}` : 'Create Mapping'}</h2>
              <button type="button" className="inline-flex h-8 w-8 items-center justify-center rounded-md bg-muted" onClick={() => setIsPanelOpen(false)}>
                <X className="h-4 w-4" />
              </button>
            </div>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <label className="mb-2 block text-sm font-medium text-foreground">Match Type</label>
              <select className="field-input" value={form.match_type} onChange={(event) => setForm((current) => ({ ...current, match_type: event.target.value }))}>
                <option value="email">Email</option>
                <option value="domain">Domain</option>
              </select>
            </div>
            <div>
              <label className="mb-2 block text-sm font-medium text-foreground">Match Value</label>
              <input className="field-input" value={form.match_value} onChange={(event) => setForm((current) => ({ ...current, match_value: event.target.value }))} placeholder={form.match_type === 'domain' ? 'example.com' : 'user@example.com'} required />
            </div>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <label className="mb-2 block text-sm font-medium text-foreground">Client</label>
              <select className="field-input" value={form.client_id} onChange={(event) => setForm((current) => ({ ...current, client_id: event.target.value }))} required>
                <option value="">Select client</option>
                {clients.map((client: { id: number; name: string }) => (
                  <option key={client.id} value={client.id}>
                    {client.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-2 block text-sm font-medium text-foreground">Employee</label>
              <select className="field-input" value={form.employee_id} onChange={(event) => setForm((current) => ({ ...current, employee_id: event.target.value }))}>
                <option value="">No employee</option>
                {users.map((user) => (
                  <option key={user.id} value={user.id}>
                    {user.full_name}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="sticky bottom-0 flex justify-end gap-3 border-t border-border bg-card pt-3">
            <button type="button" onClick={() => setIsPanelOpen(false)} className="action-button-secondary">
              Cancel
            </button>
            <button type="submit" className="action-button" disabled={createMapping.isPending || updateMapping.isPending}>
              {createMapping.isPending || updateMapping.isPending ? 'Saving...' : editing ? 'Save Mapping' : 'Create Mapping'}
            </button>
          </div>
        </form>
          </aside>
        </div>
      )}
    </div>
  );
};
