import React from 'react';
import { format } from 'date-fns';
import { ArrowLeft, Bot, Check, PauseCircle, Paperclip, Plus, RefreshCw, Save, Trash2, XCircle } from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';

import { ingestionAPI } from '@/api/endpoints';
import { Badge, Card, CardContent, CardHeader, CardTitle, Loading, Modal } from '@/components';
import {
  useAddIngestionLineItem,
  useApproveIngestionTimesheet,
  useAssignChainCandidate,
  useClients,
  useCreateClient,
  useDeleteIngestionLineItem,
  useDraftIngestionComment,
  useFetchJobStatus,
  useHoldIngestionTimesheet,
  useIngestionEmail,
  useIngestionTimesheet,
  useIngestionTimesheets,
  useProjects,
  useRejectIngestionLineItem,
  useRejectIngestionTimesheet,
  useReprocessIngestionEmail,
  useRevertIngestionTimesheetRejection,
  useUnrejectIngestionLineItem,
  useUpdateIngestionLineItem,
  useUpdateIngestionTimesheetData,
  useUsers,
} from '@/hooks';
import type { ChainCandidate, EmailAttachmentSummary, IngestionLineItem, IngestionLineItemPayload, SpreadsheetPreview } from '@/types';

type LineItemFormState = { work_date: string; hours: string; description: string; project_code: string; project_id: string };

const emptyLineItem = (): LineItemFormState => ({ work_date: '', hours: '', description: '', project_code: '', project_id: '' });
const toLineItemPayload = (form: LineItemFormState): IngestionLineItemPayload => ({
  work_date: form.work_date,
  hours: form.hours,
  description: form.description || null,
  project_code: form.project_code || null,
  project_id: form.project_id ? Number(form.project_id) : null,
});
const formatDateTime = (value?: string | null) => (value ? new Date(value).toLocaleString() : '--');
const attachmentKind = (attachment: EmailAttachmentSummary | null) =>
  !attachment?.mime_type ? 'other' : attachment.mime_type.includes('pdf') ? 'pdf' : attachment.mime_type.startsWith('image/') ? 'image' : 'other';
const renderReason = (value?: string | null) => value ? value.replace(/_/g, ' ') : 'unknown';
const cleanEmployeeNameForDisplay = (value?: string | null) => {
  if (!value) return '';
  const compactLeadingPrefix = value.replace(/^ven[aij](?=[A-Z])/, '');
  const parts = compactLeadingPrefix.trim().split(/\s+/).filter(Boolean);
  if (parts.length > 1 && /^ven[aij]$/i.test(parts[0])) {
    parts.shift();
  }
  if (parts.length > 0 && /^ashw/i.test(parts[0])) {
    parts[0] = `Ai${parts[0].slice(1)}`;
  }
  return parts.join(' ').trim() || compactLeadingPrefix.trim();
};
const normalizeEmployeeNameForMatch = (value?: string | null) => {
  const cleaned = cleanEmployeeNameForDisplay(value);
  if (!cleaned) return '';
  const normalized = cleaned.toLowerCase().replace(/[^a-z\s]/g, ' ').replace(/\s+/g, ' ').trim();
  const parts = normalized.split(' ').filter(Boolean);
  if (!parts.length) return '';
  const first = parts[0];
  if (first.startsWith('vena') && first.length > 6) parts[0] = first.slice(4);
  if (first.startsWith('venj') && first.length > 6) parts[0] = first.slice(4);
  if (first.startsWith('veni') && first.length > 6) parts[0] = first.slice(4);
  return parts.join(' ');
};

const trimTrailingEmptyColumns = (rows: string[][]): string[][] => {
  if (rows.length === 0) return rows;
  const width = rows.reduce((max, row) => Math.max(max, row.length), 0);
  let keep = width;
  while (keep > 0 && rows.every((row) => ((row[keep - 1] ?? '') as string).trim() === '')) {
    keep -= 1;
  }
  return keep === width ? rows : rows.map((row) => row.slice(0, keep));
};

const splitIntoBlocks = (rows: string[][]): string[][][] => {
  if (rows.length === 0) return [];
  const width = rows.reduce((max, row) => Math.max(max, row.length), 0);
  if (width === 0) return [];
  const emptyCols = new Set<number>();
  for (let c = 0; c < width; c += 1) {
    if (rows.every((row) => ((row[c] ?? '') as string).trim() === '')) emptyCols.add(c);
  }
  const ranges: Array<[number, number]> = [];
  let start: number | null = null;
  for (let c = 0; c < width; c += 1) {
    if (emptyCols.has(c)) {
      if (start !== null) {
        ranges.push([start, c]);
        start = null;
      }
    } else if (start === null) {
      start = c;
    }
  }
  if (start !== null) ranges.push([start, width]);
  return ranges
    .map(([s, e]) => rows.map((row) => row.slice(s, e)).filter((row) => row.some((cell) => cell.trim() !== '')))
    .filter((block) => block.length > 0);
};

