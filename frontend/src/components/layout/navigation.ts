import {
  Briefcase,
  Building2,
  ClipboardList,
  CalendarDays,
  ClipboardCheck,
  Clock3,
  FolderCog,
  Home,
  Inbox,
  Mail,
  Settings,
  ShieldCheck,
  UserCircle2,
  UsersRound,
} from 'lucide-react';

import type { LucideIcon } from 'lucide-react';
import type { User } from '@/types';

export type NavItem = {
  label: string;
  to: string;
  icon: LucideIcon;
  match?: string[];
  visible: boolean;
};

export type NavSection = {
  title: string;
  items: NavItem[];
};

const isManager = (user: User | null) => Boolean(user && ['MANAGER', 'SENIOR_MANAGER', 'CEO', 'ADMIN'].includes(user.role));
const isAdmin = (user: User | null) => user?.role === 'ADMIN';
const isPlatformAdmin = (user: User | null) => user?.role === 'PLATFORM_ADMIN';
const canReview = (user: User | null) => Boolean(user && (user.role === 'ADMIN' || user.can_review));

export const buildNavigation = (user: User | null, ingestionEnabled: boolean): NavSection[] => {
  const sections: NavSection[] = [
    {
      title: 'Workspace',
      items: [
        { label: 'Dashboard', to: '/dashboard', icon: Home, visible: Boolean(user) },
        { label: 'My Time', to: '/my-time', icon: Clock3, visible: Boolean(user && user.role !== 'PLATFORM_ADMIN') },
        { label: 'Time Off', to: '/time-off', icon: ClipboardCheck, visible: Boolean(user && user.role !== 'PLATFORM_ADMIN') },
        { label: 'Calendar', to: '/calendar', icon: CalendarDays, visible: Boolean(user) },
        { label: 'Profile', to: '/profile', icon: UserCircle2, visible: Boolean(user) },
      ],
    },
    {
      title: 'Operations',
      items: [
        { label: 'Approvals', to: '/approvals', icon: ShieldCheck, visible: isManager(user) },
        { label: 'Users', to: '/user-management', icon: UsersRound, visible: isAdmin(user) || isManager(user) },
        { label: 'Clients', to: '/client-management', icon: Briefcase, visible: isAdmin(user) },
        { label: 'Audit Trail', to: '/audit-trail', icon: ClipboardList, visible: isAdmin(user) },
        { label: 'Settings', to: '/settings', icon: Settings, visible: isAdmin(user) },
      ],
    },
    {
      title: 'Emails',
      items: [
        { label: 'Mailboxes', to: '/mailboxes', icon: Mail, visible: ingestionEnabled && isAdmin(user) },
        { label: 'Mappings', to: '/mappings', icon: FolderCog, visible: ingestionEnabled && isAdmin(user) },
        { label: 'Inbox', to: '/ingestion/inbox', icon: Inbox, visible: ingestionEnabled && canReview(user), match: ['/ingestion/inbox', '/ingestion/review'] },
      ],
    },
    {
      title: 'Platform',
      items: [
        { label: 'Tenants', to: '/platform/tenants', icon: Building2, visible: isPlatformAdmin(user) },
        { label: 'Settings', to: '/platform/settings', icon: Settings, visible: isPlatformAdmin(user) },
      ],
    },
  ];

  return sections
    .map((section) => ({ ...section, items: section.items.filter((item) => item.visible) }))
    .filter((section) => section.items.length > 0);
};
