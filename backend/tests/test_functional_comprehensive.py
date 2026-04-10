"""
Functional tests covering every use case not already exercised in the existing
test suite:

  Authentication      – unauthenticated access, password change
  Projects            – admin CRUD, non-admin 403, 404
  Clients             – admin CRUD, non-admin 403, 404
  Tasks               – admin CRUD, scoped listing, invalid project 400
  Timesheets          – get-by-id, delete draft, filter by status, weekly
                        submit status, cannot-edit-submitted,
                        employee cannot edit others, CEO/SM cannot create
  Approvals           – history, batch-approve, batch-reject, employee 403
  Time Off            – get-by-id, update draft, cannot-update-submitted,
                        delete draft, manager reject, approval history,
                        employee 403 on approval endpoints
  Dashboard           – team list (manager / CEO / employee), team-daily-overview,
                        analytics with no data
  Users               – own profile (employee + manager), get-by-id access rules,
                        employee 403 on list, admin update, admin delete,
                        duplicate email rejected
  Notifications       – delete single, delete-all
"""
from datetime import date, timedelta

from fastapi.testclient import TestClient


# ─────────────────────────────────────────────────────────────────────────────
# Authentication
# ─────────────────────────────────────────────────────────────────────────────

def test_unauthenticated_access_denied(api_client: TestClient):
    """Every protected endpoint must return 401 when no token is supplied."""
    routes = [
        ("GET",  "/auth/me"),
        ("GET",  "/projects"),
        ("GET",  "/clients"),
        ("GET",  "/tasks"),
        ("GET",  "/timesheets/my"),
        ("GET",  "/approvals/pending"),
        ("GET",  "/dashboard/summary"),
        ("GET",  "/time-off/my"),
        ("GET",  "/notifications/summary"),
    ]
    for method, path in routes:
        r = api_client.request(method, path)
        # FastAPI's HTTPBearer raises 403 when the Authorization header is absent;
        # 401 is raised only when a token is present but invalid.
        assert r.status_code in (401, 403), (
            f"Expected 401/403 on {method} {path}, got {r.status_code}"
        )


def test_change_password_success_and_failure(
    api_client: TestClient, auth_headers: dict
):
    # Wrong current password is rejected
    bad = api_client.post(
        "/users/me/password",
        headers=auth_headers,
        json={"current_password": "WrongPass!", "new_password": "NewPass@99"},
    )
    assert bad.status_code == 400
    assert "incorrect" in bad.json()["detail"].lower()

    # Same password as current is rejected
    same = api_client.post(
        "/users/me/password",
        headers=auth_headers,
        json={"current_password": "password", "new_password": "password"},
    )
    assert same.status_code == 400

    # Valid change succeeds
    ok = api_client.post(
        "/users/me/password",
        headers=auth_headers,
        json={"current_password": "password", "new_password": "Changed@Pass9"},
    )
    assert ok.status_code == 200
    assert "successfully" in ok.json()["message"].lower()

    # New password works for login
    login = api_client.post(
        "/auth/login",
        json={"email": "emp@example.com", "password": "Changed@Pass9"},
    )
    assert login.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# Projects – admin CRUD + access control
# ─────────────────────────────────────────────────────────────────────────────

