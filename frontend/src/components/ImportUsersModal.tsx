import React, { useCallback, useRef, useState } from 'react';
import { AlertCircle, CheckCircle2, ChevronRight, FileUp, Loader2, X } from 'lucide-react';

import { useClients, useImportUsersCommit, useImportUsersPreview, useImportUsersValidate, useProjects, useUsers } from '@/hooks';
import type { ImportPreviewResponse, ImportPreviewRow } from '@/api/endpoints';
import type { Client, Project, User } from '@/types';
import { cn } from '@/lib/utils';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const IMPORT_FIELD_OPTIONS = [
  { value: 'ignore', label: '— Ignore —' },
  { value: 'full_name', label: 'Full Name' },
  { value: 'email', label: 'Primary Email' },
  { value: 'extra_email_1', label: 'Extra Email 1' },
  { value: 'extra_email_2', label: 'Extra Email 2' },
  { value: 'phone', label: 'Primary Phone' },
  { value: 'extra_phone_1', label: 'Extra Phone 1' },
  { value: 'extra_phone_2', label: 'Extra Phone 2' },
  { value: 'role', label: 'Role' },
  { value: 'title', label: 'Job Title' },
  { value: 'department', label: 'Department' },
  { value: 'client', label: 'Client (name)' },
  { value: 'project', label: 'Project (name)' },
  { value: 'manager', label: 'Manager (name or email)' },
  { value: 'is_active', label: 'Active (true/false)' },
];

