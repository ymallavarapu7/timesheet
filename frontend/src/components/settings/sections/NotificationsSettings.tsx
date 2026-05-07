import React from 'react';
import { TenantSettingsForm } from '@/components/TenantSettingsForm';
import { SectionWrapper } from '../SettingsPrimitives';

export const NotificationsSettings: React.FC = () => (
  <SectionWrapper title="Notifications" desc="Configure notification retention, approval history, and alert timing.">
    <TenantSettingsForm filterCategories={['notifications']} showHeader={false} />
  </SectionWrapper>
);
