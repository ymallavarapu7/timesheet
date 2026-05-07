import { describe, expect, it } from 'vitest';

import { buildNavigation } from './navigation';
import type { User, UserRole } from '@/types';

const makeUser = (overrides: Partial<User> = {}): User => ({
  id: 1,
  email: 'someone@example.com',
  username: 'someone',
  full_name: 'Some One',
  role: 'EMPLOYEE' as UserRole,
  is_active: true,
  email_verified: true,
  has_changed_password: true,
  manager_id: null,
  tenant_id: 1,
  timezone: 'UTC',
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  ...overrides,
});

const flatten = (sections: ReturnType<typeof buildNavigation>): string[] =>
  sections.flatMap((s) => s.items.map((i) => i.label));

describe('buildNavigation', () => {
  describe('admin', () => {
    const admin = makeUser({ role: 'ADMIN', can_review: true });

    it('does NOT show Approvals to an admin', () => {
      const labels = flatten(buildNavigation(admin, true));
      expect(labels).not.toContain('Approvals');
    });

    it('does NOT show Inbox to an admin even when ingestion is enabled and can_review=true', () => {
      // Defends the role-strip rule. Admin's job is admin work; review
      // and approval flow happens under the manager account.
      const labels = flatten(buildNavigation(admin, true));
      expect(labels).not.toContain('Inbox');
    });

    it('shows admin-only nav items', () => {
      const labels = flatten(buildNavigation(admin, true));
      expect(labels).toEqual(expect.arrayContaining([
        'Dashboard', 'My Time', 'Time Off', 'Calendar',
        'Users', 'Clients', 'Audit Trail', 'Settings', 'Mailboxes',
      ]));
    });
  });

  describe('manager', () => {
    const manager = makeUser({ role: 'MANAGER', can_review: true });

    it('shows Approvals to a manager', () => {
      const labels = flatten(buildNavigation(manager, true));
      expect(labels).toContain('Approvals');
    });

    it('shows Inbox to a manager when ingestion is enabled and can_review=true', () => {
      const labels = flatten(buildNavigation(manager, true));
      expect(labels).toContain('Inbox');
    });

    it('hides Inbox when ingestion is disabled', () => {
      const labels = flatten(buildNavigation(manager, false));
      expect(labels).not.toContain('Inbox');
    });

    it('hides Inbox when can_review is false', () => {
      const noReview = makeUser({ role: 'MANAGER', can_review: false });
      const labels = flatten(buildNavigation(noReview, true));
      expect(labels).not.toContain('Inbox');
    });

    it('hides admin-only nav items', () => {
      const labels = flatten(buildNavigation(manager, true));
      expect(labels).not.toContain('Clients');
      expect(labels).not.toContain('Audit Trail');
      expect(labels).not.toContain('Mailboxes');
    });
  });

  describe('manager', () => {
    it('shows Approvals for MANAGER', () => {
      const mgr = makeUser({ role: 'MANAGER' });
      expect(flatten(buildNavigation(mgr, true))).toContain('Approvals');
    });
  });

  describe('employee', () => {
    const employee = makeUser({ role: 'EMPLOYEE' });

    it('shows only the workspace items', () => {
      const labels = flatten(buildNavigation(employee, true));
      expect(labels).toEqual(['Dashboard', 'My Time', 'Time Off', 'Calendar']);
    });
  });

  describe('platform_admin', () => {
    const platform = makeUser({ role: 'PLATFORM_ADMIN', tenant_id: null });

    it('shows platform nav items, hides workspace personal-time items', () => {
      const labels = flatten(buildNavigation(platform, false));
      expect(labels).toContain('Dashboard');
      expect(labels).toContain('Tenants');
      expect(labels).toContain('Settings');
      expect(labels).not.toContain('My Time');
      expect(labels).not.toContain('Time Off');
      expect(labels).not.toContain('Approvals');
    });
  });

  it('returns no nav for a null user', () => {
    expect(buildNavigation(null, false)).toEqual([]);
  });
});
