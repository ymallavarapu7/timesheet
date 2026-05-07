import React from 'react';
import { TenantSettingsForm } from '@/components/TenantSettingsForm';
import { SectionWrapper } from '../SettingsPrimitives';

export const TimeEntrySettings: React.FC = () => (
  <SectionWrapper title="Time entry" desc="Configure time entry windows, hour limits, and submission policies.">
    <TenantSettingsForm filterCategories={['time_entry']} showHeader={false} />
  </SectionWrapper>
);
