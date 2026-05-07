import React from 'react';
import { TimeEntrySettings } from './sections/TimeEntrySettings';
import { TimeOffPolicySettings } from './sections/TimeOffPolicySettings';
import { SecuritySettings } from './sections/SecuritySettings';
import { RemindersSettings } from './sections/RemindersSettings';
import { NotificationsSettings } from './sections/NotificationsSettings';
import { EmailSmtpSettings } from './sections/EmailSmtpSettings';

const sectionMap: Record<string, React.FC> = {
  'time-entry':      TimeEntrySettings,
  'timeoff-policy':  TimeOffPolicySettings,
  'security':        SecuritySettings,
  'reminders':       RemindersSettings,
  'notifications':   NotificationsSettings,
  'email-smtp':      EmailSmtpSettings,
};

interface Props {
  activeSection: string;
}

export const SettingsContent: React.FC<Props> = ({ activeSection }) => {
  const ActiveComponent = sectionMap[activeSection] ?? TimeEntrySettings;
  return (
    <div className="flex-1 overflow-y-auto p-6 lg:p-7">
      <ActiveComponent />
    </div>
  );
};