const BlockTable: React.FC<{ rows: string[][] }> = ({ rows }) => {
  const maxCols = rows.reduce((max, row) => Math.max(max, row.length), 0);
  return (
    <table className="min-w-full border-collapse text-sm">
      <tbody>
        {rows.map((row, rIdx) => (
          <tr
            key={rIdx}
            className={rIdx === 0 ? 'bg-muted/50 font-semibold text-foreground' : 'even:bg-muted/20'}
          >
            {Array.from({ length: maxCols }, (_, cIdx) => (
              <td
                key={cIdx}
                className="whitespace-nowrap border border-border/60 px-3 py-1.5 align-top text-foreground"
              >
                {row[cIdx] ?? ''}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
};

const SpreadsheetPreviewTable: React.FC<{ preview: SpreadsheetPreview }> = ({ preview }) => {
  const [activeSheet, setActiveSheet] = React.useState(0);
  const sheets = preview.sheets ?? [];
  if (sheets.length === 0) {
    return <div className="px-6 py-10 text-sm text-muted-foreground">Spreadsheet is empty.</div>;
  }
  const rawCurrent = sheets[Math.min(activeSheet, sheets.length - 1)];
  const trimmedRows = trimTrailingEmptyColumns(rawCurrent.rows);
  // Prefer server-provided blocks; fall back to computing them client-side so
  // older previews without the `blocks` field still benefit.
  const blocks = rawCurrent.blocks?.length
    ? rawCurrent.blocks.map((b) => b.rows)
    : splitIntoBlocks(trimmedRows);
  const renderBlocks = blocks.length > 0 ? blocks : [trimmedRows];
  return (
    <div className="flex flex-col">
      {sheets.length > 1 && (
        <div className="flex shrink-0 gap-1 border-b border-border/60 px-4 py-2 overflow-x-auto">
          {sheets.map((sheet, idx) => (
            <button
              key={`${sheet.name}-${idx}`}
              type="button"
              onClick={() => setActiveSheet(idx)}
              className={`shrink-0 rounded-md px-3 py-1 text-xs font-medium transition ${
                idx === activeSheet
                  ? 'bg-primary/15 text-primary'
                  : 'text-muted-foreground hover:bg-muted/60 hover:text-foreground'
              }`}
            >
              {sheet.name || `Sheet ${idx + 1}`}
            </button>
          ))}
        </div>
      )}
      <div className="overflow-auto max-h-[75vh] px-4 py-3 space-y-4">
        {renderBlocks.map((rows, idx) => (
          <BlockTable key={idx} rows={rows} />
        ))}
      </div>
    </div>
  );
};

// Extract chain_candidates from the loosely-typed llm_match_suggestions blob.
// Returns [] when the structure doesn't match — defensive because the
// pipeline is the only writer but the column is Record<string, unknown>.
const extractChainCandidates = (raw: Record<string, unknown> | null): ChainCandidate[] => {
  if (!raw || typeof raw !== 'object') return [];
  const candidates = (raw as { chain_candidates?: unknown }).chain_candidates;
  if (!Array.isArray(candidates)) return [];
  return candidates
    .filter((entry): entry is Record<string, unknown> => !!entry && typeof entry === 'object')
    .map((entry) => ({
      name: typeof entry.name === 'string' ? entry.name : null,
      email: typeof entry.email === 'string' ? entry.email : null,
      existing_user_id:
        typeof entry.existing_user_id === 'number' ? entry.existing_user_id : null,
      matches_extracted_name: entry.matches_extracted_name === true,
    }));
};


type ChainCandidatesPanelProps = {
  timesheetId: number | null;
  rawSuggestions: Record<string, unknown> | null;
  currentEmployeeId: number | null;
  onAssign: (payload: { name?: string | null; email?: string | null }) => Promise<void>;
  isAssigning: boolean;
};

const ChainCandidatesPanel: React.FC<ChainCandidatesPanelProps> = ({
  timesheetId,
  rawSuggestions,
  currentEmployeeId,
  onAssign,
  isAssigning,
}) => {
  const candidates = React.useMemo(() => extractChainCandidates(rawSuggestions), [rawSuggestions]);
  const [editingIdx, setEditingIdx] = React.useState<number | null>(null);
  const [emailInput, setEmailInput] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);

  // Reset state when we switch timesheets or the underlying data changes.
  React.useEffect(() => {
    setEditingIdx(null);
    setEmailInput('');
    setError(null);
  }, [timesheetId, rawSuggestions]);

  if (!candidates.length) return null;
  // Hide the panel once the reviewer has bound the timesheet to anyone —
  // the primary Employee dropdown is now authoritative.
  if (currentEmployeeId != null) return null;

  const handleSelect = async (candidate: ChainCandidate, idx: number) => {
    setError(null);
    // If candidate has an email OR matches an existing user, we can submit
    // immediately. Otherwise open the inline email input.
    if (candidate.email || candidate.existing_user_id != null) {
      try {
        await onAssign({ name: candidate.name, email: candidate.email });
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : 'Assignment failed');
      }
      return;
    }
    setEditingIdx(idx);
    setEmailInput('');
  };

  const handleConfirmWithEmail = async (candidate: ChainCandidate) => {
    setError(null);
    try {
      await onAssign({
        name: candidate.name,
        email: emailInput.trim() || null,
      });
      setEditingIdx(null);
      setEmailInput('');
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Assignment failed');
    }
  };

  return (
    <div className="mt-3 rounded-md border border-amber-200/30 bg-amber-50/5 px-3 py-2.5" data-testid="chain-candidates-panel">
      <p className="text-xs font-medium uppercase tracking-wide text-amber-200/80">
        Candidates from email chain
      </p>
      <p className="mt-1 text-xs text-muted-foreground">
        The forwarded email included these names. Pick the one that belongs to this timesheet.
      </p>
      <div className="mt-2 flex flex-wrap gap-2">
        {candidates.map((candidate, idx) => {
          const label = candidate.email
            ? `${candidate.name ?? candidate.email} <${candidate.email}>`
            : candidate.name ?? '(no name)';
          const isEditing = editingIdx === idx;
          const hasKnownUser = candidate.existing_user_id != null;
          return (
            <div key={idx} className="flex flex-col gap-1" data-testid="chain-candidate-chip">
              <button
                type="button"
                className="inline-flex items-center gap-2 rounded-full bg-muted/30 px-3 py-1 text-xs font-medium text-foreground hover:bg-muted disabled:opacity-50"
                onClick={() => void handleSelect(candidate, idx)}
                disabled={isAssigning}
                title={hasKnownUser ? 'Bind to existing user' : 'Select this candidate'}
              >
                {candidate.matches_extracted_name && <span>★</span>}
                <span>{label}</span>
                {hasKnownUser && <span className="text-[10px] uppercase text-emerald-300">known</span>}
              </button>
              {isEditing && !hasKnownUser && !candidate.email && (
                <div className="flex items-center gap-2">
                  <input
                    type="email"
                    className="field-input h-7 text-xs"
                    placeholder="email@example.com (optional)"
                    value={emailInput}
                    onChange={(e) => setEmailInput(e.target.value)}
                  />
                  <button
                    type="button"
                    className="rounded bg-primary px-2 py-1 text-xs font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
                    onClick={() => void handleConfirmWithEmail(candidate)}
                    disabled={isAssigning}
                  >
                    Confirm
                  </button>
                  <button
                    type="button"
                    className="rounded px-2 py-1 text-xs text-muted-foreground hover:text-foreground"
                    onClick={() => { setEditingIdx(null); setEmailInput(''); }}
                    disabled={isAssigning}
                  >
                    Cancel
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </div>
      {error && <p className="mt-2 text-xs text-red-400">{error}</p>}
    </div>
  );
};


export const ReviewPanelPage: React.FC = () => {
  const navigate = useNavigate();
  const { timesheetId, emailId } = useParams();
  const parsedTimesheetId = Number(timesheetId ?? '');
  const parsedEmailId = Number(emailId ?? '');
  const normalizedTimesheetId = Number.isInteger(parsedTimesheetId) && parsedTimesheetId > 0 ? parsedTimesheetId : null;
  const normalizedEmailId = Number.isInteger(parsedEmailId) && parsedEmailId > 0 ? parsedEmailId : null;
  const isTimesheetMode = normalizedTimesheetId !== null;
  const isEmailMode = normalizedEmailId !== null;

  const {
    data: timesheet,
    isLoading: isTimesheetLoading,
    isError: isTimesheetError,
  } = useIngestionTimesheet(normalizedTimesheetId, isTimesheetMode);
  const {
    data: storedEmail,
    isLoading: isEmailLoading,
    isError: isEmailError,
  } = useIngestionEmail(normalizedEmailId, isEmailMode);
  const { data: users = [] } = useUsers();
  const { data: clients = [] } = useClients();
  const createClient = useCreateClient();
  const { data: projects = [] } = useProjects({ active_only: true, limit: 500 });
  const updateTimesheet = useUpdateIngestionTimesheetData();
  const assignChainCandidate = useAssignChainCandidate();
  const addLineItem = useAddIngestionLineItem();
  const updateLineItem = useUpdateIngestionLineItem();
  const deleteLineItem = useDeleteIngestionLineItem();
  const approveTimesheet = useApproveIngestionTimesheet();
  const rejectTimesheet = useRejectIngestionTimesheet();
  const holdTimesheet = useHoldIngestionTimesheet();
  const draftComment = useDraftIngestionComment();
  const reprocessEmail = useReprocessIngestionEmail();
  const queryClient = useQueryClient();
  const [reprocessJobId, setReprocessJobId] = React.useState<string | null>(null);
  const { data: reprocessStatus } = useFetchJobStatus(reprocessJobId, Boolean(reprocessJobId));
  const isReprocessing = Boolean(reprocessJobId && reprocessStatus && (reprocessStatus.status === 'queued' || reprocessStatus.status === 'in_progress'));
  const reprocessDone = Boolean(reprocessJobId && reprocessStatus && (reprocessStatus.status === 'complete' || reprocessStatus.status === 'failed'));
  const rejectLineItem = useRejectIngestionLineItem();
  const unrejectLineItem = useUnrejectIngestionLineItem();
  const revertTimesheetRejection = useRevertIngestionTimesheetRejection();

  const emailContext = timesheet?.email ?? storedEmail ?? null;

  // When a reprocess job finishes, refresh data and (if needed) redirect.
  // Reprocess deletes non-approved IngestionTimesheet rows and creates new
  // ones with fresh IDs, so the current /ingestion/review/:timesheetId URL
  // will 404. Redirect to the email view so the user lands on the new row.
  React.useEffect(() => {
    if (!reprocessJobId || !reprocessStatus) return;
    if (reprocessStatus.status !== 'complete' && reprocessStatus.status !== 'failed') return;
    if (reprocessStatus.status === 'complete') {
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'timesheet'] });
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'timesheets'] });
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'email'] });
      queryClient.invalidateQueries({ queryKey: ['ingestion', 'skipped-emails'] });
      const targetEmailId = emailContext?.id ?? normalizedEmailId;
      if (isTimesheetMode && targetEmailId) {
        navigate(`/ingestion/email/${targetEmailId}`, { replace: true });
      }
    }
    const timer = window.setTimeout(() => setReprocessJobId(null), 6000);
    return () => window.clearTimeout(timer);
  }, [reprocessJobId, reprocessStatus?.status, queryClient, isTimesheetMode, emailContext?.id, normalizedEmailId, navigate]);
  const emailId_forSiblings = emailContext?.id ?? null;
  const extractedName = ((timesheet?.extracted_employee_name ?? timesheet?.employee_name) ?? '').toLowerCase().trim();
  const attachmentId_forSiblings = timesheet?.attachment_id ?? null;
  const { data: siblingData } = useIngestionTimesheets(
    emailId_forSiblings ? { email_id: emailId_forSiblings } : undefined,
    !!emailId_forSiblings,
  );
  // Filter siblings to same employee: prefer attachment_id match (most reliable),
  // fall back to extracted employee name if attachment_id is null.
  const siblings = React.useMemo(() => {
    if (!Array.isArray(siblingData)) return [];
    const filtered = [...siblingData].filter((s) => {
      if (attachmentId_forSiblings != null && s.attachment_id != null) {
        return s.attachment_id === attachmentId_forSiblings;
      }
      const sName = ((s.extracted_employee_name ?? s.employee_name) ?? '').toLowerCase().trim();
      return !extractedName || sName === extractedName;
    });

    const deduped = new Map<string, typeof filtered[number]>();
    for (const entry of filtered) {
      const signature = `${entry.attachment_id ?? 'no-att'}|${entry.period_start ?? ''}|${entry.period_end ?? ''}|${entry.total_hours ?? ''}`;
      const existing = deduped.get(signature);
      if (!existing || entry.id === timesheet?.id) {
        deduped.set(signature, entry);
      }
    }

    return [...deduped.values()].sort((a, b) => {
      const av = a.period_start ? new Date(a.period_start).getTime() : 0;
      const bv = b.period_start ? new Date(b.period_start).getTime() : 0;
      return av - bv;
    });
  }, [siblingData, attachmentId_forSiblings, extractedName, timesheet?.id]);

  // In email mode, if exactly one timesheet exists for this email, jump
  // directly to its timesheet view. This happens after a reprocess redirect
  // so the user lands on the equivalent submission instead of the diagnostic.
  React.useEffect(() => {
    if (!isEmailMode) return;
    if (!Array.isArray(siblingData) || siblingData.length === 0) return;
    const first = siblingData[0];
    if (first?.id) navigate(`/ingestion/review/${first.id}`, { replace: true });
  }, [isEmailMode, siblingData, navigate]);

  const [summaryForm, setSummaryForm] = React.useState({ employee_id: '', client_id: '', supervisor_user_id: '', period_start: '', period_end: '', total_hours: '', internal_notes: '' });
  const [reviewComment, setReviewComment] = React.useState('');
  const [rejectReason, setRejectReason] = React.useState('');
  const [lineItemModalOpen, setLineItemModalOpen] = React.useState(false);
  const [editingLineItem, setEditingLineItem] = React.useState<IngestionLineItem | null>(null);
  const [lineItemForm, setLineItemForm] = React.useState<LineItemFormState>(emptyLineItem());
  const [selectedAttachmentId, setSelectedAttachmentId] = React.useState<number | null>(null);
  const [attachmentUrl, setAttachmentUrl] = React.useState<string | null>(null);
  const [attachmentLoadError, setAttachmentLoadError] = React.useState<string | null>(null);
  const [showFullSheet, setShowFullSheet] = React.useState(false);
  const [fullSheetHtml, setFullSheetHtml] = React.useState<string | null>(null);
  const [fullSheetLoading, setFullSheetLoading] = React.useState(false);
  const [showApproveConfirm, setShowApproveConfirm] = React.useState(false);
  const [showRejectPanel, setShowRejectPanel] = React.useState(false);
  const [rejectingLineItemId, setRejectingLineItemId] = React.useState<number | null>(null);
  const [lineItemRejectReason, setLineItemRejectReason] = React.useState('');

  // Splitter drag state
  const [leftPct, setLeftPct] = React.useState(62);
  const containerRef = React.useRef<HTMLDivElement>(null);
  const isDragging = React.useRef(false);

  React.useEffect(() => {
    const onUp = () => { isDragging.current = false; document.body.style.cursor = ''; document.body.style.userSelect = ''; };
    const onMove = (e: MouseEvent) => {
      if (!isDragging.current || !containerRef.current) return;
      if (e.buttons === 0) { onUp(); return; } // mouse released outside window
      const rect = containerRef.current.getBoundingClientRect();
      const pct = ((e.clientX - rect.left) / rect.width) * 100;
      setLeftPct(Math.min(Math.max(pct, 30), 78));
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => { window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp); };
  }, []);

  React.useEffect(() => {
    if (!timesheet) return;
    setSummaryForm({
      employee_id: timesheet.employee_id ? String(timesheet.employee_id) : '',
      client_id: timesheet.client_id ? String(timesheet.client_id) : '',
      supervisor_user_id: timesheet.supervisor_user_id ? String(timesheet.supervisor_user_id) : '',
      period_start: timesheet.period_start ?? '',
      period_end: timesheet.period_end ?? '',
      total_hours: timesheet.total_hours ? Number(timesheet.total_hours).toFixed(1) : '',
      internal_notes: timesheet.internal_notes ?? '',
    });
  }, [timesheet]);

  React.useEffect(() => {
    if (!timesheet?.attachment_id) return;
    setSelectedAttachmentId(timesheet.attachment_id);
  }, [timesheet?.attachment_id]);

  React.useEffect(() => {
    let objectUrl: string | null = null;
    if (!selectedAttachmentId) {
      setAttachmentUrl(null);
      setAttachmentLoadError(null);
      return undefined;
    }
    ingestionAPI.getAttachmentFile(selectedAttachmentId)
      .then((url) => { objectUrl = url; setAttachmentUrl(url); setAttachmentLoadError(null); })
      .catch(() => { setAttachmentUrl(null); setAttachmentLoadError('Unable to load attachment preview.'); });
    return () => { if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [selectedAttachmentId]); // intentionally excludes emailContext — only re-fetch when the actual ID changes

  // Reset full-sheet state when switching attachments.
  React.useEffect(() => {
    setShowFullSheet(false);
    setFullSheetHtml(null);
  }, [selectedAttachmentId]);

  // Lazy-load full HTML the first time the toggle is flipped on.
  React.useEffect(() => {
    if (!showFullSheet || !selectedAttachmentId || fullSheetHtml || fullSheetLoading) return;
    setFullSheetLoading(true);
    ingestionAPI.getAttachmentFullHtml(selectedAttachmentId)
      .then((res) => setFullSheetHtml(res.data.html))
      .catch(() => setFullSheetHtml('<p style="padding:16px;font-family:sans-serif">Failed to load full sheet.</p>'))
      .finally(() => setFullSheetLoading(false));
  }, [showFullSheet, selectedAttachmentId, fullSheetHtml, fullSheetLoading]);

  const selectedAttachment = emailContext?.attachments.find((item) => item.id === selectedAttachmentId) ?? null;
  const linkedAttachment =
    timesheet?.attachment_id != null
      ? emailContext?.attachments.find((item) => item.id === timesheet.attachment_id) ?? null
      : null;
  const selectedAttachmentType = attachmentKind(selectedAttachment);
  const structured = timesheet?.extracted_data;
  const fromStructured = structured && typeof structured === 'object' && typeof (structured as Record<string, unknown>).employee_name === 'string'
    ? String((structured as Record<string, unknown>).employee_name)
    : '';
  const extractedEmployeeHint = ((timesheet?.extracted_employee_name || fromStructured || '') as string).trim();
  const extractedClientHint = (() => {
    if (!structured || typeof structured !== 'object') return '';
    const record = structured as Record<string, unknown>;
    const value = record.client_name ?? record.client;
    return typeof value === 'string' ? value.trim() : '';
  })();
  const extractedClientMatchesExisting = extractedClientHint
    ? clients.some((c: { id: number; name: string }) =>
        c.name.trim().toLowerCase() === extractedClientHint.toLowerCase())
    : false;
  const normalizedHint = normalizeEmployeeNameForMatch(extractedEmployeeHint);
  const extractedEmployeeMatch = normalizedHint
    ? users.find((user) => {
        const normalizedUser = normalizeEmployeeNameForMatch(user.full_name);
        return (
          normalizedUser === normalizedHint
          || normalizedUser.includes(normalizedHint)
          || normalizedHint.includes(normalizedUser)
        );
      })
    : undefined;
  const extractedEmployeeDisplayName = cleanEmployeeNameForDisplay(extractedEmployeeMatch?.full_name || extractedEmployeeHint);
  const extractedEmployeeHasMatch = !!extractedEmployeeMatch;
  const showExtractedEmployeeOption = !summaryForm.employee_id && !!extractedEmployeeHint && !extractedEmployeeHasMatch;
  const employeeSelectValue = summaryForm.employee_id || (showExtractedEmployeeOption ? '__extracted__' : '');
  const isActionable = timesheet ? timesheet.status !== 'approved' && timesheet.status !== 'rejected' : false;

  React.useEffect(() => {
    if (!timesheet) return;
    if (summaryForm.employee_id) return;
    if (!extractedEmployeeMatch) return;
    setSummaryForm((current) => ({ ...current, employee_id: String(extractedEmployeeMatch.id) }));
  }, [timesheet?.id, summaryForm.employee_id, extractedEmployeeMatch]);

  if ((isTimesheetMode && isTimesheetLoading) || (isEmailMode && isEmailLoading)) {
    return <Loading message={isEmailMode ? 'Loading stored email...' : 'Loading staged submission...'} />;
  }

  if (!isTimesheetMode && !isEmailMode) {
    return (
      <div className="mx-auto mt-12 max-w-xl rounded-xl border border-border bg-card p-6">
        <p className="text-lg font-semibold text-foreground">Invalid review link</p>
        <p className="mt-2 text-sm text-muted-foreground">This page expects a valid timesheet or email identifier.</p>
        <button type="button" onClick={() => navigate('/ingestion/inbox')} className="action-button mt-4">
          Back to inbox
        </button>
      </div>
    );
  }

  if (isTimesheetMode && (isTimesheetError || !timesheet)) {
    return (
      <div className="mx-auto mt-12 max-w-xl rounded-xl border border-border bg-card p-6">
        <p className="text-lg font-semibold text-foreground">Submission not found</p>
        <p className="mt-2 text-sm text-muted-foreground">The selected submission may have been deleted or is no longer available.</p>
        <button type="button" onClick={() => navigate('/ingestion/inbox')} className="action-button mt-4">
          Back to inbox
        </button>
      </div>
    );
  }

  if (isEmailMode && (isEmailError || !storedEmail)) {
    return (
      <div className="mx-auto mt-12 max-w-xl rounded-xl border border-border bg-card p-6">
        <p className="text-lg font-semibold text-foreground">Email not found</p>
        <p className="mt-2 text-sm text-muted-foreground">The selected email may have been deleted or is no longer available.</p>
        <button type="button" onClick={() => navigate('/ingestion/inbox')} className="action-button mt-4">
          Back to inbox
        </button>
      </div>
    );
  }

  const openLineItemModal = (lineItem?: IngestionLineItem) => {
    if (lineItem) {
      setEditingLineItem(lineItem);
      setLineItemForm({
        work_date: lineItem.work_date,
        hours: String(lineItem.hours),
        description: lineItem.description ?? '',
        project_code: lineItem.project_code ?? '',
        project_id: lineItem.project_id ? String(lineItem.project_id) : '',
      });
    } else {
      setEditingLineItem(null);
      setLineItemForm(emptyLineItem());
    }
    setLineItemModalOpen(true);
  };

  const handleSaveSummary = async () => {
    if (!timesheet) return;
    await updateTimesheet.mutateAsync({ id: timesheet.id, data: {
      employee_id: summaryForm.employee_id ? Number(summaryForm.employee_id) : null,
      client_id: summaryForm.client_id ? Number(summaryForm.client_id) : null,
      supervisor_user_id: summaryForm.supervisor_user_id ? Number(summaryForm.supervisor_user_id) : null,
      period_start: summaryForm.period_start || null,
      period_end: summaryForm.period_end || null,
      total_hours: summaryForm.total_hours || null,
      internal_notes: summaryForm.internal_notes || null,
    } });
  };

  const handleSaveLineItem = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!timesheet) return;
    const payload = toLineItemPayload(lineItemForm);
    if (editingLineItem) await updateLineItem.mutateAsync({ timesheetId: timesheet.id, itemId: editingLineItem.id, data: payload });
    else if (payload.work_date && payload.hours) await addLineItem.mutateAsync({ timesheetId: timesheet.id, data: payload as Required<Pick<IngestionLineItemPayload, 'work_date' | 'hours'>> & IngestionLineItemPayload });
    setLineItemModalOpen(false);
  };

  const handleDeleteLineItem = async (lineItem: IngestionLineItem) => {
    if (!timesheet || !window.confirm(`Delete line item for ${lineItem.work_date}?`)) return;
    await deleteLineItem.mutateAsync({ timesheetId: timesheet.id, itemId: lineItem.id });
  };

  const handleApprove = async () => {
    if (!timesheet) return;
    const employeeIdForApproval = summaryForm.employee_id ? Number(summaryForm.employee_id) : (timesheet.employee_id ?? null);
    const clientIdForApproval = summaryForm.client_id ? Number(summaryForm.client_id) : (timesheet.client_id ?? null);

    if (!employeeIdForApproval) {
      window.alert('Select an employee before approving weeks.');
      return;
    }

    const siblingIds = siblings
      .filter((item) => item.status !== 'approved' && item.status !== 'rejected')
      .map((item) => item.id);
    const targetIds = siblingIds.length ? siblingIds : [timesheet.id];

    // Persist assignment for the currently edited week if it changed.
    const hasAssignmentChanges =
      (timesheet.employee_id ?? null) !== employeeIdForApproval ||
      (timesheet.client_id ?? null) !== clientIdForApproval;
    if (hasAssignmentChanges) {
      await updateTimesheet.mutateAsync({
        id: timesheet.id,
        data: {
          employee_id: employeeIdForApproval,
          client_id: clientIdForApproval,
        },
      });
    }

    let successCount = 0;
    const failures: string[] = [];

    for (const id of targetIds) {
      try {
        // Keep assignment aligned across sibling weeks before approval.
        await updateTimesheet.mutateAsync({
          id,
          data: {
            employee_id: employeeIdForApproval,
            client_id: clientIdForApproval,
          },
        });
        const result = await approveTimesheet.mutateAsync({ id, comment: reviewComment || undefined });
        successCount += 1;
        if (result?.overlapping_entries_count > 0) {
          failures.push(`Week #${id}: Approved, but ${result.overlapping_entries_count} date(s) already had existing time entries (${result.overlapping_dates?.join(', ')}). Check for duplicates.`);
        }
      } catch (error: unknown) {
        const detail =
          typeof error === 'object' && error !== null && 'response' in error
            ? ((error as { response?: { data?: { detail?: string } } }).response?.data?.detail || 'Approval failed')
            : 'Approval failed';
        failures.push(`Week #${id}: ${detail}`);
      }
    }

    if (successCount === 0 && failures.length > 0) {
      window.alert(failures.join('\n'));
      return;
    }

    navigate('/ingestion/inbox', {
      state: {
        banner: failures.length
          ? `Approved ${successCount} week(s). ${failures.length} failed.`
          : targetIds.length > 1
          ? `Approved ${targetIds.length} weeks successfully.`
          : `Approved week #${timesheet.id}. Time entries were created successfully.`,
      },
    });
  };

  const handleReject = async () => {
    if (!timesheet || !rejectReason.trim()) return;
    await rejectTimesheet.mutateAsync({ id: timesheet.id, reason: rejectReason, comment: reviewComment || undefined });
    setShowRejectPanel(false);
  };

  const handleHold = async () => {
    if (!timesheet) return;
    await holdTimesheet.mutateAsync({ id: timesheet.id, comment: reviewComment || undefined });
  };

  const handleRejectLineItem = async (itemId: number) => {
    if (!timesheet || !lineItemRejectReason.trim()) return;
    await rejectLineItem.mutateAsync({ timesheetId: timesheet.id, itemId, reason: lineItemRejectReason });
    setRejectingLineItemId(null);
    setLineItemRejectReason('');
  };

  const handleUnrejectLineItem = async (itemId: number) => {
    if (!timesheet) return;
    await unrejectLineItem.mutateAsync({ timesheetId: timesheet.id, itemId });
  };

  const handleRevertRejection = async () => {
    if (!timesheet) return;
    await revertTimesheetRejection.mutateAsync({ id: timesheet.id });
  };

  const handleDraftComment = async () => {
    if (!timesheet) return;
    const result = await draftComment.mutateAsync({ id: timesheet.id, seedText: reviewComment });
    setReviewComment(result.draft);
  };

  const handleReprocessEmail = async (attachmentIds?: number[]) => {
    if (!emailContext?.id) return;
    const response = await reprocessEmail.mutateAsync({ emailId: emailContext.id, attachmentIds });
    setReprocessJobId(response.job_id);
  };

  return (
    <div className="-m-6 flex h-[calc(100vh-64px)] flex-col overflow-hidden">
      {/* ── Top bar ─────────────────────────────────────────────────── */}
      <div className="flex shrink-0 items-center gap-3 border-b border-border/60 bg-[var(--bg-surface)] px-6 py-3">
        <button type="button" onClick={() => navigate('/ingestion/inbox')} className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition hover:text-foreground">
          <ArrowLeft className="h-4 w-4" /> Back to inbox
        </button>
        <div className="ml-1 min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-2">
            <span className="truncate text-[15px] font-semibold text-foreground">
              {emailContext?.subject || 'No subject'}
            </span>
            <span className="text-sm text-muted-foreground">
              from {emailContext?.sender_name || emailContext?.sender_email || 'Unknown'}
              {emailContext?.forwarded_from_email && (
                <span className="ml-1.5 inline-flex items-center gap-1 rounded bg-sky-50 px-1.5 py-0.5 text-xs font-medium text-sky-700">
                  Forwarded · originally from {emailContext.forwarded_from_name || emailContext.forwarded_from_email}
                </span>
              )}
            </span>
          </div>
        </div>
        {timesheet
          ? <Badge tone={timesheet.status === 'approved' ? 'success' : timesheet.status === 'rejected' ? 'danger' : 'info'}>{timesheet.status}</Badge>
          : <Badge tone="warning">{renderReason(storedEmail?.skip_reason)}</Badge>}
        {timesheet?.extracted_data?.extraction_confidence != null && (() => {
          const score = Number(timesheet.extracted_data.extraction_confidence);
          const uncertain = Array.isArray(timesheet.extracted_data.uncertain_fields)
            ? timesheet.extracted_data.uncertain_fields
            : [];
          const hasUncertain = uncertain.length > 0;
          const tone = hasUncertain
            ? 'bg-amber-50 text-amber-700'
            : score >= 0.8 ? 'bg-emerald-50 text-emerald-700'
            : score >= 0.5 ? 'bg-amber-50 text-amber-700'
            : 'bg-red-50 text-red-700';
          const tooltip = hasUncertain
            ? `Model self-rated. Uncertain fields: ${uncertain.join(', ')}. Verify before approving.`
            : 'Model self-rated extraction certainty — not a calibrated probability. Always verify the extracted fields against the source document.';
          return (
            <span
              className={`text-xs px-2 py-0.5 rounded ${tone}`}
              title={tooltip}
            >
              AI self-rated: {(score * 100).toFixed(0)}%
              {hasUncertain && ` · ${uncertain.length} uncertain`}
            </span>
          );
        })()}
        {isReprocessing && (
          <div className="flex items-center gap-2">
            <RefreshCw className="h-3.5 w-3.5 animate-spin text-primary" />
            <span className="text-xs text-primary font-medium">
              {reprocessStatus?.status === 'queued' ? 'Queued...' : `Reprocessing... ${Math.round(Number(reprocessStatus?.progress ?? 0))}%`}
            </span>
            <div className="h-1.5 w-24 overflow-hidden rounded-full bg-muted">
              <div className="h-full rounded-full bg-primary/60 transition-all duration-300" style={{ width: `${Number(reprocessStatus?.progress ?? 0)}%` }} />
            </div>
          </div>
        )}
        {reprocessDone && (
          <span className={`text-xs font-medium ${reprocessStatus?.status === 'complete' ? 'text-sky-600' : 'text-destructive'}`}>
            {reprocessStatus?.status === 'complete' ? 'Reprocessing complete.' : 'Reprocessing failed.'}
          </span>
        )}
        <div className="flex shrink-0 gap-2">
          <button type="button" onClick={() => handleReprocessEmail()} className="action-button-secondary" disabled={reprocessEmail.isPending || isReprocessing}>
            <RefreshCw className={`mr-1.5 h-4 w-4 ${isReprocessing ? 'animate-spin' : ''}`} /> {reprocessEmail.isPending ? 'Queueing...' : isReprocessing ? 'Reprocessing...' : 'Reprocess'}
          </button>
          {timesheet?.status === 'rejected' && (
            <button type="button" onClick={handleRevertRejection} className="action-button-secondary" disabled={revertTimesheetRejection.isPending}>
              <RefreshCw className="mr-1.5 h-4 w-4" /> {revertTimesheetRejection.isPending ? 'Reverting...' : 'Revert Rejection'}
            </button>
          )}
          {isActionable && <>
            <button type="button" onClick={handleHold} className="action-button-secondary" disabled={holdTimesheet.isPending}>
              <PauseCircle className="mr-1.5 h-4 w-4" /> {holdTimesheet.isPending ? 'Holding...' : 'On Hold'}
            </button>
            <div className="relative">
              <button type="button" onClick={() => setShowApproveConfirm((v) => !v)} className="action-button" disabled={approveTimesheet.isPending}>
                <Check className="mr-1.5 h-4 w-4" /> {approveTimesheet.isPending ? 'Approving...' : 'Approve'}
              </button>
              {showApproveConfirm && timesheet && (() => {
                const lineCount = timesheet.line_items.length;
                const totalHoursNum = timesheet.total_hours != null ? Number(timesheet.total_hours) : null;
                const summary = lineCount > 0
                  ? `Create ${lineCount} time ${lineCount === 1 ? 'entry' : 'entries'}?`
                  : totalHoursNum && totalHoursNum > 0
                    ? `Only ${totalHoursNum} total hours — no daily breakdown. Approve anyway?`
                    : 'Nothing to create. Approve anyway?';
                return (
                  <div className="absolute right-0 top-full z-30 mt-2 w-max max-w-[560px] rounded-lg border border-primary/30 bg-popover p-3 shadow-lg">
                    <p className="whitespace-nowrap text-sm text-foreground">{summary}</p>
                    <div className="mt-3 flex justify-end gap-2">
                      <button type="button" className="action-button-secondary" onClick={() => setShowApproveConfirm(false)}>Cancel</button>
                      <button type="button" className="action-button" disabled={approveTimesheet.isPending} onClick={handleApprove}>
                        {approveTimesheet.isPending ? 'Approving...' : 'Confirm'}
                      </button>
                    </div>
                  </div>
                );
              })()}
            </div>
          </>}
        </div>
      </div>

      {showRejectPanel && (
        <div className="shrink-0 border-b border-[var(--danger)]/20 bg-[var(--danger-light)] px-6 py-3">
          <p className="mb-2 text-sm font-medium text-[var(--danger)]">Reject submission</p>
          <textarea className="field-textarea" rows={2} value={rejectReason} onChange={(e) => setRejectReason(e.target.value)} placeholder="Reason is required" />
          <div className="mt-2 flex gap-2">
            <button type="button" className="action-button-secondary" onClick={() => setShowRejectPanel(false)}>Cancel</button>
            <button type="button" className="action-button" disabled={rejectTimesheet.isPending || !rejectReason.trim()} onClick={handleReject}>
              {rejectTimesheet.isPending ? 'Submitting...' : 'Submit Rejection'}
            </button>
          </div>
        </div>
      )}

      {/* ── Two-panel body ──────────────────────────────────────────── */}
      <div ref={containerRef} className="flex min-h-0 flex-1 overflow-hidden">
        {/* LEFT – email reader (single scrollable column) */}
        <div className="overflow-y-auto border-r border-border/60" style={{ flex: `0 0 ${leftPct}%`, minWidth: 0 }}>
          <div className="px-8 py-6">
            {/* Email header */}
            <div className="mb-4 space-y-1.5 border-b border-border/60 pb-4 text-sm">
              <p><span className="w-16 inline-block text-muted-foreground">From</span> <span className="text-foreground">{emailContext?.sender_name ? `${emailContext.sender_name} <${emailContext.sender_email}>` : emailContext?.sender_email || '--'}</span></p>
              {emailContext?.forwarded_from_email && (
                <p><span className="w-16 inline-block text-muted-foreground">Originally from</span> <span className="text-foreground">{emailContext.forwarded_from_name ? `${emailContext.forwarded_from_name} <${emailContext.forwarded_from_email}>` : emailContext.forwarded_from_email}</span></p>
              )}
              <p><span className="w-16 inline-block text-muted-foreground">Date</span> <span className="text-foreground">{formatDateTime(emailContext?.received_at)}</span></p>
            </div>

            {/* Body text */}
            <div className="mb-5 whitespace-pre-wrap text-sm text-foreground leading-relaxed">
              {emailContext?.body_text || <span className="italic text-muted-foreground">No plain-text body saved.</span>}
            </div>

            {/* Attachments */}
            {!!emailContext?.attachments?.length && (
              <div>
                <p className="mb-3 text-xs font-semibold uppercase tracking-widest text-muted-foreground">Attachments</p>
                <div className="space-y-3">
                  {emailContext.attachments.filter((att) => !timesheet || att.id === timesheet.attachment_id || !timesheet.attachment_id).map((att) => {
                    const isLinked = att.id === timesheet?.attachment_id;
                    const isSelected = att.id === selectedAttachmentId;
                    return (
                      <button
                        key={att.id}
                        type="button"
                        onClick={() => setSelectedAttachmentId(isSelected ? null : att.id)}
                        className={`flex w-full items-start gap-3 rounded-xl border px-4 py-3 text-left transition ${isSelected ? 'border-primary/40 bg-[var(--accent-light)]' : 'border-border/60 bg-muted/20 hover:border-primary/30 hover:bg-muted/40'}`}
                      >
                        <Paperclip className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-medium text-foreground">{att.filename}</p>
                          <div className="mt-1 flex flex-wrap gap-1">
                            {att.extraction_method && <Badge tone="info">{att.extraction_method}</Badge>}
                            <Badge tone="outline">{att.extraction_status}</Badge>
                            {isLinked && <Badge tone="success">linked to this record</Badge>}
                          </div>
                        </div>
                      </button>
                    );
                  })}
                </div>
                {linkedAttachment && (
                  <button type="button" onClick={() => handleReprocessEmail([linkedAttachment.id])} className="mt-3 inline-flex items-center gap-1.5 text-xs text-[var(--warning)] transition hover:text-[var(--accent-blue)]" disabled={reprocessEmail.isPending}>
                    <RefreshCw className="h-3.5 w-3.5" /> Reprocess linked attachment
                  </button>
                )}
              </div>
            )}
          </div>

          {/* Attachment preview — inline below email content, scrollable as one unit */}
          {selectedAttachment && (
            <div className="border-t border-border/60">
              <div className="flex flex-wrap items-center gap-3 border-b border-border/60 px-6 py-2.5">
                <p className="font-medium text-foreground">{selectedAttachment.filename}</p>
                <Badge tone="outline">{selectedAttachment.extraction_status}</Badge>
                {selectedAttachment.extraction_method && <Badge tone="info">{selectedAttachment.extraction_method}</Badge>}
                {selectedAttachment.rendered_html && (
                  <label className="ml-auto flex cursor-pointer items-center gap-2 text-xs text-muted-foreground">
                    <input
                      type="checkbox"
                      className="h-3.5 w-3.5 cursor-pointer"
                      checked={showFullSheet}
                      onChange={(e) => setShowFullSheet(e.target.checked)}
                    />
                    Show full sheet{fullSheetLoading && showFullSheet ? '…' : ''}
                  </label>
                )}
              </div>
              <div>
                {attachmentLoadError
                  ? <div className="px-6 py-10 text-sm text-[var(--danger)]">{attachmentLoadError}</div>
                  : selectedAttachmentType === 'pdf' && attachmentUrl
                    ? <iframe src={attachmentUrl} className="h-[75vh] w-full border-0" title={selectedAttachment.filename} />
                    : selectedAttachmentType === 'image' && attachmentUrl
                      ? <div className="flex items-center justify-center p-4"><img src={attachmentUrl} alt={selectedAttachment.filename} className="max-w-full rounded-2xl object-contain" /></div>
                      : selectedAttachment.rendered_html
                        ? <iframe srcDoc={showFullSheet && fullSheetHtml ? fullSheetHtml : selectedAttachment.rendered_html} className="h-[75vh] w-full border-0" title={selectedAttachment.filename} sandbox="" />
                        : selectedAttachment.spreadsheet_preview
                          ? <SpreadsheetPreviewTable preview={selectedAttachment.spreadsheet_preview} />
                          : selectedAttachment.raw_extracted_text
                            ? <pre className="whitespace-pre overflow-x-auto px-5 py-5 font-mono text-sm text-muted-foreground">{selectedAttachment.raw_extracted_text}</pre>
                            : <div className="px-6 py-10 text-sm text-muted-foreground">Preview unavailable for this attachment.</div>}
              </div>
            </div>
          )}
        </div>

        {/* Splitter */}
        <div
          className="group relative flex w-1.5 shrink-0 cursor-col-resize items-center justify-center bg-border/40 transition hover:bg-primary/30 active:bg-primary/50"
          onMouseDown={(e) => { e.preventDefault(); isDragging.current = true; document.body.style.cursor = 'col-resize'; document.body.style.userSelect = 'none'; }}
        >
          <div className="h-8 w-0.5 rounded-full bg-border group-hover:bg-primary/60 transition" />
        </div>

        {/* RIGHT – review panel */}
        <div className="flex min-w-0 flex-1 flex-col overflow-y-auto px-6 py-6">
          {/* Week tabs */}
          {siblings.length > 1 && (
            <div className="mb-5">
              <p className="mb-2 text-xs font-semibold uppercase tracking-widest text-muted-foreground">
                {siblings.length} timesheets from this email
              </p>
              <div className="flex flex-wrap gap-2">
                {siblings.map((s) => {
                  const isActive = s.id === timesheet?.id;
                  const label = s.period_start && s.period_end
                    ? `${new Date(s.period_start).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} – ${new Date(s.period_end).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`
                    : `#${s.id}`;
                  return (
                    <button
                      key={s.id}
                      type="button"
                      onClick={() => navigate(`/ingestion/review/${s.id}`)}
                      className={`rounded-full px-3 py-1.5 text-xs font-medium transition ${isActive ? 'bg-primary text-primary-foreground' : 'border border-border/60 bg-muted/30 text-muted-foreground hover:border-primary/30 hover:text-foreground'}`}
                    >
                      {label}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* Rejection reason banner */}
          {timesheet?.status === 'rejected' && timesheet.rejection_reason && (
            <div className="mb-5 rounded-md bg-[var(--danger-light)] border border-[var(--danger)]/20 px-4 py-3">
              <p className="text-xs uppercase tracking-[0.12em] text-[var(--danger)] font-medium mb-1">
                Rejection Reason
              </p>
              <p className="text-sm text-[var(--text-primary)]">
                {timesheet.rejection_reason}
              </p>
            </div>
          )}

          {/* Assignment */}
          {timesheet ? (
            <div className="space-y-5">
              <div>
                <p className="mb-3 text-xs font-semibold uppercase tracking-widest text-muted-foreground">Assignment</p>
                <div className="space-y-3">
                  <div>
                    <label className="mb-1.5 block text-sm font-medium text-foreground">Client</label>
                    <select className="field-input" value={summaryForm.client_id} onChange={(e) => setSummaryForm((c) => ({ ...c, client_id: e.target.value }))}>
                      <option value="">Select client</option>
                      {clients.map((client: { id: number; name: string }) => <option key={client.id} value={client.id}>{client.name}</option>)}
                    </select>
                    {extractedClientHint && !extractedClientMatchesExisting && !summaryForm.client_id && (
                      <div className="mt-2 flex flex-wrap items-center gap-2 rounded-md border border-border/60 bg-muted/30 px-3 py-2">
                        <p className="text-xs text-muted-foreground">
                          Extracted client: <span className="font-medium text-foreground">{extractedClientHint}</span> — not in your client list.
                        </p>
                        <button
                          type="button"
                          disabled={createClient.isPending}
                          onClick={async () => {
                            try {
                              const created = await createClient.mutateAsync({ name: extractedClientHint });
                              setSummaryForm((c) => ({ ...c, client_id: String(created.id) }));
                            } catch {
                              // Surface via generic error handling; leave the form as-is.
                            }
                          }}
                          className="text-xs font-medium text-primary hover:underline disabled:opacity-60"
                        >
                          {createClient.isPending ? 'Creating…' : `Create "${extractedClientHint}"`}
                        </button>
                      </div>
                    )}
                  </div>
                  <div>
                    <label className="mb-1.5 block text-sm font-medium text-foreground">Employee</label>
                    <select
                      className="field-input"
                      value={employeeSelectValue}
                      onChange={(e) => setSummaryForm((c) => ({ ...c, employee_id: e.target.value === '__extracted__' ? '' : e.target.value }))}
                    >
                      <option value="">Select employee</option>
                      {showExtractedEmployeeOption && (
                        <option value="__extracted__">Extracted: {extractedEmployeeDisplayName || extractedEmployeeHint} (unmatched)</option>
                      )}
                      {users.map((user) => <option key={user.id} value={user.id}>{cleanEmployeeNameForDisplay(user.full_name) || user.full_name}</option>)}
                    </select>
                    {extractedEmployeeHint && (
                      <p className="mt-1.5 text-xs text-muted-foreground">Extracted name: <span className="font-medium text-foreground">{extractedEmployeeDisplayName || extractedEmployeeHint}</span></p>
                    )}
                    <ChainCandidatesPanel
                      timesheetId={timesheet?.id ?? null}
                      rawSuggestions={timesheet?.llm_match_suggestions ?? null}
                      currentEmployeeId={timesheet?.employee_id ?? null}
                      onAssign={async (payload) => {
                        if (!timesheet) return;
                        await assignChainCandidate.mutateAsync({ id: timesheet.id, data: payload });
                      }}
                      isAssigning={assignChainCandidate.isPending}
                    />
                  </div>
                </div>

                {/* Supervisor: editable dropdown of tenant users.
                    Permissive model — any reviewer can override the
                    extracted name. The original LLM-extracted name is
                    kept on the record (and on every TimeEntry created
                    by approval) as an audit anchor regardless of the
                    reviewer's choice. */}
                <div className="mt-3">
                  <label className="mb-1.5 block text-sm font-medium text-foreground">Supervisor</label>
                  <select
                    className="field-input"
                    value={summaryForm.supervisor_user_id}
                    onChange={(e) => setSummaryForm((c) => ({ ...c, supervisor_user_id: e.target.value }))}
                  >
                    <option value="">No supervisor</option>
                    {users.map((u) => (
                      <option key={u.id} value={u.id}>{u.full_name}</option>
                    ))}
                  </select>
                  {timesheet?.extracted_supervisor_name && (
                    <p className="mt-1 text-xs text-muted-foreground">
                      Extracted from document: <span className="font-medium text-foreground">{timesheet.extracted_supervisor_name}</span>. Saved with the approved entries for audit.
                    </p>
                  )}
                </div>
              </div>

              {/* Week & Hours */}
              <div>
                <p className="mb-3 text-xs font-semibold uppercase tracking-widest text-muted-foreground">Week &amp; Hours</p>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="mb-1.5 block text-sm font-medium text-foreground">Week Start</label>
                    <input type="date" className="field-input" value={summaryForm.period_start} onChange={(e) => setSummaryForm((c) => ({ ...c, period_start: e.target.value }))} />
                  </div>
                  <div>
                    <label className="mb-1.5 block text-sm font-medium text-foreground">Week End</label>
                    <input type="date" className="field-input" value={summaryForm.period_end} onChange={(e) => setSummaryForm((c) => ({ ...c, period_end: e.target.value }))} />
                  </div>
                  <div>
                    <label className="mb-1.5 block text-sm font-medium text-foreground">Total Hours</label>
                    <input className="field-input" value={summaryForm.total_hours} onChange={(e) => setSummaryForm((c) => ({ ...c, total_hours: e.target.value }))} />
                  </div>
                </div>
              </div>

              <div>
                <label className="mb-1.5 block text-sm font-medium text-foreground">Internal Notes</label>
                <textarea className="field-textarea" rows={3} value={summaryForm.internal_notes} onChange={(e) => setSummaryForm((c) => ({ ...c, internal_notes: e.target.value }))} />
              </div>

              <div className="flex items-center justify-between">
                {timesheet?.created_at ? (
                  <p className="text-[11px] text-muted-foreground">
                    Processed by system · {formatDateTime(timesheet.created_at)}
                  </p>
                ) : <span />}
                <button type="button" onClick={handleSaveSummary} className="action-button" disabled={updateTimesheet.isPending}>
                  <Save className="mr-1.5 h-4 w-4" /> {updateTimesheet.isPending ? 'Saving...' : 'Save Summary'}
                </button>
              </div>

              {/* Line Items */}
              <div>
                <div className="mb-3 flex items-center justify-between">
                  <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">Line Items</p>
                  {isActionable && (
                    <button type="button" onClick={() => openLineItemModal()} className="inline-flex items-center gap-1 text-xs text-primary transition hover:opacity-75">
                      <Plus className="h-3.5 w-3.5" /> Add
                    </button>
                  )}
                </div>
                {timesheet.line_items.length === 0
                  ? <p className="text-sm text-muted-foreground">No line items yet.</p>
                  : (
                    <div className="space-y-2">
                      {timesheet.line_items.map((lineItem) => (
                        <div key={lineItem.id} className={`group rounded-lg border px-3 py-2.5 transition ${lineItem.is_rejected ? 'border-[var(--danger)]/30 bg-[var(--danger-light)]/40' : 'border-border/60 bg-muted/20 hover:bg-muted/40'}`}>
                          <div className="flex items-start justify-between gap-2">
                            <div className="min-w-0 flex-1">
                              <div className="flex flex-wrap items-center gap-1.5">
                                <span className={`font-mono text-sm font-medium ${lineItem.is_rejected ? 'line-through text-muted-foreground' : 'text-foreground'}`}>{format(new Date(lineItem.work_date + 'T00:00:00'), 'MMM d, yyyy (EEE)')}</span>
                                <span className={`font-mono text-sm ${lineItem.is_rejected ? 'line-through text-muted-foreground' : 'text-foreground'}`}>{Number(lineItem.hours).toFixed(1)}h</span>
                                {lineItem.is_rejected
                                  ? <Badge tone="danger">Excluded</Badge>
                                  : <Badge tone={lineItem.project_id ? 'info' : 'warning'}>{lineItem.project_id ? `Project #${lineItem.project_id}` : 'Needs project'}</Badge>}
                                {lineItem.is_corrected && !lineItem.is_rejected && <Badge tone="outline">Corrected</Badge>}
                                {lineItem.is_corrected && !lineItem.is_rejected && lineItem.original_value && (
                                  <span className="text-xs text-muted-foreground ml-2">
                                    (was: {Number(lineItem.original_value.hours).toFixed(1)}h on {String(lineItem.original_value.work_date)})
                                  </span>
                                )}
                              </div>
                              <p className={`mt-0.5 truncate text-xs ${lineItem.is_rejected ? 'line-through text-muted-foreground' : 'text-muted-foreground'}`}>{lineItem.description || 'No description'} · Code {lineItem.project_code || '--'}</p>
                              {lineItem.is_rejected && lineItem.rejection_reason && (
                                <p className="mt-1 text-xs text-[var(--danger)]">Reason: {lineItem.rejection_reason}</p>
                              )}
                              {rejectingLineItemId === lineItem.id && (
                                <div className="mt-2 flex gap-2">
                                  <input
                                    className="field-input h-7 flex-1 text-xs"
                                    value={lineItemRejectReason}
                                    onChange={(e) => setLineItemRejectReason(e.target.value)}
                                    placeholder="Rejection reason (required)"
                                    autoFocus
                                  />
                                  <button type="button" onClick={() => handleRejectLineItem(lineItem.id)} disabled={!lineItemRejectReason.trim() || rejectLineItem.isPending} className="action-button h-7 px-2 text-xs">Confirm</button>
                                  <button type="button" onClick={() => { setRejectingLineItemId(null); setLineItemRejectReason(''); }} className="action-button-secondary h-7 px-2 text-xs">Cancel</button>
                                </div>
                              )}
                            </div>
                            <div className="flex shrink-0 gap-1 opacity-0 transition group-hover:opacity-100">
                              {isActionable && !lineItem.is_rejected && (
                                <>
                                  <button type="button" onClick={() => openLineItemModal(lineItem)} className="action-button-secondary h-7 px-2 text-xs">Edit</button>
                                  <button type="button" onClick={() => handleDeleteLineItem(lineItem)} className="action-button-secondary h-7 px-2 text-xs"><Trash2 className="h-3.5 w-3.5" /></button>
                                  <button type="button" onClick={() => { setRejectingLineItemId(lineItem.id); setLineItemRejectReason(''); }} className="h-7 px-2 text-xs rounded border border-[var(--danger)]/30 text-[var(--danger)] hover:bg-[var(--danger-light)] transition">Exclude</button>
                                </>
                              )}
                              {lineItem.is_rejected && (
                                <button type="button" onClick={() => handleUnrejectLineItem(lineItem.id)} disabled={unrejectLineItem.isPending} className="h-7 px-2 text-xs rounded border border-border/60 text-foreground hover:bg-muted/40 transition">Restore</button>
                              )}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                {!!timesheet.line_items.length && (
                  <p className="mt-2 text-xs text-muted-foreground">
                    Project assignment must be resolved on every line item before approval can create real time entries.
                  </p>
                )}
              </div>

              {/* AI Flags */}
              {!!timesheet.llm_anomalies?.length && (
                <div>
                  <p className="mb-3 text-xs font-semibold uppercase tracking-widest text-muted-foreground">AI Flags</p>
                  <div className="space-y-2">
                    {timesheet.llm_anomalies.map((anomaly, index) => (
                      <div key={index} className="rounded-xl border border-[var(--warning)]/25 bg-[var(--warning-light)] px-3 py-2.5 text-sm text-[var(--warning)]">
                        <span className="font-semibold">{(anomaly.type as string) || 'Anomaly'}:</span>{' '}
                        <span className="text-[var(--text-primary)]">{(anomaly.description as string) || 'Check this item.'}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Reviewer Actions */}
              <div>
                <p className="mb-3 text-xs font-semibold uppercase tracking-widest text-muted-foreground">Reviewer Actions</p>
                <div className="space-y-3">
                  <div>
                    <label className="mb-1.5 block text-sm font-medium text-foreground">Comment</label>
                    <textarea className="field-textarea" rows={3} value={reviewComment} onChange={(e) => setReviewComment(e.target.value)} />
                  </div>
                  {isActionable && (
                    <div>
                      <label className="mb-1.5 block text-sm font-medium text-foreground">Reject Reason</label>
                      <input className="field-input" value={rejectReason} onChange={(e) => setRejectReason(e.target.value)} placeholder="Required for rejection" />
                    </div>
                  )}
                  <div className="grid gap-2">
                    <button type="button" onClick={handleDraftComment} className="action-button-secondary" disabled={draftComment.isPending}>
                      <Bot className="mr-1.5 h-4 w-4" /> {draftComment.isPending ? 'Drafting...' : 'Draft AI Comment'}
                    </button>
                    {isActionable && <>
                      <button type="button" onClick={handleHold} className="action-button-secondary" disabled={holdTimesheet.isPending}>
                        <PauseCircle className="mr-1.5 h-4 w-4" /> {holdTimesheet.isPending ? 'Holding...' : 'Place On Hold'}
                      </button>
                      <button type="button" onClick={() => setShowRejectPanel((current) => !current)} className="action-button-secondary" disabled={rejectTimesheet.isPending}>
                        <XCircle className="mr-1.5 h-4 w-4" /> Reject Submission
                      </button>
                    </>}
                  </div>
                </div>
              </div>

              {/* Audit Trail */}
              {!!timesheet.audit_log?.length && (
                <div>
                  <p className="mb-3 text-xs font-semibold uppercase tracking-widest text-muted-foreground">Audit Trail</p>
                  <div className="space-y-2">
                    {timesheet.audit_log.map((entry) => (
                      <div key={entry.id} className="rounded-xl border border-border/60 bg-muted/20 px-3 py-2.5">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <p className="text-sm font-medium text-foreground">{entry.action.replace(/_/g, ' ')}</p>
                          <p className="text-xs text-muted-foreground">{formatDateTime(entry.created_at)}</p>
                        </div>
                        {entry.comment && <p className="mt-1 text-xs text-muted-foreground">{entry.comment}</p>}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            /* Diagnostic view (email-only mode) */
            <div className="space-y-4">
              <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">Diagnostic Summary</p>
              <div className="rounded-xl border border-border/60 bg-muted/20 px-4 py-3 space-y-2 text-sm">
                <p className="text-muted-foreground">Mailbox: <span className="text-foreground">{storedEmail?.mailbox_label || '--'}</span></p>
                <p className="text-muted-foreground">Classifier intent: <span className="text-foreground">{storedEmail?.classification_intent || 'unknown'}</span></p>
                <p className="text-muted-foreground">Skip reason: <span className="text-foreground">{renderReason(storedEmail?.skip_reason)}</span></p>
              </div>
              {storedEmail?.skip_detail && <p className="text-sm text-muted-foreground">{storedEmail.skip_detail}</p>}
              {!!storedEmail?.llm_classification?.reasoning && (
                <div className="rounded-xl border border-border/60 bg-muted/20 px-4 py-3 text-sm text-muted-foreground">
                  {String(storedEmail.llm_classification.reasoning)}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {timesheet && <Modal open={lineItemModalOpen} onClose={() => setLineItemModalOpen(false)} title={editingLineItem ? 'Edit Line Item' : 'Add Line Item'} description="Project assignment can be by code, direct project id, or both.">
        <form onSubmit={handleSaveLineItem} className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2">
            <div><label className="mb-2 block text-sm font-medium text-foreground">Work Date</label><input type="date" className="field-input" value={lineItemForm.work_date} onChange={(e) => setLineItemForm((c) => ({ ...c, work_date: e.target.value }))} required /></div>
            <div><label className="mb-2 block text-sm font-medium text-foreground">Hours</label><input className="field-input" value={lineItemForm.hours} onChange={(e) => setLineItemForm((c) => ({ ...c, hours: e.target.value }))} required /></div>
          </div>
          <div><label className="mb-2 block text-sm font-medium text-foreground">Description</label><textarea className="field-textarea" rows={3} value={lineItemForm.description} onChange={(e) => setLineItemForm((c) => ({ ...c, description: e.target.value }))} /></div>
          <div className="grid gap-4 md:grid-cols-2">
            <div><label className="mb-2 block text-sm font-medium text-foreground">Project Code</label><input className="field-input" value={lineItemForm.project_code} onChange={(e) => setLineItemForm((c) => ({ ...c, project_code: e.target.value }))} /></div>
            <div><label className="mb-2 block text-sm font-medium text-foreground">Project</label><select className="field-input" value={lineItemForm.project_id} onChange={(e) => setLineItemForm((c) => ({ ...c, project_id: e.target.value }))}><option value="">No direct project</option>{projects.map((project: { id: number; name: string }) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></div>
          </div>
          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={() => setLineItemModalOpen(false)} className="action-button-secondary">Cancel</button>
            <button type="submit" className="action-button" disabled={addLineItem.isPending || updateLineItem.isPending}>{addLineItem.isPending || updateLineItem.isPending ? 'Saving...' : editingLineItem ? 'Save Line Item' : 'Add Line Item'}</button>
          </div>
        </form>
      </Modal>}
    </div>
  );
};
