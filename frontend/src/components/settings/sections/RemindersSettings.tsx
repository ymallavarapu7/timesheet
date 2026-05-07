import React from 'react';
import { TenantSettingsForm } from '@/components/TenantSettingsForm';
import { SectionWrapper } from '../SettingsPrimitives';

export const RemindersSettings: React.FC = () => (
  <SectionWrapper title="Reminders" desc="Automated deadline reminders for employees and contractors.">
    <TenantSettingsForm filterCategories={['reminders']} showHeader={false} />
  </SectionWrapper>
);
