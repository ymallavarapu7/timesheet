import React, { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { AlertCircle, CheckCircle2, Lock, Eye, EyeOff } from 'lucide-react';
import axios from 'axios';

import { authAPI, usersAPI } from '@/api/endpoints';
import { Card, CardContent } from '@/components';

type Stage = 'verifying' | 'set-password' | 'success' | 'error';

const getApiError = (err: unknown): string => {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail;
    if (typeof detail === 'string') return detail;
  }
  if (err instanceof Error) return err.message;
  return 'Something went wrong';
};

export const VerifyAccountPage: React.FC = () => {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const token = searchParams.get('token') ?? '';

  const [stage, setStage] = useState<Stage>('verifying');
  const [errorMessage, setErrorMessage] = useState('');
  const [verifiedEmail, setVerifiedEmail] = useState('');

  // Set-password form state
  const [tempPassword, setTempPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showTemp, setShowTemp] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState('');

  // Step 1: verify the token as soon as the page loads
  useEffect(() => {
    if (!token) {
      setErrorMessage('No verification token found in the URL. Please use the link from your email.');
      setStage('error');
      return;
    }

    authAPI.verifyEmail(token)
      .then((res) => {
        setVerifiedEmail(res.data.email);
        setStage('set-password');
      })
      .catch((err) => {
        setErrorMessage(getApiError(err));
        setStage('error');
      });
  }, [token]);

  // Step 2: after email is verified, user sets a new password
  const handleSetPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError('');

    if (!tempPassword || !newPassword || !confirmPassword) {
      setFormError('All fields are required');
      return;
    }
    if (newPassword !== confirmPassword) {
      setFormError('Passwords do not match');
      return;
    }
    if (newPassword.length < 10) {
      setFormError('New password must be at least 10 characters');
      return;
    }
    if (newPassword === tempPassword) {
      setFormError('New password must be different from your temporary password');
      return;
    }

    setIsSubmitting(true);
    try {
      await usersAPI.changePasswordAfterVerification(tempPassword, newPassword, verifiedEmail);
      setStage('success');
      setTimeout(() => navigate('/'), 2500);
    } catch (err) {
      setFormError(getApiError(err));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-background flex items-center justify-center px-4">
      <Card className="w-full max-w-[440px] shadow-none">
        <CardContent className="p-8">
          {/* Header */}
          <div className="flex items-center gap-3 mb-6">
            <svg width="32" height="32" viewBox="0 0 40 40" fill="none" aria-hidden="true">
              <path d="M10 6h20l10 14-10 14H10L0 20 10 6z" fill="#2563EB" fillOpacity="0.95" />
            </svg>
            <h1 className="text-xl font-bold text-foreground">Acufy AI</h1>
          </div>

          {stage === 'verifying' && (
            <div className="space-y-3">
              <h2 className="text-xl font-semibold text-foreground">Verifying your account…</h2>
              <p className="text-sm text-muted-foreground">Please wait a moment.</p>
              <div className="h-1 w-full bg-muted rounded overflow-hidden">
                <div className="h-full w-1/2 bg-primary rounded animate-pulse" />
              </div>
            </div>
          )}

          {stage === 'error' && (
            <div className="space-y-4">
              <h2 className="text-xl font-semibold text-foreground">Verification failed</h2>
              <div className="flex items-start gap-2 p-3 bg-red-50 border border-red-200 rounded-lg">
                <AlertCircle className="w-5 h-5 text-red-600 shrink-0 mt-0.5" />
                <p className="text-sm text-red-700">{errorMessage}</p>
              </div>
              <p className="text-sm text-muted-foreground">
                The link may have expired. Contact your admin to resend a verification email.
              </p>
            </div>
          )}

          {stage === 'set-password' && (
            <div className="space-y-5">
              <div>
                <h2 className="text-xl font-semibold text-foreground">Set your password</h2>
                <p className="text-sm text-muted-foreground mt-1">
                  Your email has been verified. Enter the temporary password from your email and choose a new one.
                </p>
              </div>

              <form onSubmit={handleSetPassword} className="space-y-4">
                {/* Temporary password */}
                <div>
                  <label className="block text-sm font-medium text-foreground mb-1">
                    Temporary password
                  </label>
                  <div className="relative">
                    <Lock className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <input
                      type={showTemp ? 'text' : 'password'}
                      value={tempPassword}
                      onChange={(e) => setTempPassword(e.target.value)}
                      className="field-input pl-9 pr-9"
                      placeholder="Temporary password from email"
                      autoComplete="current-password"
                    />
                    <button
                      type="button"
                      onClick={() => setShowTemp((v) => !v)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                      tabIndex={-1}
                    >
                      {showTemp ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>
                </div>

                {/* New password */}
                <div>
                  <label className="block text-sm font-medium text-foreground mb-1">
                    New password
                  </label>
                  <div className="relative">
                    <Lock className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <input
                      type={showNew ? 'text' : 'password'}
                      value={newPassword}
                      onChange={(e) => setNewPassword(e.target.value)}
                      className="field-input pl-9 pr-9"
                      placeholder="Choose a strong password"
                      autoComplete="new-password"
                    />
                    <button
                      type="button"
                      onClick={() => setShowNew((v) => !v)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                      tabIndex={-1}
                    >
                      {showNew ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>
                  <p className="text-xs text-muted-foreground mt-1">
                    At least 10 characters with uppercase, lowercase, number, and special character.
                  </p>
                </div>

                {/* Confirm password */}
                <div>
                  <label className="block text-sm font-medium text-foreground mb-1">
                    Confirm new password
                  </label>
                  <div className="relative">
                    <Lock className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <input
                      type={showConfirm ? 'text' : 'password'}
                      value={confirmPassword}
                      onChange={(e) => setConfirmPassword(e.target.value)}
                      className="field-input pl-9 pr-9"
                      placeholder="Repeat your new password"
                      autoComplete="new-password"
                    />
                    <button
                      type="button"
                      onClick={() => setShowConfirm((v) => !v)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                      tabIndex={-1}
                    >
                      {showConfirm ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>
                </div>

                {formError && (
                  <div className="flex items-start gap-2 p-3 bg-red-50 border border-red-200 rounded-lg">
                    <AlertCircle className="w-5 h-5 text-red-600 shrink-0 mt-0.5" />
                    <p className="text-sm text-red-700">{formError}</p>
                  </div>
                )}

                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="action-button w-full mt-2"
                >
                  {isSubmitting ? 'Setting password…' : 'Set password & sign in'}
                </button>
              </form>
            </div>
          )}

          {stage === 'success' && (
            <div className="space-y-4">
              <div className="flex items-start gap-3 p-4 bg-green-50 border border-green-200 rounded-lg">
                <CheckCircle2 className="w-6 h-6 text-green-600 shrink-0 mt-0.5" />
                <div>
                  <p className="font-semibold text-green-800">Password set successfully!</p>
                  <p className="text-sm text-green-700 mt-1">Redirecting you to sign in…</p>
                </div>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
};