def test_admin_crud_projects(api_client: TestClient, admin_auth_headers: dict):
    # List projects
    list_resp = api_client.get("/projects", headers=admin_auth_headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) >= 2

    # Get by ID
    project_id = list_resp.json()[0]["id"]
    get_resp = api_client.get(f"/projects/{project_id}", headers=admin_auth_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == project_id

    # Resolve a real client_id
    clients_resp = api_client.get("/clients", headers=admin_auth_headers)
    assert clients_resp.status_code == 200
    client_id = clients_resp.json()[0]["id"]

    # Create
    create_resp = api_client.post(
        "/projects",
        headers=admin_auth_headers,
        json={"name": "Admin Test Project", "client_id": client_id, "billable_rate": "200.00"},
    )
    assert create_resp.status_code == 201
    new_id = create_resp.json()["id"]
    assert create_resp.json()["name"] == "Admin Test Project"

    # Update
    update_resp = api_client.put(
        f"/projects/{new_id}",
        headers=admin_auth_headers,
        json={"name": "Admin Test Project Updated"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["name"] == "Admin Test Project Updated"

    # Delete
    delete_resp = api_client.delete(f"/projects/{new_id}", headers=admin_auth_headers)
    assert delete_resp.status_code == 204

    # Gone
    assert api_client.get(f"/projects/{new_id}", headers=admin_auth_headers).status_code == 404


def test_non_admin_cannot_modify_projects(api_client: TestClient, auth_headers: dict):
    assert api_client.get("/projects", headers=auth_headers).status_code == 200

    assert api_client.post(
        "/projects", headers=auth_headers,
        json={"name": "Unauth", "client_id": 1, "billable_rate": "100.00"},
    ).status_code == 403

    assert api_client.put(
        "/projects/1", headers=auth_headers, json={"name": "Unauth"},
    ).status_code == 403

    assert api_client.delete("/projects/1", headers=auth_headers).status_code == 403


def test_project_not_found_returns_404(api_client: TestClient, admin_auth_headers: dict):
    assert api_client.get("/projects/99999", headers=admin_auth_headers).status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# Clients – admin CRUD + access control
# ─────────────────────────────────────────────────────────────────────────────

def test_admin_crud_clients(api_client: TestClient, admin_auth_headers: dict, auth_headers: dict):
    # Any authenticated user can list
    list_resp = api_client.get("/clients", headers=auth_headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) >= 1

    # Get by ID
    client_id = list_resp.json()[0]["id"]
    get_resp = api_client.get(f"/clients/{client_id}", headers=auth_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == client_id

    # Admin creates
    create_resp = api_client.post(
        "/clients", headers=admin_auth_headers, json={"name": "New Test Client"},
    )
    assert create_resp.status_code == 201
    new_id = create_resp.json()["id"]
    assert create_resp.json()["name"] == "New Test Client"

    # Admin updates
    update_resp = api_client.put(
        f"/clients/{new_id}", headers=admin_auth_headers, json={"name": "Updated Test Client"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["name"] == "Updated Test Client"

    # Admin deletes
    assert api_client.delete(f"/clients/{new_id}", headers=admin_auth_headers).status_code == 204
    assert api_client.get(f"/clients/{new_id}", headers=admin_auth_headers).status_code == 404


def test_non_admin_cannot_modify_clients(api_client: TestClient, auth_headers: dict):
    assert api_client.post(
        "/clients", headers=auth_headers, json={"name": "Unauth"},
    ).status_code == 403

    assert api_client.put(
        "/clients/1", headers=auth_headers, json={"name": "Unauth"},
    ).status_code == 403

    assert api_client.delete("/clients/1", headers=auth_headers).status_code == 403


def test_client_not_found_returns_404(api_client: TestClient, admin_auth_headers: dict):
    assert api_client.get("/clients/99999", headers=admin_auth_headers).status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# Tasks – admin CRUD + access control
# ─────────────────────────────────────────────────────────────────────────────

def test_admin_crud_tasks(api_client: TestClient, admin_auth_headers: dict):
    # Create a task on project 1
    create_resp = api_client.post(
        "/tasks",
        headers=admin_auth_headers,
        json={"project_id": 1, "name": "Test Task", "code": "TASK-001", "is_active": True},
    )
    assert create_resp.status_code == 201
    task_id = create_resp.json()["id"]
    assert create_resp.json()["name"] == "Test Task"

    # Get by ID
    get_resp = api_client.get(f"/tasks/{task_id}", headers=admin_auth_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == task_id

    # List – admin sees all
    list_resp = api_client.get("/tasks", headers=admin_auth_headers)
    assert list_resp.status_code == 200
    assert any(t["id"] == task_id for t in list_resp.json())

    # Update
    update_resp = api_client.put(
        f"/tasks/{task_id}", headers=admin_auth_headers,
        json={"name": "Updated Task", "is_active": True},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["name"] == "Updated Task"

    # Delete
    assert api_client.delete(f"/tasks/{task_id}", headers=admin_auth_headers).status_code == 204
    assert api_client.get(f"/tasks/{task_id}", headers=admin_auth_headers).status_code == 404


def test_non_admin_cannot_create_tasks(api_client: TestClient, auth_headers: dict):
    assert api_client.post(
        "/tasks", headers=auth_headers,
        json={"project_id": 1, "name": "Unauth Task"},
    ).status_code == 403


def test_task_on_nonexistent_project_returns_400(api_client: TestClient, admin_auth_headers: dict):
    resp = api_client.post(
        "/tasks", headers=admin_auth_headers,
        json={"project_id": 99999, "name": "Ghost Task"},
    )
    assert resp.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# Timesheets – additional cases
# ─────────────────────────────────────────────────────────────────────────────

def test_timesheet_get_by_id(api_client: TestClient, auth_headers: dict):
    my_resp = api_client.get("/timesheets/my", headers=auth_headers, params={"status": "DRAFT"})
    assert my_resp.status_code == 200
    assert len(my_resp.json()) >= 1
    entry_id = my_resp.json()[0]["id"]

    get_resp = api_client.get(f"/timesheets/{entry_id}", headers=auth_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == entry_id
    assert get_resp.json()["user"]["email"] == "emp@example.com"


def test_timesheet_delete_draft(api_client: TestClient, auth_headers: dict):
    entry_date = (date.today() - timedelta(days=2)).isoformat()
    create_resp = api_client.post(
        "/timesheets", headers=auth_headers,
        json={"project_id": 1, "entry_date": entry_date, "hours": "2.00", "description": "To delete"},
    )
    assert create_resp.status_code == 201
    entry_id = create_resp.json()["id"]

    assert api_client.delete(f"/timesheets/{entry_id}", headers=auth_headers).status_code == 204
    assert api_client.get(f"/timesheets/{entry_id}", headers=auth_headers).status_code == 404


def test_timesheet_cannot_edit_submitted_entry(api_client: TestClient, auth_headers: dict):
    submitted = api_client.get(
        "/timesheets/my", headers=auth_headers, params={"status": "SUBMITTED"}
    )
    assert submitted.status_code == 200
    assert len(submitted.json()) >= 1
    entry_id = submitted.json()[0]["id"]

    resp = api_client.put(
        f"/timesheets/{entry_id}", headers=auth_headers,
        json={"description": "Should fail"},
    )
    assert resp.status_code == 400
    assert "DRAFT" in resp.json()["detail"]


def test_timesheet_employee_cannot_edit_others_entry(
    api_client: TestClient, auth_headers: dict, manager_auth_headers: dict
):
    entry_date = (date.today() - timedelta(days=3)).isoformat()
    create_resp = api_client.post(
        "/timesheets", headers=manager_auth_headers,
        json={"project_id": 1, "entry_date": entry_date, "hours": "4.00", "description": "Manager entry"},
    )
    assert create_resp.status_code == 201
    manager_entry_id = create_resp.json()["id"]

    resp = api_client.put(
        f"/timesheets/{manager_entry_id}", headers=auth_headers,
        json={"description": "Unauthorized edit"},
    )
    assert resp.status_code == 403
    assert "own" in resp.json()["detail"].lower()


def test_timesheet_filter_by_status(api_client: TestClient, auth_headers: dict):
    draft_resp = api_client.get(
        "/timesheets/my", headers=auth_headers, params={"status": "DRAFT"}
    )
    assert draft_resp.status_code == 200
    for entry in draft_resp.json():
        assert entry["status"] == "DRAFT"

    submitted_resp = api_client.get(
        "/timesheets/my", headers=auth_headers, params={"status": "SUBMITTED"}
    )
    assert submitted_resp.status_code == 200
    for entry in submitted_resp.json():
        assert entry["status"] == "SUBMITTED"


def test_weekly_submit_status_returns_expected_shape(api_client: TestClient, auth_headers: dict):
    resp = api_client.get("/timesheets/weekly-submit-status", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "can_submit" in body
    assert "reason" in body
    assert "due_date" in body
    assert isinstance(body["can_submit"], bool)


def test_ceo_and_senior_manager_cannot_create_timesheets(
    api_client: TestClient, ceo_auth_headers: dict, senior_manager_auth_headers: dict
):
    payload = {"project_id": 1, "entry_date": date.today().isoformat(), "hours": "5.00", "description": "x"}

    assert api_client.post("/timesheets", headers=ceo_auth_headers, json=payload).status_code == 403
    assert api_client.post("/timesheets", headers=senior_manager_auth_headers, json=payload).status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
# Approvals – history, batch-approve, batch-reject, employee 403
# ─────────────────────────────────────────────────────────────────────────────

def test_approval_history_returns_approved_and_rejected(
    api_client: TestClient, manager_auth_headers: dict
):
    # Approve the one pending submitted entry first to seed the history
    pending = api_client.get("/approvals/pending", headers=manager_auth_headers).json()
    if pending:
        api_client.post(
            f"/approvals/{pending[0]['id']}/approve",
            headers=manager_auth_headers, json={},
        )

    history_resp = api_client.get("/approvals/history", headers=manager_auth_headers)
    assert history_resp.status_code == 200
    for entry in history_resp.json():
        assert entry["status"] in ("APPROVED", "REJECTED")


def test_batch_approve_submitted_week(api_client: TestClient, manager_auth_headers: dict):
    pending = api_client.get("/approvals/pending", headers=manager_auth_headers).json()
    assert len(pending) >= 1

    first = pending[0]
    emp_id = first["user"]["id"]
    entry_date = date.fromisoformat(first["entry_date"])
    week_start = entry_date - timedelta(days=entry_date.weekday())
    week_end = week_start + timedelta(days=6)

    week_ids = [
        e["id"] for e in pending
        if e["user"]["id"] == emp_id
        and week_start <= date.fromisoformat(e["entry_date"]) <= week_end
    ]

    resp = api_client.post(
        "/approvals/batch-approve",
        headers=manager_auth_headers,
        json={"entry_ids": week_ids},
    )
    assert resp.status_code == 200
    for entry in resp.json():
        assert entry["status"] == "APPROVED"


def test_batch_reject_submitted_week(api_client: TestClient, manager_auth_headers: dict):
    pending = api_client.get("/approvals/pending", headers=manager_auth_headers).json()
    assert len(pending) >= 1

    first = pending[0]
    emp_id = first["user"]["id"]
    entry_date = date.fromisoformat(first["entry_date"])
    week_start = entry_date - timedelta(days=entry_date.weekday())
    week_end = week_start + timedelta(days=6)

    week_ids = [
        e["id"] for e in pending
        if e["user"]["id"] == emp_id
        and week_start <= date.fromisoformat(e["entry_date"]) <= week_end
    ]

    resp = api_client.post(
        "/approvals/batch-reject",
        headers=manager_auth_headers,
        json={"entry_ids": week_ids, "rejection_reason": "Batch rejection – testing"},
    )
    assert resp.status_code == 200
    for entry in resp.json():
        assert entry["status"] == "REJECTED"


def test_employee_cannot_access_approval_history(api_client: TestClient, auth_headers: dict):
    assert api_client.get("/approvals/history", headers=auth_headers).status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
# Time Off – additional cases
# ─────────────────────────────────────────────────────────────────────────────

def test_time_off_get_by_id(api_client: TestClient, auth_headers: dict):
    list_resp = api_client.get("/time-off/my", headers=auth_headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) >= 1
    request_id = list_resp.json()[0]["id"]

    get_resp = api_client.get(f"/time-off/{request_id}", headers=auth_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == request_id


def test_time_off_update_draft(api_client: TestClient, auth_headers: dict):
    create_resp = api_client.post(
        "/time-off", headers=auth_headers,
        json={"request_date": "2026-06-05", "hours": "4.00", "leave_type": "HALF_DAY", "reason": "Appointment"},
    )
    assert create_resp.status_code == 201
    request_id = create_resp.json()["id"]

    update_resp = api_client.put(
        f"/time-off/{request_id}", headers=auth_headers,
        json={"reason": "Updated reason", "hours": "8.00", "leave_type": "PTO"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["reason"] == "Updated reason"
    assert update_resp.json()["leave_type"] == "PTO"


def test_time_off_cannot_update_submitted(api_client: TestClient, auth_headers: dict):
    submitted = [
        r for r in api_client.get("/time-off/my", headers=auth_headers).json()
        if r["status"] == "SUBMITTED"
    ]
    assert len(submitted) >= 1

    resp = api_client.put(
        f"/time-off/{submitted[0]['id']}", headers=auth_headers,
        json={"reason": "Should not work"},
    )
    assert resp.status_code == 400
    assert "DRAFT" in resp.json()["detail"]


def test_time_off_delete_draft(api_client: TestClient, auth_headers: dict):
    create_resp = api_client.post(
        "/time-off", headers=auth_headers,
        json={"request_date": "2026-07-10", "hours": "8.00", "leave_type": "PTO", "reason": "To delete"},
    )
    assert create_resp.status_code == 201
    request_id = create_resp.json()["id"]

    assert api_client.delete(f"/time-off/{request_id}", headers=auth_headers).status_code == 204
    assert api_client.get(f"/time-off/{request_id}", headers=auth_headers).status_code == 404


def test_time_off_manager_reject(
    api_client: TestClient, auth_headers: dict, manager_auth_headers: dict
):
    create_resp = api_client.post(
        "/time-off", headers=auth_headers,
        json={"request_date": "2026-04-20", "hours": "8.00", "leave_type": "SICK_DAY", "reason": "Sick day"},
    )
    assert create_resp.status_code == 201
    request_id = create_resp.json()["id"]

    api_client.post("/time-off/submit", headers=auth_headers, json={"request_ids": [request_id]})

    reject_resp = api_client.post(
        f"/time-off-approvals/{request_id}/reject",
        headers=manager_auth_headers,
        json={"rejection_reason": "Not approved at this time"},
    )
    assert reject_resp.status_code == 200
    assert reject_resp.json()["status"] == "REJECTED"
    assert reject_resp.json()["rejection_reason"] == "Not approved at this time"


def test_time_off_approval_history(
    api_client: TestClient, auth_headers: dict, manager_auth_headers: dict
):
    create_resp = api_client.post(
        "/time-off", headers=auth_headers,
        json={"request_date": "2026-04-15", "hours": "8.00", "leave_type": "PTO", "reason": "History test"},
    )
    assert create_resp.status_code == 201
    request_id = create_resp.json()["id"]

    api_client.post("/time-off/submit", headers=auth_headers, json={"request_ids": [request_id]})
    api_client.post(f"/time-off-approvals/{request_id}/approve", headers=manager_auth_headers, json={})

    history_resp = api_client.get("/time-off-approvals/history", headers=manager_auth_headers)
    assert history_resp.status_code == 200
    for item in history_resp.json():
        assert item["status"] in ("APPROVED", "REJECTED")


def test_employee_cannot_access_time_off_approvals(api_client: TestClient, auth_headers: dict):
    assert api_client.get("/time-off-approvals/pending", headers=auth_headers).status_code == 403
    assert api_client.get("/time-off-approvals/history", headers=auth_headers).status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard – team list, team-daily-overview, analytics edge case
# ─────────────────────────────────────────────────────────────────────────────

def test_dashboard_team_returns_direct_reports_for_manager(
    api_client: TestClient, manager_auth_headers: dict
):
    resp = api_client.get("/dashboard/team", headers=manager_auth_headers)
    assert resp.status_code == 200
    emails = {u["email"] for u in resp.json()}
    assert "emp@example.com" in emails


def test_dashboard_team_returns_employees_for_ceo(api_client: TestClient, ceo_auth_headers: dict):
    resp = api_client.get("/dashboard/team", headers=ceo_auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


def test_dashboard_team_empty_for_employee(api_client: TestClient, auth_headers: dict):
    resp = api_client.get("/dashboard/team", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_dashboard_team_daily_overview_shape_for_manager(
    api_client: TestClient, manager_auth_headers: dict
):
    resp = api_client.get("/dashboard/team-daily-overview", headers=manager_auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    for key in ("date", "team_size", "submitted_yesterday_count",
                "missing_yesterday_count", "pending_approvals_count"):
        assert key in body


def test_dashboard_team_daily_overview_employee_returns_empty_team(
    api_client: TestClient, auth_headers: dict
):
    resp = api_client.get("/dashboard/team-daily-overview", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["team_size"] == 0


def test_dashboard_analytics_future_date_returns_zero(api_client: TestClient, auth_headers: dict):
    future = (date.today() + timedelta(days=365)).isoformat()
    resp = api_client.get(
        "/dashboard/analytics", headers=auth_headers,
        params={"start_date": future, "end_date": future},
    )
    assert resp.status_code == 200
    assert float(resp.json()["total_hours"]) == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Users – profile, get-by-id access, employee 403 on list, admin CRUD
# ─────────────────────────────────────────────────────────────────────────────

def test_user_get_own_profile_employee(api_client: TestClient, auth_headers: dict):
    resp = api_client.get("/users/me/profile", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "emp@example.com"
    assert "manager_name" in body
    assert "direct_reports" in body
    assert "supervisor_chain" in body


def test_user_get_own_profile_manager_has_direct_reports(
    api_client: TestClient, manager_auth_headers: dict
):
    resp = api_client.get("/users/me/profile", headers=manager_auth_headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == "manager@example.com"
    assert len(resp.json()["direct_reports"]) >= 1


def test_user_get_by_id_self_allowed_for_employee(api_client: TestClient, auth_headers: dict):
    me = api_client.get("/auth/me", headers=auth_headers).json()
    resp = api_client.get(f"/users/{me['id']}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == me["id"]


def test_user_get_by_id_others_forbidden_for_employee(
    api_client: TestClient, auth_headers: dict, admin_auth_headers: dict
):
    all_users = api_client.get("/users", headers=admin_auth_headers).json()
    manager_id = next(u["id"] for u in all_users if u["email"] == "manager@example.com")

    # Employee cannot view another user
    assert api_client.get(f"/users/{manager_id}", headers=auth_headers).status_code == 403

    # Admin can view any user
    assert api_client.get(f"/users/{manager_id}", headers=admin_auth_headers).status_code == 200


def test_employee_cannot_list_users(api_client: TestClient, auth_headers: dict):
    assert api_client.get("/users", headers=auth_headers).status_code == 403


def test_admin_can_update_user(api_client: TestClient, admin_auth_headers: dict):
    all_users = api_client.get("/users", headers=admin_auth_headers).json()
    emp_id = next(u["id"] for u in all_users if u["email"] == "emp@example.com")

    update_resp = api_client.put(
        f"/users/{emp_id}", headers=admin_auth_headers,
        json={
            "title": "Senior Software Engineer",
            "can_review": True,
            "is_external": True,
        },
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["title"] == "Senior Software Engineer"
    assert update_resp.json()["can_review"] is True
    assert update_resp.json()["is_external"] is True


def test_admin_can_delete_user(api_client: TestClient, admin_auth_headers: dict):
    create_resp = api_client.post(
        "/users", headers=admin_auth_headers,
        json={
            "email": "throwaway@example.com",
            "username": "throwaway",
            "full_name": "Throwaway User",
            "title": "Test Engineer",
            "password": "Throwaway@1",
            "role": "EMPLOYEE",
            "is_active": True,
        },
    )
    assert create_resp.status_code == 201
    user_id = create_resp.json()["id"]

    assert api_client.delete(f"/users/{user_id}", headers=admin_auth_headers).status_code == 204
    assert api_client.get(f"/users/{user_id}", headers=admin_auth_headers).status_code == 404


def test_duplicate_user_email_rejected(api_client: TestClient, admin_auth_headers: dict):
    resp = api_client.post(
        "/users", headers=admin_auth_headers,
        json={
            "email": "emp@example.com",
            "username": "dup-emp",
            "full_name": "Duplicate Employee",
            "password": "Password1!",
            "role": "EMPLOYEE",
            "is_active": True,
        },
    )
    assert resp.status_code == 400
    assert "already exists" in resp.json()["detail"].lower()


# ─────────────────────────────────────────────────────────────────────────────
# Notifications – delete single, delete-all
# ─────────────────────────────────────────────────────────────────────────────

def test_notification_delete_single(
    api_client: TestClient, auth_headers: dict, manager_auth_headers: dict
):
    # Produce a rejection notification
    pending = api_client.get("/approvals/pending", headers=manager_auth_headers).json()
    assert len(pending) >= 1
    api_client.post(
        f"/approvals/{pending[0]['id']}/reject",
        headers=manager_auth_headers,
        json={"rejection_reason": "Delete notification test"},
    )

    summary = api_client.get("/notifications/summary", headers=auth_headers).json()
    rejected_item = next(
        (item for item in summary["items"] if item["id"] == "rejected-time-entries"), None
    )
    assert rejected_item is not None

    delete_resp = api_client.post(
        "/notifications/delete", headers=auth_headers,
        json={"notification_id": rejected_item["id"]},
    )
    assert delete_resp.status_code == 200
    assert delete_resp.json()["success"] is True

    # Dismissed notification must not appear in next summary
    after = api_client.get("/notifications/summary", headers=auth_headers).json()
    assert "rejected-time-entries" not in [item["id"] for item in after["items"]]


def test_notification_delete_all(api_client: TestClient, auth_headers: dict):
    delete_all_resp = api_client.post("/notifications/delete-all", headers=auth_headers, json={})
    assert delete_all_resp.status_code == 200
    assert delete_all_resp.json()["success"] is True

    # After delete-all no items should be visible
    after = api_client.get("/notifications/summary", headers=auth_headers).json()
    assert len(after["items"]) == 0
