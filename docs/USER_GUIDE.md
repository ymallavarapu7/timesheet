# TimesheetIQ — User Guide

This guide covers every role and workflow in the platform.

---

## Table of Contents

1. [Roles & Permissions](#1-roles--permissions)
2. [Logging In](#2-logging-in)
3. [Dashboard](#3-dashboard)
4. [Logging Time (Employees)](#4-logging-time-employees)
5. [Time Off Requests](#5-time-off-requests)
6. [Approvals (Managers)](#6-approvals-managers)
7. [Ingestion Inbox (Reviewers)](#7-ingestion-inbox-reviewers)
8. [User Management (Admins)](#8-user-management-admins)
9. [Client & Project Management (Admins)](#9-client--project-management-admins)
10. [Mailbox Configuration (Admins)](#10-mailbox-configuration-admins)
11. [Sender Mappings (Admins)](#11-sender-mappings-admins)
12. [Platform Administration](#12-platform-administration)
13. [Notifications](#13-notifications)
14. [Profile & Password](#14-profile--password)
15. [Demo Credentials](#15-demo-credentials)

---

## 1. Roles & Permissions

| Role | Who They Are | What They Can Do |
|---|---|---|
| **EMPLOYEE** | Staff & contractors | Log time, request time off, view own entries |
| **MANAGER** | Team leads | All employee actions + approve/reject direct reports |
| **SENIOR_MANAGER** | Department heads | All manager actions + approve/reject managers and their reports |
| **CEO** | Executive | Read-only all entries in the tenant; can approve anyone |
| **ADMIN** | Tenant administrator | Full user, client, project, mailbox, and mapping management |
| **PLATFORM_ADMIN** | Platform-level superuser | Cross-tenant access; manages tenants and service tokens |

**Reviewer** is not a role — it is a flag (`can_review`) set on any user by an ADMIN. Reviewers can access the Ingestion Inbox to approve emailed timesheets.

### What Each Role Sees in the Navigation

| Page | EMP | MGR | SR_MGR | CEO | ADMIN | PLATFORM_ADMIN |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Dashboard | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| My Time | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| Time Off | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| Calendar | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| Approvals | — | ✓ | ✓ | ✓ | — | — |
| User Management | — | ✓* | ✓* | ✓* | ✓ | — |
| Client Management | — | — | — | — | ✓ | — |
| Mailboxes | — | — | — | — | ✓ | — |
| Mappings | — | — | — | — | ✓ | — |
| Ingestion Inbox | — | — | — | — | ✓ | — |
| Platform / Tenants | — | — | — | — | — | ✓ |

*Managers can view their team in User Management but cannot create/delete users.

---

## 2. Logging In

1. Go to the frontend URL (default: http://localhost:5174 in dev, http://localhost in Docker)
2. Enter your email and password
3. If this is your first login, you will be prompted to change your password before proceeding

**Password requirements:** minimum 8 characters including uppercase, lowercase, number, and special character.

**Account lockout:** 5 failed attempts locks the account for 15 minutes. An ADMIN can unlock it early from User Management.

---

## 3. Dashboard

The dashboard shows a snapshot of your week and your team.

### Summary Cards (top row)

- **Hours Logged** — Total hours across time entries and time off for the current period
- **Approved** — Hours that have been approved by a manager
- **Pending** — Hours submitted but awaiting approval
- **Pending Approvals** — Count of entries waiting for your approval (managers)
- **Team Members** — Size of your reporting team

### Team Daily Overview (managers)

Shows yesterday's activity across the team:
- **Submitted** — Who submitted time entries yesterday
- **Draft** — Who has drafts but hasn't submitted
- **Missing** — Who has no entries at all

The submission deadline time is shown (default 10am the next working day). The panel highlights whether you are still within the deadline window.

### Analytics

Select a date range to see:
- **Daily breakdown** — Stacked bar chart of hours per day (billable vs. non-billable, segmented by project)
- **Project breakdown** — Pie/percentage breakdown by project
- **Top activities** — Most logged descriptions for the period

Managers can filter analytics by team member. The data is automatically scoped to your reporting tree.

### Recent Activity (Admins)

A feed of administrative events (user created, client updated, approvals, ingestion actions) with severity indicators. Click any item to navigate to the relevant area.

---

## 4. Logging Time (Employees)

### Creating a Time Entry

1. Navigate to **My Time**
2. Click **New Entry** or the + button
3. Fill in:
   - **Date** — cannot be in the future; max 8 weeks in the past
   - **Project** — only projects you have been granted access to appear
   - **Task** (optional) — must belong to the selected project
   - **Hours** — max 24h per entry
   - **Description** — what you worked on
   - **Billable** — toggle if the work is non-billable
4. Save — entry is created in **DRAFT** status

**Daily limits:** The total hours across all your non-rejected entries on a given day cannot exceed 24h. Weekly total (Mon–Sun) cannot exceed 80h.

### Editing and Deleting

- **DRAFT** entries can be edited or deleted freely
- **REJECTED** entries can be edited (re-enter updated values + provide an edit reason)
- **SUBMITTED** or **APPROVED** entries cannot be modified

When editing, you must provide:
- **Edit Reason** — brief explanation (max 2000 chars)
- **History Summary** — description of what changed (max 2000 chars)

This creates an audit trail viewable on the entry detail.

### Submitting for Approval

Submission is **weekly** — you submit all your DRAFT entries for a given week together.

1. Make sure all entries for the week are in DRAFT
2. Click **Submit Week**
3. The system checks:
   - At least 1.0 hours logged for the week
   - Submission is on or after Friday of that week
4. All selected DRAFT entries move to **SUBMITTED** status

**Weekly Submit Status** is shown as a banner on My Time — it tells you whether you can submit, and if not, why (e.g., too early in the week, no entries).

### Time Entry Status Flow

```
DRAFT
  └─(submit)─→ SUBMITTED
                  ├─(approve)─→ APPROVED
                  └─(reject)──→ REJECTED
                                   └─(edit)──→ DRAFT → SUBMITTED → ...
```

### Filters and Search

Use the filter bar to search by:
- Date range
- Status (DRAFT / SUBMITTED / APPROVED / REJECTED)
- Free-text search (description or project name)
- Sort by date, hours, or status

---

## 5. Time Off Requests

Time off works identically to time entries but with leave types instead of projects.

### Leave Types

| Type | Description |
|---|---|
| PTO | Paid time off / vacation |
| SICK_DAY | Sick leave |
| HALF_DAY | Half-day absence |
| HOURLY_PERMISSION | Partial day leave (enter hours) |
| OTHER_LEAVE | Other approved absence |

### Creating a Request

1. Navigate to **Time Off**
2. Click **New Request**
3. Select: date, hours, leave type, and a reason
4. Save as DRAFT, then submit when ready

Only one request per date is allowed. Submitted requests follow the same DRAFT → SUBMITTED → APPROVED/REJECTED flow as time entries.

---

## 6. Approvals (Managers)

### Who Can Approve What

- **MANAGER** — can approve their direct reports only
- **SENIOR_MANAGER** — can approve managers and all their reports
- **CEO** — can approve anyone in the tenant

### Pending Approvals

1. Navigate to **Approvals → Pending**
2. Entries are grouped by employee and week
3. Review the hours, dates, descriptions, and projects
4. Options per group:
   - **Approve All** — approves every entry in that employee's week in one click
   - **Reject All** — rejects the whole week (requires a rejection reason)
   - Or act on individual entries with the row-level approve/reject buttons

### Approval History

- Shows approved and rejected entries from the past 7 days by default
- Toggle **Show older** to see beyond 7 days
- **History Grouped** view shows per-employee, per-week summaries with total hours and status breakdown

### After Approval

Approved entries trigger a QuickBooks sync (currently a stub — no external call made in the current version). An activity log entry is created for audit purposes.

### Rejecting

A rejection reason is required (max 1000 chars). The employee will see the reason on their My Time page and can edit the entry and resubmit.

### Reverting a Rejection

If you rejected an entry in error, use **Revert Rejection** to move it back to SUBMITTED status, allowing re-approval without requiring the employee to resubmit.

### Time Off Approvals

Time off approvals work the same way. Navigate to **Approvals → Time Off Pending** to see submitted requests.

---

## 7. Ingestion Inbox (Reviewers)

The Ingestion Inbox is where emailed timesheets land after AI processing. It is visible to users with the **Reviewer** flag (`can_review`) or ADMIN role, when ingestion is enabled for the tenant.

### Inbox Overview (`/ingestion/inbox`)

The inbox lists all ingested timesheets with:
- Sender email and subject
- Received date
- Extracted employee name and client
- Period and total hours
- Status badge
- Anomaly indicators (warning/info icons)
- Whether time entries have been created

**Status filters:**
| Status | Meaning |
|---|---|
| Pending | Ready for review |
| Under Review | Someone has opened the detail view |
| Approved | Time entries have been created |
| Rejected | Rejected by reviewer |
| On Hold | Parked for later review |

### Triggering Email Fetch

Click **Fetch Emails** to run a background job that polls all configured mailboxes. A spinner shows progress. The job ID is polled every few seconds and results displayed when complete (total fetched, new, skipped, errors).

### Skipped Emails

Click **View Skipped** to see emails that did not produce a timesheet — typically because:
- The email was not classified as a timesheet (`not_timesheet_email`)
- No attachment was found (`no_attachments`)
- Attachment extraction failed
- No structured timesheet data could be extracted

You can **Reprocess Skipped** to re-run them through the pipeline (useful after configuration changes or model updates).

### Review Panel (`/ingestion/review/:id`)

Opening a timesheet from the inbox takes you to the Review Panel.

**Left pane — Email & Attachment**
- Email metadata (sender, subject, received date)
- Original email body (rendered HTML)
- Attachments — click to download/view the original file

**Center pane — Line Items**
- Editable table of extracted work entries:
  - Work date
  - Hours
  - Description
  - Project code / Project assignment
- Add new line items with the **+ Add Row** button
- Delete or reject individual line items
- Changes are tracked with `is_corrected` flag and `original_value` preserved

**Right pane — LLM Insights**
- **Match Suggestions** — LLM-suggested employee, client, and project matches with confidence scores
- **Anomalies** — detected issues (duplicate dates, weekend work, hours mismatch, missing descriptions), each with severity (error/warning/info)
- **LLM Summary** — natural language summary of the extracted timesheet

**Actions**
- **Approve** — Creates TimeEntry records for all non-rejected line items. Employee, project, and client must be resolved. Entries are created with APPROVED status.
- **Reject** — Marks timesheet as rejected. Requires a reason. Can be reverted later.
- **Hold** — Parks the timesheet for later review without taking action.
- **Draft Comment** — Uses LLM to generate an audit comment based on the timesheet content.

**Audit Log**
- Full timeline of all actions: who did what, when, previous and new values.
- System actions (pipeline processing) and user actions are both logged.

**Internal Notes**
- Free-text field for reviewer notes that are not sent externally.

### Reapply Mappings

If sender mappings have been added or updated after emails were ingested, click **Reapply Mappings** from the Inbox to retroactively apply them to existing pending timesheets.

---

## 8. User Management (Admins)

Navigate to **User Management** to manage the users in your tenant.

### Creating a User

1. Click **New User**
2. Fill in:
   - **Email** and **Full Name** (required)
   - **Role** — see role definitions above
   - **Department** and **Title** (recommended for managers)
   - **Manager** — who this user reports to (must be compatible role)
   - **Projects** — which projects this user can log time against
   - **Can Review** — toggle to grant Ingestion Inbox access
   - **Is External** — flag for contractor accounts
3. A temporary password is auto-generated. The user will be forced to change it on first login.

### Editing a User

Click the edit icon on any user row. You can update any field. Changing a user's role may automatically adjust their manager assignments (incompatible managers are removed).

### Manager Assignment Rules

| User Role | Can Report To |
|---|---|
| EMPLOYEE | MANAGER, SENIOR_MANAGER, CEO, ADMIN |
| MANAGER | SENIOR_MANAGER, CEO |
| SENIOR_MANAGER | CEO |
| ADMIN | MANAGER, SENIOR_MANAGER |
| CEO, PLATFORM_ADMIN | No manager |

### Project Access

Project access is explicit — employees only see projects they have been granted. Grant or revoke access from the user's edit form by selecting/deselecting projects.

### Unlocking a User

If a user has been locked out (too many failed logins or timesheet lock), click the **Unlock** action on their row.

### Tenant Settings

From **User Management**, ADMIN users can access **Tenant Settings** to configure:
- Submission reminder enabled/disabled
- Reminder deadline day and time
- Whether to auto-lock accounts after the submission deadline

---

## 9. Client & Project Management (Admins)

Navigate to **Client Management** to manage the client → project → task hierarchy.

### Clients

- Create clients with a name (unique within tenant)
- Optional: QuickBooks Customer ID for billing integration

### Projects

Each project belongs to a client. Fields:
- **Name** — project display name
- **Code** — short code (e.g., "PROJ-001") used in ingestion matching
- **Billable Rate** — hourly rate for billing
- **Budget** — optional budget amount and currency
- **Dates** — optional start and end dates
- **Is Active** — inactive projects don't appear in time entry dropdowns

### Tasks

Each task belongs to a project. Tasks provide optional granularity for time tracking:
- **Name** and **Code**
- **Is Active** — inactive tasks are hidden from entry forms

When a task is selected on a time entry, it is validated to belong to the selected project.

---

## 10. Mailbox Configuration (Admins)

Navigate to **Mailboxes** to configure email sources for timesheet ingestion.

> Mailboxes only appear when ingestion is enabled for your tenant (set by Platform Admin).

### Supported Protocols

| Protocol | Use Case |
|---|---|
| IMAP | Standard email (Gmail, Office 365, custom SMTP) |
| POP3 | Legacy email servers |
| Graph | Microsoft 365 via Graph API (recommended for Outlook) |

### Authentication Types

**Basic Auth** — username + password. Password is encrypted at rest (AES-256-GCM).

**OAuth2** — click **Connect with Google** or **Connect with Microsoft**. A popup opens the OAuth consent screen. After authorizing, the mailbox is created automatically with tokens stored encrypted.

### Creating a Mailbox

1. Click **Add Mailbox**
2. Choose protocol and auth type
3. For basic auth: enter host, port, use SSL, username, password
4. For OAuth2: click the provider button and complete the OAuth flow
5. Optionally link to a **Client** — all emails from this mailbox will be associated with that client
6. Click **Test Connection** to verify before saving

### Resetting the Cursor

Each mailbox tracks `last_fetched_at` — only emails received after this timestamp are fetched. Click **Reset Cursor** to re-fetch all emails from the beginning (useful for reprocessing historical data).

---

## 11. Sender Mappings (Admins)

Sender mappings automatically assign a **client** and optionally an **employee** based on who sent the email. This speeds up review by pre-filling fields when a known sender emails a timesheet.

### Match Types

| Type | Example | Behavior |
|---|---|---|
| Email | `john@contractor.com` | Matches only this exact address |
| Domain | `contractor.com` | Matches any email from this domain |

### Creating a Mapping

1. Navigate to **Mappings**
2. Click **Add Mapping**
3. Choose match type and enter the value (normalized to lowercase)
4. Select the **Client** this sender is associated with
5. Optionally select the **Employee** user to auto-assign as the timesheet owner

### Reapply Mappings

After creating new mappings, click **Reapply Mappings** to apply them to already-ingested timesheets that are still in `pending` status.

---

## 12. Platform Administration

Navigate to **Platform → Tenants** (PLATFORM_ADMIN only).

### Managing Tenants

- **Create Tenant** — name + slug (lowercase, hyphens allowed, e.g. `acme-corp`)
- **Edit Tenant** — update name, slug, or status (active/inactive/suspended)
- **Enable Ingestion** — toggle `ingestion_enabled` to give the tenant access to mailboxes and the ingestion inbox

Suspended tenants cannot log in. Inactive tenants are disabled but data is preserved.

### Service Tokens

Service tokens allow an external system to authenticate with the Sync API (`/sync/...`) on behalf of a tenant.

1. Click **Generate Token** on a tenant row
2. The plaintext token is shown **once** — copy it immediately
3. The token is stored as a bcrypt hash; the plaintext is never shown again
4. Revoke tokens from the token list when no longer needed

### System User Provisioning

Each tenant that uses the Sync API needs a system user (`system_ingestion_{tenant_id}@system.internal`) as the "approver" for pushed timesheets. Click **Provision System User** to create it idempotently.

---

## 13. Notifications

The bell icon in the top bar shows unread notifications. Click it to open the notification panel.

### Notification Types

| Type | Who Sees It | Trigger |
|---|---|---|
| Rejected Entry | EMPLOYEE | One of your entries was rejected |
| Pending Approval | MANAGER | You have entries awaiting approval |
| Missing Time | EMPLOYEE | You have no entries for yesterday |
| Deadline Approaching | EMPLOYEE | Submission deadline is approaching |
| Timesheet Lock | EMPLOYEE | Your account has been locked |

### Actions

- Click a notification to navigate to the relevant page
- Click the X to dismiss a notification
- **Mark All Read** — clears the unread count
- **Dismiss All** — removes all notifications

---

## 14. Profile & Password

Navigate to **Profile** to manage your personal details.

### Editable Fields

- Full Name
- Job Title
- Department

Role and email can only be changed by an ADMIN.

### Supervisor Chain

The Profile page shows your manager hierarchy (who you report to, up the chain) and your direct reports (who reports to you).

### Changing Your Password

1. Click **Change Password** on the Profile page
2. Enter your current password and a new password
3. New password must meet: 8+ chars, uppercase, lowercase, number, special character

If you have forgotten your password, an ADMIN must reset it from User Management.

---

## 15. Demo Credentials

All accounts use password: `password`

| Role | Email | Name |
|---|---|---|
| PLATFORM_ADMIN | platform@example.com | Platform Admin |
| ADMIN | admin@example.com | Bharat Mallavarapu |
| CEO | ceo@example.com | Casey CEO |
| SENIOR_MANAGER | alexander@example.com | Alexander Chen (Engineering) |
| SENIOR_MANAGER | margaret@example.com | Margaret Ross (Operations) |
| MANAGER | manager1@example.com | John Doe |
| MANAGER | manager2@example.com | Sarah Ops |
| MANAGER | manager3@example.com | Nina Infra |
| EMPLOYEE | emp1-1@example.com | Employee 1 |
| EMPLOYEE | emp1-2@example.com | Employee 2 |
| EMPLOYEE | emp1-3@example.com | Employee 3 |
| EMPLOYEE | emp3-1@example.com | Employee 4 |
| EMPLOYEE | emp3-2@example.com | Employee 5 |
| EMPLOYEE | emp4-1@example.com | Employee 6 |

All users belong to **Default Tenant** (slug: `default`).

The system account `system_ingestion_1@system.internal` is used internally for ingestion-pushed time entries and should not be used for manual login.
