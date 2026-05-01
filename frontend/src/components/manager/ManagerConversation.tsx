import React from 'react';
import { useNavigate } from 'react-router-dom';

import type { ManagerTeamOverviewResponse } from '@/types';

interface ManagerConversationProps {
  overview: ManagerTeamOverviewResponse | undefined;
  /** When true, surface the email-ingestion line and "Open inbox" action. */
  ingestionEnabled?: boolean;
  pendingIngestionCount?: number;
  ingestionErrorsCount?: number;
}

const ageLabel = (hours: number | null | undefined): string => {
  if (hours == null) return '';
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
};

export const ManagerConversation: React.FC<ManagerConversationProps> = ({
  overview,
  ingestionEnabled,
  pendingIngestionCount = 0,
  ingestionErrorsCount = 0,
}) => {
  const navigate = useNavigate();

  if (!overview) {
    return (
      <div className="rounded-lg border bg-card p-6 mb-4 shadow-[0_1px_2px_rgba(0,0,0,0.05)]">
        <p className="text-sm text-muted-foreground">Loading your priorities...</p>
      </div>
    );
  }

  const onTrack = overview.members.filter((m) =>
    !m.is_repeatedly_late
    && !m.is_on_pto_today
    && (m.working_days_in_week === 0 || m.submitted_days >= m.working_days_in_week)
  ).length;

  const critical = overview.members.filter((m) => m.is_repeatedly_late);
  const behind = overview.members.filter((m) =>
    !m.is_repeatedly_late
    && !m.is_on_pto_today
    && m.working_days_in_week > 0
    && m.submitted_days < m.working_days_in_week
  );
  const ptoToday = overview.members.filter((m) => m.is_on_pto_today);

  const fragments: React.ReactNode[] = [];

  // Suppress alarming framings when the team simply hasn't entered time yet.
  const noSubmissionsYet = overview.team_size > 0
    && critical.length === 0
    && behind.length === 0
    && ptoToday.length === 0
    && overview.members.every((m) => m.submitted_days === 0);

  if (overview.team_size === 0) {
    fragments.push(
      <span key="empty"><strong>You have no direct reports right now.</strong> The page below still shows your project and approval signals.{' '}</span>,
    );
  } else if (onTrack === overview.team_size) {
    fragments.push(
      <span key="all-good" className="convo-good">Everyone on your team is on track for the week.</span>,
    );
    fragments.push(<span key="sp-good"> </span>);
  } else if (noSubmissionsYet) {
    fragments.push(
      <span key="early">No entries from your team yet this week.{' '}</span>,
    );
  } else {
    if (critical.length > 0) {
      // Render each follow-up name as a clickable link so the
      // manager can drill straight into that person's approvals
      // queue. Colored, not highlighted: no background fill.
      const linkable = critical.slice(0, 2);
      fragments.push(
        <span key="crit">
          {linkable.map((m, i) => (
            <React.Fragment key={m.user_id}>
              <button
                type="button"
                onClick={() => navigate(`/approvals?user_id=${m.user_id}`)}
                className="convo-link"
              >
                {m.full_name.split(' ')[0]}
              </button>
              {i < linkable.length - 1 ? ' and ' : ''}
            </React.Fragment>
          ))}
          {' '}{critical.length === 1 ? 'needs' : 'need'} follow-up
          {critical.length === 1 ? ', missed multiple deadlines recently' : '. Both have missed multiple deadlines recently'}.{' '}
        </span>,
      );
    }
    if (behind.length > 0) {
      // Make the "N others" count clickable too, leading to the
      // approvals queue scoped to the team's pending entries.
      fragments.push(
        <span key="behind">
          <button
            type="button"
            onClick={() => navigate('/approvals')}
            className="convo-link"
          >
            {behind.length} {behind.length === 1 ? 'other' : 'others'}
          </button>
          {' '}haven't logged all of this week's days yet.{' '}
        </span>,
      );
    }
    if (ptoToday.length > 0) {
      fragments.push(
        <span key="pto">
          <strong>{ptoToday.length} on PTO today.</strong>{' '}
        </span>,
      );
    }
  }

  if (overview.pending_approvals_count > 0) {
    const oldestH = overview.pending_approvals_oldest_hours;
    const ageWord =
      oldestH == null ? '' :
      oldestH < 12 ? 'today' :
      oldestH < 36 ? 'yesterday' :
      'older';
    fragments.push(
      <span key="appr">
        <button
          type="button"
          onClick={() => navigate('/approvals')}
          className="convo-link"
        >
          {overview.pending_approvals_count} {overview.pending_approvals_count === 1 ? 'timesheet entry' : 'timesheet entries'}
        </button>
        {' '}{overview.pending_approvals_count === 1 ? 'is' : 'are'} waiting on your approval
        {ageWord ? <> ({ageWord})</> : null}
        .{' '}
      </span>,
    );
  }

  if (ingestionEnabled && pendingIngestionCount > 0) {
    fragments.push(
      <span key="inbox">
        And{' '}
        <button
          type="button"
          onClick={() => navigate('/ingestion/inbox')}
          className="convo-link"
        >
          {pendingIngestionCount} {pendingIngestionCount === 1 ? 'timesheet' : 'timesheets'} in the email inbox
        </button>
        {' '}{pendingIngestionCount === 1 ? 'is' : 'are'} waiting for you to review
        {ingestionErrorsCount > 0 ? <>, including <strong>{ingestionErrorsCount} {ingestionErrorsCount === 1 ? 'extraction error' : 'extraction errors'}</strong></> : null}
        .
      </span>,
    );
  }

  // Action buttons. Approvals is primary if there are any; otherwise
  // we offer a calmer single CTA.
  const actions: { label: string; primary?: boolean; onClick: () => void }[] = [];
  if (overview.pending_approvals_count > 0) {
    actions.push({
      label: `Review approvals (${overview.pending_approvals_count})`,
      primary: true,
      onClick: () => navigate('/approvals'),
    });
  }
  if (ingestionEnabled && pendingIngestionCount > 0) {
    actions.push({
      label: `Open inbox (${pendingIngestionCount})`,
      primary: actions.length === 0,
      onClick: () => navigate('/ingestion/inbox'),
    });
  }
  if (behind.length > 0) {
    actions.push({
      label: `Send reminder (${behind.length})`,
      onClick: () => navigate('/approvals'),
    });
  }
  if (critical.length > 0) {
    actions.push({
      // Button copy mirrors the paragraph: avoid "critical", say what
      // the manager will actually do (open the follow-up list).
      label: `Open follow-ups (${critical.length})`,
      onClick: () => navigate('/approvals'),
    });
  }
  if (actions.length === 0) {
    actions.push({ label: 'View team', onClick: () => {} });
  }

  return (
    <div className="rounded-lg border bg-card p-6 mb-4 shadow-[0_1px_2px_rgba(0,0,0,0.05)] manager-convo">
      <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">
        {new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' })}
      </p>
      <p className="text-base leading-relaxed text-foreground">{fragments}</p>
      <div className="mt-5 flex flex-wrap gap-2">
        {actions.map((a) => (
          <button
            key={a.label}
            type="button"
            onClick={a.onClick}
            className={`rounded-md px-3 py-2 text-sm font-medium transition ${
              a.primary
                ? 'bg-primary text-primary-foreground hover:opacity-90'
                : 'border border-border bg-card text-foreground hover:border-primary/40'
            }`}
          >
            {a.label}
          </button>
        ))}
      </div>
      <style>{`
        /* Color-only emphasis for clickable counts and names. No
           background fill (avoids the highlighter look). Underline on
           hover so it reads as interactive. */
        .manager-convo .convo-link {
          background: transparent;
          border: none;
          padding: 0;
          margin: 0;
          cursor: pointer;
          font: inherit;
          font-weight: 600;
          color: rgb(146, 64, 14);
          text-decoration: none;
        }
        .dark .manager-convo .convo-link { color: rgb(252, 211, 77); }
        .manager-convo .convo-link:hover { text-decoration: underline; }
        .manager-convo .convo-link:focus-visible {
          outline: 2px solid currentColor;
          outline-offset: 2px;
          border-radius: 3px;
        }
        .manager-convo .convo-good {
          color: rgb(6, 95, 70);
          font-weight: 600;
        }
        .dark .manager-convo .convo-good { color: rgb(110, 231, 183); }
      `}</style>
    </div>
  );
};
