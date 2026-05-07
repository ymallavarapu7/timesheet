import React from 'react';
import { TenantSettingsForm } from '@/components/TenantSettingsForm';
import { SectionWrapper } from '../SettingsPrimitives';

export const EmailSmtpSettings: React.FC = () => (
  <SectionWrapper title="Email / SMTP" desc="Outbound email delivery and scheduled email fetch configuration.">
    <TenantSettingsForm filterCategories={['email']} showHeader={false} />
  </SectionWrapper>
);
