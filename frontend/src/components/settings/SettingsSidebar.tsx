import React from 'react';

const iconProps = {
  width: 14, height: 14, viewBox: '0 0 24 24',
  fill: 'none', stroke: 'currentColor', strokeWidth: 1.5,
  strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const,
};

const ClockIcon   = () => <svg {...iconProps}><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>;
const CalIcon     = () => <svg {...iconProps}><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>;
const LockIcon    = () => <svg {...iconProps}><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>;
const BellIcon    = () => <svg {...iconProps}><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>;
const ListIcon    = () => <svg {...iconProps}><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>;
const MailIcon    = () => <svg {...iconProps}><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>;

type NavItem = { key: string; label: string; icon: React.ReactNode };
type NavGroup = { title: string; items: NavItem[] };

const NAV: NavGroup[] = [
  {
    title: 'Time management',
    items: [
      { key: 'time-entry',      label: 'Time entry',        icon: <ClockIcon /> },
      { key: 'timeoff-policy',  label: 'Time-off policy',   icon: <CalIcon /> },
    ],
  },
  {
    title: 'Access & security',
    items: [
      { key: 'security',    label: 'Security',    icon: <LockIcon /> },
    ],
  },
  {
    title: 'Notifications',
    items: [
      { key: 'reminders',     label: 'Reminders',     icon: <BellIcon /> },
      { key: 'notifications', label: 'Notifications', icon: <ListIcon /> },
    ],
  },
  {
    title: 'Integrations',
    items: [
      { key: 'email-smtp',      label: 'Email / SMTP',    icon: <MailIcon /> },
    ],
  },
];

interface Props {
  activeSection: string;
  onChange: (key: string) => void;
}

export const SettingsSidebar: React.FC<Props> = ({ activeSection, onChange }) => (
  <nav
    className="shrink-0 overflow-y-auto border-r border-border"
    style={{ width: 210, minHeight: 0 }}
  >
    <div className="px-4 pt-5 pb-2">
      <h2 className="text-base font-semibold tracking-tight text-foreground">Settings</h2>
      <p className="text-xs text-muted-foreground mt-0.5">Tenant-wide policies</p>
    </div>

    <div className="px-2 pb-4">
      {NAV.map((group, gi) => (
        <div key={group.title}>
          {gi > 0 && <hr className="my-[7px] mx-[14px] border-border" />}
          <p className="px-2 pt-3 pb-1.5 text-xs font-semibold uppercase tracking-[0.65px] text-muted-foreground/50 select-none">
            {group.title}
          </p>
          {group.items.map((item) => {
            const active = activeSection === item.key;
            return (
              <button
                key={item.key}
                type="button"
                onClick={() => onChange(item.key)}
                className={`
                  group w-full flex items-center gap-2.5 rounded-lg px-2.5 py-[7px] text-xs font-medium
                  border-l-2 transition-all duration-150
                  ${active
                    ? 'border-primary bg-primary/[0.07] text-foreground'
                    : 'border-transparent text-muted-foreground hover:bg-muted/60 hover:text-foreground'
                  }
                `}
              >
                <span className={`shrink-0 transition-opacity ${active ? 'opacity-100' : 'opacity-[0.55] group-hover:opacity-80'}`}>
                  {item.icon}
                </span>
                {item.label}
              </button>
            );
          })}
        </div>
      ))}
    </div>
  </nav>
);
