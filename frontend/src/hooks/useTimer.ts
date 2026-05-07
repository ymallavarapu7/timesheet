import { useContext } from 'react';
import { TimerContext, TimerContextValue } from '@/contexts/TimerContext';

export function useTimer(): TimerContextValue {
  const context = useContext(TimerContext);
  if (!context) {
    throw new Error('useTimer must be used within a TimerProvider');
  }
  return context;
}
