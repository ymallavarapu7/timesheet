import React from 'react';

interface DashboardGreetingProps {
  /** The full name of the logged-in user. We use the first token as
   *  the salutation: "Good afternoon, Bharat." Falls back to a
   *  time-only greeting when null/empty. */
  userFullName?: string | null;
  /** Optional override for the date label that sits below the
   *  greeting. Defaults to today in the user's locale. */
  dateLabel?: string;
}

const greetingPrefix = (): string => {
  const h = new Date().getHours();
  if (h < 12) return 'Good morning';
  if (h < 18) return 'Good afternoon';
  return 'Good evening';
};

export const DashboardGreeting: React.FC<DashboardGreetingProps> = ({
  userFullName,
  dateLabel,
}) => {
  const firstName = (userFullName ?? '').trim().split(/\s+/)[0] || '';
  const greeting = firstName
    ? `${greetingPrefix()}, ${firstName}.`
    : `${greetingPrefix()}.`;

  const today = dateLabel
    ?? new Date().toLocaleDateString(undefined, {
      weekday: 'long',
      month: 'short',
      day: 'numeric',
    });

  return (
    <div className="mb-4">
      <p className="text-[11px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">
        {today}
      </p>
      <h1 className="mt-0.5 text-2xl font-semibold text-foreground">{greeting}</h1>
    </div>
  );
};
