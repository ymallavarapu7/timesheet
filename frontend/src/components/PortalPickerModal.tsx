import React from 'react';
import { ArrowRight, Briefcase, Eye, ShieldCheck } from 'lucide-react';

import type { UserRole } from '@/types';

interface PortalPickerModalProps {
  isOpen: boolean;
  /** Roles the user is allowed to act as. Picker shows one button per
   *  role. Single-element lists should never invoke the picker; the
   *  caller is responsible for that gate. */
  roles: UserRole[];
  /** Currently active role, highlighted as a hint about which portal
   *  the user landed in last time. Optional. */
  currentRole?: UserRole;
  /** Called when the user picks a role. The caller drives the actual
   *  /auth/switch-role round trip and any post-pick navigation. */
  onPick: (role: UserRole) => void;
  /** Disable buttons while a switch is in flight so a user can't
   *  trigger two flips at once. */
  pending?: boolean;
}

const PORTAL_LABEL: Partial<Record<UserRole, string>> = {
  ADMIN: 'Admin',
  MANAGER: 'Manager',
  VIEWER: 'Viewer',
  EMPLOYEE: 'Employee',
};

const PORTAL_DESCRIPTION: Partial<Record<UserRole, string>> = {
  ADMIN: 'Tenant settings, users, clients, projects, and audit trail.',
  MANAGER: 'Approvals, reviewer inbox, and team oversight.',
  VIEWER: 'Tenant-wide read-only oversight.',
  EMPLOYEE: 'Your own time entries, time off, and calendar.',
};

const PORTAL_ICON: Partial<Record<UserRole, React.ComponentType<{ className?: string }>>> = {
  ADMIN: Briefcase,
  MANAGER: ShieldCheck,
  VIEWER: Eye,
  EMPLOYEE: Briefcase,
};

export const PortalPickerModal: React.FC<PortalPickerModalProps> = ({
  isOpen,
  roles,
  currentRole,
  onPick,
  pending = false,
}) => {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-2xl border border-border bg-card p-6 shadow-[0_18px_40px_rgba(0,0,0,0.2)]">
        <h2 className="text-xl font-semibold text-foreground">Choose your portal</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          You have access to more than one role. Pick where to start; you can switch later from the topbar.
        </p>

        <div className="mt-5 space-y-2">
          {roles.map((role) => {
            const Icon = PORTAL_ICON[role] ?? Briefcase;
            const label = PORTAL_LABEL[role] ?? role;
            const description = PORTAL_DESCRIPTION[role] ?? '';
            const isCurrent = currentRole === role;
            return (
              <button
                key={role}
                type="button"
                onClick={() => onPick(role)}
                disabled={pending}
                className="group flex w-full items-center gap-3 rounded-xl border border-border bg-background/40 px-4 py-3 text-left transition hover:border-primary/40 hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 disabled:opacity-60"
              >
                <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-primary/30 bg-primary/10 text-primary">
                  <Icon className="h-4 w-4" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-2">
                    <span className="block truncate text-sm font-semibold text-foreground">
                      Continue as {label}
                    </span>
                    {isCurrent && (
                      <span className="rounded-full border border-primary/30 bg-primary/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-primary">
                        last used
                      </span>
                    )}
                  </span>
                  {description && (
                    <span className="mt-0.5 block truncate text-xs text-muted-foreground">{description}</span>
                  )}
                </span>
                <ArrowRight className="ml-2 hidden h-4 w-4 shrink-0 text-primary group-hover:inline-block" />
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
};