function autoDetect(header: string): string {
  const h = header.toLowerCase().replace(/[^a-z0-9]/g, ' ').trim();
  if (/\bfull.?name\b|\bname\b/.test(h)) return 'full_name';
  if (/\bemail\b/.test(h) && !/extra|alias|2|two/.test(h)) return 'email';
  if (/\bemail.?2\b|\bsecond.?email\b|\bextra.?email\b/.test(h)) return 'extra_email_1';
  if (/\bemail.?3\b|\bthird.?email\b/.test(h)) return 'extra_email_2';
  if (/\bphone\b|\bmobile\b|\bcell\b/.test(h) && !/2|two|extra/.test(h)) return 'phone';
  if (/\bphone.?2\b|\bsecond.?phone\b|\bextra.?phone\b|\balt.?phone\b/.test(h)) return 'extra_phone_1';
  if (/\bphone.?3\b|\bthird.?phone\b/.test(h)) return 'extra_phone_2';
  if (/\brole\b|\bposition\b/.test(h)) return 'role';
  if (/\btitle\b|\bjob.?title\b/.test(h)) return 'title';
  if (/\bdept\b|\bdepartment\b/.test(h)) return 'department';
  if (/\bclient\b|\bcompany\b/.test(h)) return 'client';
  if (/\bproject\b/.test(h)) return 'project';
  if (/\bmanager\b|\bsupervisor\b|\breports.?to\b/.test(h)) return 'manager';
  if (/\bactive\b|\bstatus\b/.test(h)) return 'is_active';
  return 'ignore';
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Step = 'upload' | 'defaults' | 'map' | 'preview' | 'conflicts' | 'result';

interface Props {
  onClose: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export const ImportUsersModal: React.FC<Props> = ({ onClose }) => {
  React.useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  const [step, setStep] = useState<Step>('upload');
  const [file, setFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [preview, setPreview] = useState<ImportPreviewResponse | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [allRows, setAllRows] = useState<string[][]>([]);
  // Validated rows returned from /import/validate
  const [validatedRows, setValidatedRows] = useState<ImportPreviewRow[]>([]);
  // Per-row conflict resolution: row number (string) -> 'overwrite' | 'skip'
  const [conflictResolutions, setConflictResolutions] = useState<Record<string, 'overwrite' | 'skip'>>({});
  const [commitResult, setCommitResult] = useState<{
    created: number;
    updated: number;
    skipped: number;
    details: {
      created: Array<{ row: number; user_id: number; full_name: string; warnings: string[] }>;
      updated: Array<{ row: number; user_id: number; full_name: string; warnings: string[] }>;
      skipped: Array<{ row: number; reason: string }>;
    };
  } | null>(null);
  const [stepError, setStepError] = useState<string | null>(null);

  const [batchUserType, setBatchUserType] = useState<'internal' | 'external'>('external');
  const [batchClientId, setBatchClientId] = useState<string>('');
  const [batchProjectId, setBatchProjectId] = useState<string>('');
  const [batchManagerId, setBatchManagerId] = useState<string>('');

  const inputRef = useRef<HTMLInputElement>(null);
  const previewMutation = useImportUsersPreview();
  const validateMutation = useImportUsersValidate();
  const commitMutation = useImportUsersCommit();
  const { data: clients } = useClients();
  const { data: projects } = useProjects();
  const { data: users } = useUsers();

  const filteredProjects: Project[] = batchClientId
    ? (projects ?? []).filter((p: Project) => String(p.client_id) === batchClientId)
    : (projects ?? []);

  // Conflicts that need a decision (not exact_match, not errors, not new)
  const conflictRows = validatedRows.filter((r) => r.status === 'conflict');

  // -------------------------------------------------------------------------
  // Step 1: upload
  // -------------------------------------------------------------------------

  const handleFile = useCallback(async (f: File) => {
    setFile(f);
    setStepError(null);
    try {
      const result = await previewMutation.mutateAsync(f);
      setPreview(result);
      setAllRows(result.all_rows);
      const initialMapping: Record<string, string> = {};
      result.headers.forEach((h) => { initialMapping[h] = autoDetect(h); });
      setMapping(initialMapping);
      setStep('defaults');
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setStepError(msg || 'Failed to parse file. Check the format and try again.');
    }
  }, [previewMutation]);

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files[0];
    if (f) handleFile(f);
  }, [handleFile]);

  // -------------------------------------------------------------------------
  // Step 2: map columns -> validate
  // -------------------------------------------------------------------------

  const usedFields = new Set(Object.values(mapping).filter((v) => v !== 'ignore'));
  const isFieldTaken = (header: string, field: string) =>
    field !== 'ignore' && usedFields.has(field) && mapping[header] !== field;

  const handlePreviewStep = () => {
    if (!preview) return;
    setStepError(null);
    setStep('preview');
  };

  // -------------------------------------------------------------------------
  // Step 3: preview -> validate (re-upload full file then validate)
  // -------------------------------------------------------------------------

  const handleValidateStep = async () => {
    if (!preview) return;
    setStepError(null);
    try {
      const result = await validateMutation.mutateAsync({ headers: preview.headers, rows: allRows, mapping });
      setValidatedRows(result.rows);
      // Default all conflicts to 'skip'
      const resolutions: Record<string, 'overwrite' | 'skip'> = {};
      result.rows.filter((r) => r.status === 'conflict').forEach((r) => {
        resolutions[String(r.row)] = 'skip';
      });
      setConflictResolutions(resolutions);
      if (result.counts.conflict > 0) {
        setStep('conflicts');
      } else {
        await doCommit(allRows, resolutions);
      }
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setStepError(msg || 'Validation failed. Please try again.');
    }
  };

  // -------------------------------------------------------------------------
  // Commit
  // -------------------------------------------------------------------------

  const doCommit = async (rows: string[][], resolutions: Record<string, 'overwrite' | 'skip'>) => {
    if (!preview) return;
    setStepError(null);
    try {
      const result = await commitMutation.mutateAsync({
        headers: preview.headers,
        rows,
        mapping,
        user_type: batchUserType,
        ...(batchClientId ? { default_client_id: Number(batchClientId) } : {}),
        ...(batchProjectId ? { default_project_id: Number(batchProjectId) } : {}),
        ...(batchManagerId ? { default_manager_id: Number(batchManagerId) } : {}),
        conflict_resolutions: resolutions,
      });
      setCommitResult(result);
      setStep('result');
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setStepError(msg || 'Import failed. Please try again.');
    }
  };

  const handleCommitFromConflicts = () => doCommit(allRows, conflictResolutions);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const STEPS: Step[] = ['upload', 'defaults', 'map', 'preview', 'conflicts', 'result'];
  const STEP_LABELS = ['Upload', 'Defaults', 'Map columns', 'Preview', 'Conflicts', 'Done'];
  const stepIdx = STEPS.indexOf(step);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="flex w-full max-w-3xl flex-col rounded-xl border border-border bg-card shadow-xl max-h-[90vh]">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-6 py-4">
          <div>
            <h2 className="text-lg font-semibold">Import Users</h2>
            <p className="text-xs text-muted-foreground mt-0.5">CSV or Excel files supported</p>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg p-1.5 hover:bg-muted">
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Step indicator */}
        <div className="flex items-center gap-1 border-b border-border px-6 py-3 text-xs">
          {STEP_LABELS.map((label, i) => (
            <React.Fragment key={label}>
              <span className={cn(
                'rounded-full px-2 py-0.5 font-medium',
                i === stepIdx
                  ? 'bg-primary text-primary-foreground'
                  : i < stepIdx
                  ? 'bg-primary/20 text-primary'
                  : 'text-muted-foreground',
              )}>{label}</span>
              {i < STEP_LABELS.length - 1 && <ChevronRight className="h-3 w-3 text-muted-foreground shrink-0" />}
            </React.Fragment>
          ))}
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">

          {/* ---- Step 1: Upload ---- */}
          {step === 'upload' && (
            <div
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={onDrop}
              onClick={() => inputRef.current?.click()}
              className={cn(
                'flex flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed p-12 cursor-pointer transition',
                dragOver ? 'border-primary bg-primary/5' : 'border-border hover:border-primary/50 hover:bg-muted/30',
              )}
            >
              <FileUp className="h-10 w-10 text-muted-foreground" />
              <div className="text-center">
                <p className="font-medium">Drop a CSV or Excel file here</p>
                <p className="text-xs text-muted-foreground mt-1">or click to browse</p>
              </div>
              <input
                ref={inputRef}
                type="file"
                accept=".csv,.xlsx,.xls"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) handleFile(f);
                }}
              />
            </div>
          )}

          {previewMutation.isPending && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Parsing file...
            </div>
          )}

          {/* ---- Step 1.5: Batch defaults ---- */}
          {step === 'defaults' && preview && (
            <>
              <p className="text-sm text-muted-foreground">
                Set defaults that apply to every row. Per-row values from the file always override these.
              </p>
              <div className="space-y-4">
                <div>
                  <label className="text-xs font-medium mb-1.5 block">User type for this batch</label>
                  <div className="flex gap-2">
                    {(['external', 'internal'] as const).map((t) => (
                      <button
                        key={t}
                        type="button"
                        onClick={() => setBatchUserType(t)}
                        className={cn(
                          'rounded-lg border px-4 py-1.5 text-sm font-medium transition',
                          batchUserType === t
                            ? 'border-primary bg-primary/10 text-primary'
                            : 'border-border hover:bg-muted',
                        )}
                      >
                        {t === 'external' ? 'External' : 'Internal'}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs font-medium mb-1 block">Default client</label>
                    <select
                      value={batchClientId}
                      onChange={(e) => { setBatchClientId(e.target.value); setBatchProjectId(''); }}
                      className="w-full rounded-lg border border-border bg-background px-2 py-1.5 text-sm"
                    >
                      <option value="">— None —</option>
                      {clients?.map((c: Client) => (
                        <option key={c.id} value={c.id}>{c.name}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="text-xs font-medium mb-1 block">Default project</label>
                    <select
                      value={batchProjectId}
                      onChange={(e) => setBatchProjectId(e.target.value)}
                      className="w-full rounded-lg border border-border bg-background px-2 py-1.5 text-sm"
                    >
                      <option value="">— None —</option>
                      {filteredProjects?.map((p: Project) => (
                        <option key={p.id} value={p.id}>{p.name}</option>
                      ))}
                    </select>
                  </div>
                  <div className="sm:col-span-2">
                    <label className="text-xs font-medium mb-1 block">Default manager</label>
                    <select
                      value={batchManagerId}
                      onChange={(e) => setBatchManagerId(e.target.value)}
                      className="w-full rounded-lg border border-border bg-background px-2 py-1.5 text-sm"
                    >
                      <option value="">— None —</option>
                      {users?.filter((u: User) => u.role === 'MANAGER' || u.role === 'ADMIN').map((u: User) => (
                        <option key={u.id} value={u.id}>{u.full_name}</option>
                      ))}
                    </select>
                  </div>
                </div>
              </div>
            </>
          )}

          {/* ---- Step 2: Map columns ---- */}
          {step === 'map' && preview && (
            <>
              <p className="text-sm text-muted-foreground">
                Map each column from your file to the corresponding field. Columns set to "Ignore" are skipped.
              </p>
              <div className="rounded-lg border border-border overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-muted/40 text-xs text-muted-foreground">
                    <tr>
                      <th className="px-4 py-2 text-left font-medium">Your column</th>
                      <th className="px-4 py-2 text-left font-medium">Sample value</th>
                      <th className="px-4 py-2 text-left font-medium">Maps to</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.headers.map((header) => {
                      const sample = preview.preview_rows[0]?.[header] ?? '';
                      return (
                        <tr key={header} className="border-t border-border">
                          <td className="px-4 py-2 font-medium">{header}</td>
                          <td className="px-4 py-2 text-muted-foreground truncate max-w-[160px]">{sample || '—'}</td>
                          <td className="px-4 py-2">
                            <select
                              value={mapping[header] ?? 'ignore'}
                              onChange={(e) => setMapping((m) => ({ ...m, [header]: e.target.value }))}
                              className="w-full rounded-lg border border-border bg-background px-2 py-1 text-sm"
                            >
                              {IMPORT_FIELD_OPTIONS.map((opt) => (
                                <option
                                  key={opt.value}
                                  value={opt.value}
                                  disabled={isFieldTaken(header, opt.value)}
                                >
                                  {opt.label}{isFieldTaken(header, opt.value) ? ' (already mapped)' : ''}
                                </option>
                              ))}
                            </select>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <p className="text-xs text-muted-foreground">
                {preview.total_rows} data row{preview.total_rows !== 1 ? 's' : ''} detected.
                {!Object.values(mapping).includes('full_name') && (
                  <span className="ml-1 text-amber-600 font-medium">Map "Full Name" to continue.</span>
                )}
              </p>
            </>
          )}

          {/* ---- Step 3: Preview ---- */}
          {step === 'preview' && preview && (
            <>
              <p className="text-sm text-muted-foreground">
                Showing first {preview.preview_rows.length} of {preview.total_rows} rows.
                Review the mapped data before importing.
              </p>
              <div className="rounded-lg border border-border overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="bg-muted/40 text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2 text-left">#</th>
                      {Object.entries(mapping)
                        .filter(([, v]) => v !== 'ignore')
                        .map(([col, field]) => (
                          <th key={col} className="px-3 py-2 text-left whitespace-nowrap">
                            {IMPORT_FIELD_OPTIONS.find((o) => o.value === field)?.label ?? field}
                          </th>
                        ))}
                    </tr>
                  </thead>
                  <tbody>
                    {preview.preview_rows.map((row, i) => (
                      <tr key={i} className="border-t border-border hover:bg-muted/20">
                        <td className="px-3 py-1.5 text-muted-foreground">{i + 1}</td>
                        {Object.entries(mapping)
                          .filter(([, v]) => v !== 'ignore')
                          .map(([col]) => (
                            <td key={col} className="px-3 py-1.5 truncate max-w-[140px]">
                              {row[col] || <span className="text-muted-foreground/50">—</span>}
                            </td>
                          ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {preview.total_rows > preview.preview_rows.length && (
                <p className="text-xs text-muted-foreground">
                  + {preview.total_rows - preview.preview_rows.length} more rows will be imported.
                </p>
              )}
            </>
          )}

          {/* ---- Step 4: Conflicts ---- */}
          {step === 'conflicts' && (
            <>
              <div className="rounded-lg border border-amber-400/30 bg-amber-500/5 px-4 py-3">
                <p className="text-sm font-medium text-amber-700 dark:text-amber-400">
                  {conflictRows.length} row{conflictRows.length !== 1 ? 's' : ''} already exist with a different name.
                </p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Choose whether to overwrite the existing record or keep it and skip this row.
                  All other rows ({validatedRows.filter((r) => r.status === 'new').length} new,{' '}
                  {validatedRows.filter((r) => r.status === 'exact_match').length} exact matches) will be processed automatically.
                </p>
              </div>

              <div className="flex justify-end gap-2 text-xs">
                <button
                  type="button"
                  className="rounded border border-border px-3 py-1 hover:bg-muted"
                  onClick={() => {
                    const all: Record<string, 'overwrite' | 'skip'> = {};
                    conflictRows.forEach((r) => { all[String(r.row)] = 'skip'; });
                    setConflictResolutions(all);
                  }}
                >
                  Skip all
                </button>
                <button
                  type="button"
                  className="rounded border border-primary/40 bg-primary/10 px-3 py-1 text-primary hover:bg-primary/20"
                  onClick={() => {
                    const all: Record<string, 'overwrite' | 'skip'> = {};
                    conflictRows.forEach((r) => { all[String(r.row)] = 'overwrite'; });
                    setConflictResolutions(all);
                  }}
                >
                  Overwrite all
                </button>
              </div>

              <div className="space-y-2">
                {conflictRows.map((row) => {
                  const resolution = conflictResolutions[String(row.row)] ?? 'skip';
                  return (
                    <div
                      key={row.row}
                      className="rounded-lg border border-border bg-muted/10 px-4 py-3 text-sm"
                    >
                      <div className="flex items-start justify-between gap-4">
                        <div className="min-w-0">
                          <p className="font-medium truncate">Row {row.row}: {row.email}</p>
                          <div className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-muted-foreground">
                            <span>
                              <span className="text-destructive font-medium">Existing: </span>
                              {row.existing_name || '—'}
                            </span>
                            <span>
                              <span className="text-primary font-medium">File: </span>
                              {row.full_name}
                            </span>
                          </div>
                        </div>
                        <div className="flex gap-1.5 shrink-0">
                          <button
                            type="button"
                            onClick={() => setConflictResolutions((r) => ({ ...r, [String(row.row)]: 'skip' }))}
                            className={cn(
                              'rounded px-3 py-1 text-xs font-medium transition',
                              resolution === 'skip'
                                ? 'bg-muted text-foreground ring-1 ring-border'
                                : 'text-muted-foreground hover:bg-muted',
                            )}
                          >
                            Keep existing
                          </button>
                          <button
                            type="button"
                            onClick={() => setConflictResolutions((r) => ({ ...r, [String(row.row)]: 'overwrite' }))}
                            className={cn(
                              'rounded px-3 py-1 text-xs font-medium transition',
                              resolution === 'overwrite'
                                ? 'bg-primary/10 text-primary ring-1 ring-primary/40'
                                : 'text-muted-foreground hover:bg-muted',
                            )}
                          >
                            Overwrite
                          </button>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </>
          )}

          {/* ---- Step 5: Result ---- */}
          {step === 'result' && commitResult && (
            <div className="space-y-4">
              <div className="flex items-start gap-3 rounded-lg border border-border bg-muted/20 p-4">
                <CheckCircle2 className="h-5 w-5 text-green-500 shrink-0 mt-0.5" />
                <div>
                  <p className="font-medium">
                    {commitResult.created} user{commitResult.created !== 1 ? 's' : ''} imported
                    {commitResult.updated > 0 ? `, ${commitResult.updated} updated` : ''}
                  </p>
                  {commitResult.skipped > 0 && (
                    <p className="text-sm text-muted-foreground mt-0.5">
                      {commitResult.skipped} row{commitResult.skipped !== 1 ? 's' : ''} skipped
                    </p>
                  )}
                </div>
              </div>

              {commitResult.details.updated.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-primary mb-2">Updated records:</p>
                  <ul className="space-y-1">
                    {commitResult.details.updated.map((r) => (
                      <li key={r.row} className="text-xs rounded border border-primary/20 bg-primary/5 px-3 py-1.5">
                        <span className="font-medium">Row {r.row} · {r.full_name}</span>
                        {r.warnings.length > 0 && <span className="ml-2 text-amber-600">{r.warnings.join('; ')}</span>}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {commitResult.details.created.some((r) => r.warnings.length > 0) && (
                <div>
                  <p className="text-xs font-medium text-amber-600 mb-2">Rows imported with warnings:</p>
                  <ul className="space-y-1">
                    {commitResult.details.created
                      .filter((r) => r.warnings.length > 0)
                      .map((r) => (
                        <li key={r.row} className="text-xs rounded border border-amber-200/60 bg-amber-50/30 dark:bg-amber-900/10 px-3 py-1.5">
                          <span className="font-medium">Row {r.row} · {r.full_name}:</span>{' '}
                          {r.warnings.join('; ')}
                        </li>
                      ))}
                  </ul>
                </div>
              )}

              {commitResult.details.skipped.filter((r) => !r.reason.startsWith('Already exists (exact match)')).length > 0 && (
                <div>
                  <p className="text-xs font-medium text-destructive mb-2">Skipped rows:</p>
                  <ul className="space-y-1">
                    {commitResult.details.skipped
                      .filter((r) => !r.reason.startsWith('Already exists (exact match)'))
                      .map((r) => (
                        <li key={r.row} className="text-xs rounded border border-destructive/20 bg-destructive/5 px-3 py-1.5">
                          <span className="font-medium">Row {r.row}:</span> {r.reason}
                        </li>
                      ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          {stepError && (
            <div className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
              <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
              {stepError}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-border px-6 py-4">
          <button
            type="button"
            onClick={step === 'upload' || step === 'result' ? onClose : () => {
              if (step === 'defaults') setStep('upload');
              if (step === 'map') setStep('defaults');
              if (step === 'preview') setStep('map');
              if (step === 'conflicts') setStep('preview');
            }}
            className="px-4 py-2 rounded-lg text-sm text-muted-foreground hover:bg-muted transition"
          >
            {step === 'result' ? 'Close' : step === 'upload' ? 'Cancel' : 'Back'}
          </button>

          <div className="flex items-center gap-2">
            {step === 'defaults' && (
              <button
                type="button"
                onClick={() => setStep('map')}
                className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition"
              >
                Continue
              </button>
            )}
            {step === 'map' && (
              <button
                type="button"
                disabled={!Object.values(mapping).includes('full_name')}
                onClick={handlePreviewStep}
                className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium disabled:opacity-50 hover:bg-primary/90 transition"
              >
                Preview
              </button>
            )}
            {step === 'preview' && (
              <button
                type="button"
                disabled={validateMutation.isPending || previewMutation.isPending}
                onClick={handleValidateStep}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium disabled:opacity-50 hover:bg-primary/90 transition"
              >
                {(validateMutation.isPending || previewMutation.isPending) && (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                )}
                Import {preview?.total_rows} user{preview?.total_rows !== 1 ? 's' : ''}
              </button>
            )}
            {step === 'conflicts' && (
              <button
                type="button"
                disabled={commitMutation.isPending}
                onClick={handleCommitFromConflicts}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium disabled:opacity-50 hover:bg-primary/90 transition"
              >
                {commitMutation.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                Confirm &amp; Import
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
