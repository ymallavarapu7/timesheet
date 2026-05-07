import React from 'react';
import { TenantSettingsForm } from '@/components/TenantSettingsForm';
import { SectionWrapper } from '../SettingsPrimitives';

export const TimeOffPolicySettings: React.FC = () => (
  <SectionWrapper title="Time-off policy" desc="Rules for when and how time-off requests can be created.">
    <TenantSettingsForm filterCategories={['time_off']} showHeader={false} />
  </SectionWrapper>
);
