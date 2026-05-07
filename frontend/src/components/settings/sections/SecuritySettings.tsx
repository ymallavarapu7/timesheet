import React from 'react';
import { TenantSettingsForm } from '@/components/TenantSettingsForm';
import { SectionWrapper } from '../SettingsPrimitives';

export const SecuritySettings: React.FC = () => (
  <SectionWrapper title="Security" desc="Login lockout behavior after repeated failed attempts.">
    <TenantSettingsForm filterCategories={['security']} showHeader={false} />
  </SectionWrapper>
);
