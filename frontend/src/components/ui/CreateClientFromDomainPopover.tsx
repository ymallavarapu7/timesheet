import React from 'react';

import { cn } from '@/lib/utils';

interface ExistingClient {
  id: number;
  name: string;
}

export interface CreateClientFromDomainPopoverProps {
  /** Whether the popover is rendered. */
  open: boolean;
  /** The bare email domain whose mapping is being created (e.g. "dxc.com"). */
  domain: string;
  /** How many pending rows from this domain will cascade-resolve. Used for the
   *  count suffix and the primary button label. */
  cascadeCount: number;
  /** All existing clients in the tenant. Used to fuzzy-match the smart-guess
   *  to an existing client name, and to flip the primary button between
   *  "Link to X" and "Create" based on what the user has typed. */
  existingClients: ExistingClient[];
  /** Anchor element to position the popover below (or above when there isn't
   *  enough room below). Captured at click time. */
  anchorEl: HTMLElement | null;
  /** Pre-fill text for the input. Pass the smart-guess from the domain (or the
   *  matched existing client name) here. The user can edit freely. */
  initialValue: string;
  /** Whether the underlying mutation is in flight. Disables the primary button. */
  isSubmitting?: boolean;
  /** Called on confirm. `existing` set if the name matches a client. */
  onConfirm: (payload: { name: string; existing: ExistingClient | null }) => void;
  /** Cancel / overlay click / escape key. */
  onClose: () => void;
}

const POPOVER_WIDTH = 380;
const POPOVER_ESTIMATED_HEIGHT = 280;
const VIEWPORT_MARGIN = 16;

const findExistingByName = (
  value: string,
  clients: ExistingClient[],
): ExistingClient | null => {
  const q = value.trim().toLowerCase();
  if (!q) return null;
  return clients.find((c) => c.name.toLowerCase() === q) ?? null;
};

export const CreateClientFromDomainPopover: React.FC<CreateClientFromDomainPopoverProps> = ({
  open,
  domain,
  cascadeCount,
  existingClients,
  anchorEl,
  initialValue,
  isSubmitting,
  onConfirm,
  onClose,
}) => {
  const [value, setValue] = React.useState(initialValue);
  const inputRef = React.useRef<HTMLInputElement>(null);
  const [position, setPosition] = React.useState<{ top: number; left: number } | null>(null);

  // Reset value when the popover opens for a new anchor / domain. We key on
  // `open + initialValue` so a re-open with a different smart-guess actually
  // re-fills the input rather than carrying over stale text.
  React.useEffect(() => {
    if (open) setValue(initialValue);
  }, [open, initialValue]);

  // Compute anchor position. Done with a layout effect so we read the rect
  // immediately after the popover is rendered (and on window resize).
  React.useLayoutEffect(() => {
    if (!open || !anchorEl) return;
    const updatePosition = () => {
      const rect = anchorEl.getBoundingClientRect();
      const spaceBelow = window.innerHeight - rect.bottom;
      const top = spaceBelow > POPOVER_ESTIMATED_HEIGHT + VIEWPORT_MARGIN
        ? rect.bottom + window.scrollY + 6
        : rect.top + window.scrollY - POPOVER_ESTIMATED_HEIGHT - 6;
      const maxLeft = window.innerWidth - POPOVER_WIDTH - VIEWPORT_MARGIN;
      const left = Math.min(rect.left + window.scrollX, maxLeft);
      setPosition({ top, left });
    };
    updatePosition();
    window.addEventListener('resize', updatePosition);
    window.addEventListener('scroll', updatePosition, true);
    return () => {
      window.removeEventListener('resize', updatePosition);
      window.removeEventListener('scroll', updatePosition, true);
    };
  }, [open, anchorEl]);

  // Focus the input and select its content so a single keystroke replaces
  // whatever was pre-filled.
  React.useEffect(() => {
    if (!open) return;
    const id = window.requestAnimationFrame(() => {
      inputRef.current?.focus();
      inputRef.current?.select();
    });
    return () => window.cancelAnimationFrame(id);
  }, [open]);

  // Escape closes the popover.
  React.useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open || !position) return null;

  const trimmed = value.trim();
  const exact = findExistingByName(trimmed, existingClients);
  const canSubmit = trimmed.length > 0 && !isSubmitting;

  const handleConfirm = () => {
    if (!canSubmit) return;
    onConfirm({ name: trimmed, existing: exact });
  };

  // When cascadeCount is 0 (or domain is missing) the popover is being
  // used for a one-off client create rather than a cascade — show plain
  // labels and skip the "N pending emails will be assigned" preamble.
  const cascadeMode = Boolean(domain) && cascadeCount > 0;
  const cascadeSuffix = cascadeMode ? ` · assign ${cascadeCount}` : '';
  const buttonLabel = !trimmed
    ? `Create${cascadeSuffix}`
    : exact
      ? `Link to ${exact.name}${cascadeSuffix}`
      : `Create "${trimmed}"${cascadeSuffix}`;
  const headerLabel = cascadeMode ? 'Assign client from domain' : 'Add client';

  return (
    <>
      <div
        role="presentation"
        className="fixed inset-0 z-[80]"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-label={headerLabel}
        className={cn(
          'absolute z-[90] rounded-xl border border-border/70 bg-card shadow-[0_18px_48px_rgba(0,0,0,0.35)]',
          'p-4',
        )}
        style={{ top: position.top, left: position.left, width: POPOVER_WIDTH }}
        onClick={(e) => e.stopPropagation()}
      >
        <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">
          {headerLabel}
        </p>
        {cascadeMode ? (
          <p className="mb-3 text-xs text-muted-foreground">
            All <span className="font-semibold text-amber-700 dark:text-amber-300">{cascadeCount} pending email{cascadeCount === 1 ? '' : 's'}</span>
            {' '}from <span className="font-mono text-amber-700 dark:text-amber-300">{domain}</span> will be assigned.
          </p>
        ) : domain ? (
          <p className="mb-3 text-xs text-muted-foreground">
            Will also map <span className="font-mono text-foreground">{domain}</span> to this client so future emails from that domain auto-resolve.
          </p>
        ) : (
          <p className="mb-3 text-xs text-muted-foreground">
            Create a new client. The sender's domain is personal (gmail, outlook, etc.) so no domain mapping is added.
          </p>
        )}

        <label className="mb-1 block text-xs font-medium text-muted-foreground" htmlFor="cascade-name-input">
          Client name
        </label>
        <input
          id="cascade-name-input"
          ref={inputRef}
          type="text"
          className="field-input"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              handleConfirm();
            }
          }}
          autoComplete="off"
          spellCheck={false}
        />

        {exact ? (
          <div className="mt-2 flex items-center justify-between gap-3 rounded-md border border-emerald-400/30 bg-emerald-500/5 px-3 py-2">
            <div className="min-w-0">
              <p className="text-[11px] uppercase tracking-wider text-muted-foreground">Matches existing client</p>
              <p className="truncate text-sm font-semibold text-emerald-700 dark:text-emerald-300">{exact.name}</p>
            </div>
            <p className="max-w-[9.5rem] text-right text-[11px] leading-tight text-muted-foreground">
              Confirm to link the domain. Edit the name to create a new client.
            </p>
          </div>
        ) : null}

        <p className="mt-3 text-[11px] text-muted-foreground">
          Tip: Press Enter to confirm, or edit the name first.
        </p>

        <div className="mt-3 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="action-button-secondary"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            disabled={!canSubmit}
            className="action-button disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isSubmitting ? 'Assigning...' : buttonLabel}
          </button>
        </div>
      </div>
    </>
  );
};
