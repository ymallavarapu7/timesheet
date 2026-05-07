"""Comprehensive cross-role validation tests."""
from fastapi.testclient import TestClient
from datetime import date, timedelta


def test_viewer_cannot_access_approvals(api_client: TestClient, ceo_auth_headers: dict):
    """VIEWER role is read-only: approvals endpoint returns 403."""
    pending_response = api_client.get(
        '/approvals/pending', headers=ceo_auth_headers)
    assert pending_response.status_code == 403

    dashboard_response = api_client.get(
        '/dashboard/summary',
        headers=ceo_auth_headers,
    )
    assert dashboard_response.status_code == 200


def test_manager_can_approve_direct_reports(
    api_client: TestClient,
    senior_manager_auth_headers: dict,
):
    """Manager (formerly senior_manager fixture) can access approval queue."""
    pending_response = api_client.get(
        '/approvals/pending',
        headers=senior_manager_auth_headers,
    )
    assert pending_response.status_code == 200
    pending = pending_response.json()

    if len(pending) > 0:
        first_pending = pending[0]
        approve_response = api_client.post(
            f"/approvals/{first_pending['id']}/approve",
            headers=senior_manager_auth_headers,
            json={},
        )
        assert approve_response.status_code == 200
        assert approve_response.json()['status'] == 'APPROVED'


def test_manager_cannot_self_assign_as_own_manager(api_client: TestClient, admin_auth_headers: dict):
    """Manager should be prevented from assigning themselves as their own manager."""
    users_response = api_client.get('/users', headers=admin_auth_headers)
    assert users_response.status_code == 200
    users = users_response.json()

    manager_id = next(user['id']
                      for user in users if user['email'] == 'manager@example.com')

    self_assign = api_client.put(
        f'/users/{manager_id}',
        headers=admin_auth_headers,
        json={'manager_id': manager_id,
              'title': 'Test Manager', 'department': 'Sales'},
    )
    assert self_assign.status_code == 400
    assert 'cannot be their own manager' in self_assign.json()['detail']


def test_unassigned_employee_not_in_manager_queue(
    api_client: TestClient,
    manager_auth_headers: dict,
    seeded_data: dict,
):
    """Unassigned employee (no manager) should not appear in manager's approval queue."""
    unassigned_id = seeded_data['unassigned_employee'].id

    pending_response = api_client.get(
        '/approvals/pending',
        headers=manager_auth_headers,
    )
    assert pending_response.status_code == 200
    pending = pending_response.json()

    pending_ids = [entry['user']['id'] for entry in pending]
    assert unassigned_id not in pending_ids


def test_approval_chain_audit_through_hierarchy(
    api_client: TestClient,
    manager_auth_headers: dict,
    senior_manager_auth_headers: dict,
):
    """Manager and Senior Manager can access their approval queues and histories."""
    pending_response = api_client.get(
        '/approvals/pending',
        headers=manager_auth_headers,
    )
    assert pending_response.status_code == 200

    history_response = api_client.get(
        '/approvals/history',
        headers=senior_manager_auth_headers,
    )
    assert history_response.status_code == 200


def test_project_access_restriction_enforced(
    api_client: TestClient,
    auth_headers: dict,
    seeded_data: dict,
):
    """Employee restricted to project 1 cannot create entry on unassigned project."""
    project_2 = seeded_data['second_project'].id

    denied_entry = api_client.post(
        '/timesheets',
        headers=auth_headers,
        json={
            'project_id': project_2,
            'entry_date': date.today().isoformat(),
            'hours': '6.50',
            'description': 'Unauthorized project',
        },
    )
    assert denied_entry.status_code in [400, 403]


def test_inactive_employee_excluded_from_team_views(
    api_client: TestClient,
    manager_auth_headers: dict,
    seeded_data: dict,
):
    """Inactive employee should not appear in manager's team summary."""
    team_response = api_client.get(
        '/dashboard/team',
        headers=manager_auth_headers,
    )
    assert team_response.status_code == 200
    team = team_response.json()

    active_ids = {user['id'] for user in team}
    assert seeded_data['inactive_employee'].id not in active_ids

    summary_response = api_client.get(
        '/dashboard/summary',
        headers=manager_auth_headers,
    )
    assert summary_response.status_code == 200
    summary = summary_response.json()

    assert summary['team_members'] == 1


def test_manager_analytics_for_non_report_returns_zero(
    api_client: TestClient,
    manager_auth_headers: dict,
    seeded_data: dict,
):
    """Manager querying analytics for non-report user should get zero hours (after bug fix)."""
    unassigned_id = seeded_data['unassigned_employee'].id

    analytics_response = api_client.get(
        '/dashboard/analytics',
        headers=manager_auth_headers,
        params={
            'start_date': (date.today() - timedelta(days=5)).isoformat(),
            'end_date': date.today().isoformat(),
            'user_id': unassigned_id,
        },
    )
    assert analytics_response.status_code == 200
    result = analytics_response.json()

    assert float(result['total_hours']) == 0.0


def test_manager_cannot_approve_non_report_entry(
    api_client: TestClient,
    manager_auth_headers: dict,
    seeded_data: dict,
):
    """Manager should not see entries from non-reports in pending queue."""
    unassigned_id = seeded_data['unassigned_employee'].id

    pending_response = api_client.get(
        '/approvals/pending',
        headers=manager_auth_headers,
    )
    assert pending_response.status_code == 200

    unassigned_entries = [
        e for e in pending_response.json()
        if e['user']['id'] == unassigned_id
    ]
    assert len(unassigned_entries) == 0


def test_inactive_user_cannot_login(api_client: TestClient):
    """Inactive user should fail authentication."""
    login_response = api_client.post(
        "/auth/login",
        json={"email": "inactive.emp@example.com", "password": "password"},
    )
    assert login_response.status_code in [401, 403]


def test_admin_can_assign_projects_and_manager(
    api_client: TestClient,
    admin_auth_headers: dict,
    seeded_data: dict,
):
    """Admin can create employee with both project and manager assignments."""
    create_response = api_client.post(
        "/users",
        headers=admin_auth_headers,
        json={
            "email": "new-emp@example.com",
            "username": "new-emp",
            "full_name": "New Employee",
            "title": "Engineer",
            "password": "Password1!",
            "role": "EMPLOYEE",
            "is_active": True,
            "manager_id": seeded_data['manager'].id,
            "project_ids": [seeded_data['project'].id, seeded_data['second_project'].id],
        },
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created['manager_id'] == seeded_data['manager'].id
    assert len(created['project_ids']) == 2


def test_manager_analytics_accessible(
    api_client: TestClient,
    manager_auth_headers: dict,
    seeded_data: dict,
):
    """Manager can view dashboard analytics scoped to their team."""
    mgr_response = api_client.get(
        '/dashboard/analytics',
        headers=manager_auth_headers,
        params={
            'start_date': (date.today() - timedelta(days=5)).isoformat(),
            'end_date': date.today().isoformat(),
        },
    )
    assert mgr_response.status_code == 200
    mgr_hours = float(mgr_response.json()['total_hours'])
    assert mgr_hours >= 0
