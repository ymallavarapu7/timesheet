from fastapi.testclient import TestClient
import base64
from datetime import date, timedelta
import json


def test_auth_login_success_and_failure(api_client: TestClient):
    success = api_client.post(
        "/auth/login",
        json={"email": "emp@example.com", "password": "password"},
    )
    assert success.status_code == 200
    payload = success.json()
    assert payload["token_type"] == "bearer"
    assert payload["user"]["email"] == "emp@example.com"
    assert payload["user"]["can_review"] is False
    assert payload["user"]["is_external"] is False

    token_payload = payload["access_token"].split(".")[1]
    token_payload += "=" * (-len(token_payload) % 4)
    decoded = json.loads(base64.urlsafe_b64decode(token_payload))
    assert decoded["sub"] is not None
    assert decoded["can_review"] is False

    failure = api_client.post(
        "/auth/login",
        json={"email": "emp@example.com", "password": "wrongpass"},
    )
    assert failure.status_code == 401


def test_auth_me_returns_authenticated_user(api_client: TestClient, auth_headers: dict):
    response = api_client.get("/auth/me", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "emp@example.com"
    assert body["role"] == "EMPLOYEE"
    assert body["can_review"] is False
    assert body["is_external"] is False


def test_projects_list_returns_data_for_authenticated_user(api_client: TestClient, auth_headers: dict):
    response = api_client.get("/projects", headers=auth_headers)

    assert response.status_code == 200
    projects = response.json()
    assert len(projects) >= 1
    assert projects[0]["client"]["name"] == "Test Client"


def test_timesheets_my_create_update_and_submit(api_client: TestClient, auth_headers: dict):
    entry_date = (date.today() - timedelta(days=3)).isoformat()

    my_entries = api_client.get("/timesheets/my", headers=auth_headers)
    assert my_entries.status_code == 200
    existing = my_entries.json()
    assert len(existing) >= 1
    assert existing[0]["user"]["email"] == "emp@example.com"

    create_response = api_client.post(
        "/timesheets",
        headers=auth_headers,
        json={
            "project_id": 1,
            "entry_date": entry_date,
            "hours": "3.50",
            "description": "API test entry",
        },
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["status"] == "DRAFT"

    entry_id = created["id"]
    update_response = api_client.put(
        f"/timesheets/{entry_id}",
        headers=auth_headers,
        json={
            "description": "Updated API test entry",
            "hours": "3.00",
            "edit_reason": "Refined entry",
            "history_summary": "Adjusted hours and description",
        },
    )
    assert update_response.status_code == 200
    assert update_response.json()["description"] == "Updated API test entry"

    latest_entries = api_client.get("/timesheets/my", headers=auth_headers)
    assert latest_entries.status_code == 200
    draft_ids = [entry["id"]
                 for entry in latest_entries.json() if entry["status"] == "DRAFT"]

    submit_response = api_client.post(
        "/timesheets/submit",
        headers=auth_headers,
        json={"entry_ids": draft_ids},
    )
    assert submit_response.status_code == 400
    assert "allowed on or after the last working day" in submit_response.json()[
        "detail"]


def test_admin_can_create_own_timesheet_entry(api_client: TestClient, admin_auth_headers: dict):
    entry_date = date.today().isoformat()

    create_response = api_client.post(
        "/timesheets",
        headers=admin_auth_headers,
        json={
            "project_id": 1,
            "entry_date": entry_date,
            "hours": "1.00",
            "description": "Admin system work",
        },
    )
    assert create_response.status_code == 201
    payload = create_response.json()
    assert payload["status"] == "DRAFT"


def test_approvals_pending_and_approve(api_client: TestClient, manager_auth_headers: dict):
    pending_response = api_client.get(
        "/approvals/pending", headers=manager_auth_headers)
    assert pending_response.status_code == 200

    pending = pending_response.json()
    assert len(pending) >= 1
    entry_id = pending[0]["id"]

    approve_response = api_client.post(
        f"/approvals/{entry_id}/approve",
        headers=manager_auth_headers,
        json={},
    )
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "APPROVED"


def test_employee_cannot_access_pending_approvals(api_client: TestClient, auth_headers: dict):
    response = api_client.get("/approvals/pending", headers=auth_headers)

    assert response.status_code == 403


def test_dashboard_summary_returns_live_metrics(api_client: TestClient, auth_headers: dict):
    response = api_client.get('/dashboard/summary', headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert 'hours_logged' in body
    assert 'approved_hours' in body
    assert 'pending_hours' in body
    assert 'pending_approvals' in body
    assert 'team_members' in body


def test_time_off_create_submit_and_manager_approval(api_client: TestClient, auth_headers: dict, manager_auth_headers: dict):
    list_response = api_client.get('/time-off/my', headers=auth_headers)
    assert list_response.status_code == 200

    create_response = api_client.post(
        '/time-off',
        headers=auth_headers,
        json={
            'request_date': '2026-03-15',
            'hours': '8.00',
            'leave_type': 'PTO',
            'reason': 'Vacation',
        },
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created['status'] == 'DRAFT'

    submit_response = api_client.post(
        '/time-off/submit',
        headers=auth_headers,
        json={'request_ids': [created['id']]},
    )
    assert submit_response.status_code == 200
    assert submit_response.json()[0]['status'] == 'SUBMITTED'

    pending_response = api_client.get(
        '/time-off-approvals/pending', headers=manager_auth_headers)
    assert pending_response.status_code == 200
    pending = pending_response.json()
    assert any(item['id'] == created['id'] for item in pending)

    approve_response = api_client.post(
        f"/time-off-approvals/{created['id']}/approve",
        headers=manager_auth_headers,
        json={},
    )
    assert approve_response.status_code == 200
    assert approve_response.json()['status'] == 'APPROVED'


def test_admin_can_assign_manager_and_project_access(api_client: TestClient, admin_auth_headers: dict):
    users_response = api_client.get('/users', headers=admin_auth_headers)
    assert users_response.status_code == 200
    manager_id = next(
        user['id'] for user in users_response.json() if user['email'] == 'manager@example.com'
    )

    create_response = api_client.post(
        "/users",
        headers=admin_auth_headers,
        json={
            "email": "assigned-emp@example.com",
            "username": "assigned-emp",
            "full_name": "Assigned Employee",
            "title": "Associate Engineer",
            "department": "Software Engineering",
            "password": "Password1!",
            "role": "EMPLOYEE",
            "is_active": True,
            "manager_id": manager_id,
            "project_ids": [1],
        },
    )
    assert create_response.status_code == 201, create_response.text
    created_user = create_response.json()
    assert created_user["manager_id"] == manager_id
    assert created_user["project_ids"] == [1]

    login_response = api_client.post(
        "/auth/login",
        json={"email": "assigned-emp@example.com", "password": "Password1!"},
    )
    assert login_response.status_code == 200
    employee_headers = {
        "Authorization": f"Bearer {login_response.json()['access_token']}"
    }

    projects_response = api_client.get("/projects", headers=employee_headers)
    assert projects_response.status_code == 200
    projects = projects_response.json()
    assert [project["id"] for project in projects] == [1]

    denied_entry = api_client.post(
        "/timesheets",
        headers=employee_headers,
        json={
            "project_id": 2,
            "entry_date": "2026-03-13",
            "hours": "6.50",
            "description": "Should be denied",
        },
    )
    assert denied_entry.status_code == 403


def test_manager_reports_to_must_be_senior_manager_or_ceo(api_client: TestClient, admin_auth_headers: dict):
    users_response = api_client.get('/users', headers=admin_auth_headers)
    assert users_response.status_code == 200
    users = users_response.json()

    manager_id = next(user['id']
                      for user in users if user['email'] == 'manager@example.com')
    senior_manager_id = next(
        user['id'] for user in users if user['email'] == 'senior.manager@example.com')

    create_invalid = api_client.post(
        '/users',
        headers=admin_auth_headers,
        json={
            'email': 'manager-child@example.com',
            'username': 'managerchild',
            'full_name': 'Manager Child',
            'title': 'Engineering Manager',
            'department': 'Engineering',
            'password': 'Password1!',
            'role': 'MANAGER',
            'is_active': True,
            'manager_id': manager_id,
            'project_ids': [],
        },
    )
    assert create_invalid.status_code == 400
    assert 'Selected supervisor is invalid' in create_invalid.json()['detail']

    create_valid = api_client.post(
        '/users',
        headers=admin_auth_headers,
        json={
            'email': 'manager-valid@example.com',
            'username': 'managervalid',
            'full_name': 'Manager Valid',
            'title': 'Engineering Manager',
            'department': 'Engineering',
            'password': 'Password1!',
            'role': 'MANAGER',
            'is_active': True,
            'manager_id': senior_manager_id,
            'project_ids': [],
        },
    )
    assert create_valid.status_code == 201, create_valid.text
    assert create_valid.json()['manager_id'] == senior_manager_id


def test_admin_reports_to_must_be_manager_or_senior_manager(api_client: TestClient, admin_auth_headers: dict):
    users_response = api_client.get('/users', headers=admin_auth_headers)
    assert users_response.status_code == 200
    users = users_response.json()

    ceo_id = next(user['id']
                  for user in users if user['email'] == 'ceo@example.com')
    manager_id = next(user['id']
                      for user in users if user['email'] == 'manager@example.com')

    create_invalid = api_client.post(
        '/users',
        headers=admin_auth_headers,
        json={
            'email': 'admin-invalid-ceo@example.com',
            'username': 'admininvalidceo',
            'full_name': 'Admin Invalid CEO',
            'title': 'System Administrator',
            'department': 'Administration',
            'password': 'Password1!',
            'role': 'ADMIN',
            'is_active': True,
            'manager_id': ceo_id,
            'project_ids': [],
        },
    )
    assert create_invalid.status_code == 400
    assert 'Selected supervisor is invalid' in create_invalid.json()['detail']

    create_valid = api_client.post(
        '/users',
        headers=admin_auth_headers,
        json={
            'email': 'admin-valid-manager@example.com',
            'username': 'adminvalidmanager',
            'full_name': 'Admin Valid Manager',
            'title': 'System Administrator',
            'department': 'Administration',
            'password': 'Password1!',
            'role': 'ADMIN',
            'is_active': True,
            'manager_id': manager_id,
            'project_ids': [],
        },
    )
    assert create_valid.status_code == 201, create_valid.text
    assert create_valid.json()['manager_id'] == manager_id


def test_supervisor_department_family_must_be_compatible_unless_ceo(api_client: TestClient, admin_auth_headers: dict):
    users_response = api_client.get('/users', headers=admin_auth_headers)
    assert users_response.status_code == 200
    users = users_response.json()

    ceo_id = next(user['id']
                  for user in users if user['email'] == 'ceo@example.com')
    engineering_manager_id = next(
        user['id'] for user in users if user['email'] == 'manager@example.com')

    infra_manager_response = api_client.post(
        '/users',
        headers=admin_auth_headers,
        json={
            'email': 'infra.manager@example.com',
            'username': 'inframanager',
            'full_name': 'Infra Manager',
            'title': 'Infrastructure Manager',
            'department': 'Infrastructure',
            'password': 'Password1!',
            'role': 'MANAGER',
            'is_active': True,
            'manager_id': ceo_id,
            'project_ids': [],
        },
    )
    assert infra_manager_response.status_code == 201, infra_manager_response.text
    infra_manager_id = infra_manager_response.json()['id']

    incompatible_employee_response = api_client.post(
        '/users',
        headers=admin_auth_headers,
        json={
            'email': 'product.employee.cross@example.com',
            'username': 'productcross',
            'full_name': 'Product Cross Employee',
            'title': 'Software Engineer',
            'department': 'Product',
            'password': 'Password1!',
            'role': 'EMPLOYEE',
            'is_active': True,
            'manager_id': infra_manager_id,
            'project_ids': [],
        },
    )
    assert incompatible_employee_response.status_code == 400
    assert 'compatible department family' in incompatible_employee_response.json()[
        'detail'].lower()

    compatible_employee_response = api_client.post(
        '/users',
        headers=admin_auth_headers,
        json={
            'email': 'qa.employee.compatible@example.com',
            'username': 'qacompatible',
            'full_name': 'QA Compatible Employee',
            'title': 'QA Engineer',
            'department': 'QA & Testing',
            'password': 'Password1!',
            'role': 'EMPLOYEE',
            'is_active': True,
            'manager_id': engineering_manager_id,
            'project_ids': [],
        },
    )
    assert compatible_employee_response.status_code == 201, compatible_employee_response.text

    ceo_employee_response = api_client.post(
        '/users',
        headers=admin_auth_headers,
        json={
            'email': 'eng.employee.ceo@example.com',
            'username': 'engceo',
            'full_name': 'Engineering CEO Employee',
            'title': 'Software Engineer',
            'department': 'Engineering',
            'password': 'Password1!',
            'role': 'EMPLOYEE',
            'is_active': True,
            'manager_id': ceo_id,
            'project_ids': [],
        },
    )
    assert ceo_employee_response.status_code == 201, ceo_employee_response.text


def test_employee_sees_rejection_notification(api_client: TestClient, auth_headers: dict, manager_auth_headers: dict):
    pending_response = api_client.get(
        '/approvals/pending', headers=manager_auth_headers)
    assert pending_response.status_code == 200
    pending_entry = pending_response.json()[0]

    reject_response = api_client.post(
        f"/approvals/{pending_entry['id']}/reject",
        headers=manager_auth_headers,
        json={'rejection_reason': 'Please fix the logged hours and resubmit.'},
    )
    assert reject_response.status_code == 200
    assert reject_response.json()['status'] == 'REJECTED'

    notification_response = api_client.get(
        '/notifications/summary', headers=auth_headers)
    assert notification_response.status_code == 200
    payload = notification_response.json()
    assert payload['route_counts']['my_time'] >= 1
    assert any(
        item['id'] == 'rejected-time-entries' for item in payload['items'])


def test_admin_sees_assignment_notifications(api_client: TestClient, admin_auth_headers: dict):
    notification_response = api_client.get(
        '/notifications/summary', headers=admin_auth_headers)
    assert notification_response.status_code == 200
    payload = notification_response.json()
    assert payload['route_counts']['admin'] >= 1
    assert any(
        item['id'] == 'employees-without-manager' for item in payload['items'])


def test_notification_mark_read_and_mark_all(api_client: TestClient, auth_headers: dict, manager_auth_headers: dict):
    pending_response = api_client.get(
        '/approvals/pending', headers=manager_auth_headers)
    assert pending_response.status_code == 200
    pending_entry = pending_response.json()[0]

    reject_response = api_client.post(
        f"/approvals/{pending_entry['id']}/reject",
        headers=manager_auth_headers,
        json={'rejection_reason': 'Please fix and resubmit.'},
    )
    assert reject_response.status_code == 200

    first_summary = api_client.get(
        '/notifications/summary', headers=auth_headers)
    assert first_summary.status_code == 200
    first_payload = first_summary.json()
    assert first_payload['total_count'] > 0

    rejected_item = next(
        item for item in first_payload['items'] if item['id'] == 'rejected-time-entries')
    mark_read_response = api_client.post(
        '/notifications/read',
        headers=auth_headers,
        json={'notification_id': rejected_item['id']},
    )
    assert mark_read_response.status_code == 200
    assert mark_read_response.json()['success'] is True

    second_summary = api_client.get(
        '/notifications/summary', headers=auth_headers)
    assert second_summary.status_code == 200
    second_payload = second_summary.json()
    rejected_after_read = next(
        item for item in second_payload['items'] if item['id'] == 'rejected-time-entries')
    assert rejected_after_read['is_read'] is True

    mark_all_response = api_client.post(
        '/notifications/read-all', headers=auth_headers, json={})
    assert mark_all_response.status_code == 200
    assert mark_all_response.json()['success'] is True

    third_summary = api_client.get(
        '/notifications/summary', headers=auth_headers)
    assert third_summary.status_code == 200
    third_payload = third_summary.json()
    assert third_payload['total_count'] == 0
    assert len(third_payload['items']) > 0
    assert all(item['is_read'] for item in third_payload['items'])


def test_manager_employee_scope_for_user_listing_and_updates(api_client: TestClient, manager_auth_headers: dict):
    users_response = api_client.get('/users', headers=manager_auth_headers)
    assert users_response.status_code == 200
    users = users_response.json()

    emails = {user['email'] for user in users}
    assert 'emp@example.com' in emails
    assert 'emp2@example.com' not in emails
    assert 'senior.manager@example.com' not in emails

    employee_id = next(user['id']
                       for user in users if user['email'] == 'emp@example.com')

    denied_non_project_update = api_client.put(
        f'/users/{employee_id}',
        headers=manager_auth_headers,
        json={'full_name': 'Should Not Work'},
    )
    assert denied_non_project_update.status_code == 403
    assert denied_non_project_update.json(
    )['detail'] == 'Managers can only update employee project assignments'

    allowed_project_update = api_client.put(
        f'/users/{employee_id}',
        headers=manager_auth_headers,
        json={'project_ids': [1]},
    )
    assert allowed_project_update.status_code == 200


def test_senior_manager_manager_hierarchy_visibility_and_analytics(
    api_client: TestClient,
    senior_manager_auth_headers: dict,
    manager_auth_headers: dict,
):
    users_response = api_client.get(
        '/users', headers=senior_manager_auth_headers)
    assert users_response.status_code == 200
    users = users_response.json()

    emails = {user['email'] for user in users}
    assert 'manager@example.com' in emails
    assert 'emp@example.com' in emails
    assert 'emp2@example.com' not in emails

    manager_user_id = next(
        user['id'] for user in users if user['email'] == 'manager@example.com')

    create_manager_entry = api_client.post(
        '/timesheets',
        headers=manager_auth_headers,
        json={
            'project_id': 1,
            'entry_date': date.today().isoformat(),
            'hours': '2.50',
            'description': 'Manager personal work',
        },
    )
    assert create_manager_entry.status_code == 201

    analytics_response = api_client.get(
        '/dashboard/analytics',
        headers=senior_manager_auth_headers,
        params={
            'start_date': date.today().isoformat(),
            'end_date': date.today().isoformat(),
            'user_id': manager_user_id,
        },
    )
    assert analytics_response.status_code == 200
    assert float(analytics_response.json()['total_hours']) >= 2.5


def test_admin_has_dashboard_scope_and_approval_access(api_client: TestClient, admin_auth_headers: dict):
    users_response = api_client.get('/users', headers=admin_auth_headers)
    assert users_response.status_code == 200
    users = users_response.json()

    employee_id = next(user['id']
                       for user in users if user['email'] == 'emp@example.com')

    pending_response = api_client.get(
        '/approvals/pending', headers=admin_auth_headers)
    assert pending_response.status_code == 200

    analytics_response = api_client.get(
        '/dashboard/analytics',
        headers=admin_auth_headers,
        params={
            'start_date': (date.today() - timedelta(days=1)).isoformat(),
            'end_date': date.today().isoformat(),
            'user_id': employee_id,
        },
    )
    assert analytics_response.status_code == 200
    assert float(analytics_response.json()['total_hours']) > 0


def test_notification_counts_match_filtered_history(api_client: TestClient, auth_headers: dict):
    """
    Verify that notification counts match the actual filtered history data visible to users.
    Counts should be consistent across different users/roles and include only year-to-date entries.
    """
    today = date.today()
    year_start = date(today.year, 1, 1)

    # Get notifications
    notif_response = api_client.get(
        "/notifications/summary", headers=auth_headers)
    assert notif_response.status_code == 200
    notifications = notif_response.json()

    notification_counts = {
        item['id']: item['count']
        for item in notifications.get('items', [])
    }

    # Get filtered history entries (same date range as notifications: year-to-date)
    history_response = api_client.get(
        "/timesheets/my",
        headers=auth_headers,
        params={
            'start_date': year_start.isoformat(),
            'end_date': today.isoformat(),
            'limit': 1000,
        },
    )
    assert history_response.status_code == 200
    all_entries = history_response.json()

    # Verify rejected count matches
    if 'rejected-time-entries' in notification_counts:
        rejected_from_history = sum(
            1 for entry in all_entries if entry['status'] == 'REJECTED'
        )
        rejected_from_notif = notification_counts['rejected-time-entries']
        assert rejected_from_notif == rejected_from_history, (
            f"Rejected count mismatch: notification says {rejected_from_notif}, "
            f"history shows {rejected_from_history}"
        )

    # Verify draft count matches
    if 'draft-time-entries' in notification_counts:
        draft_from_history = sum(
            1 for entry in all_entries if entry['status'] == 'DRAFT'
        )
        draft_from_notif = notification_counts['draft-time-entries']
        assert draft_from_notif == draft_from_history, (
            f"Draft count mismatch: notification says {draft_from_notif}, "
            f"history shows {draft_from_history}"
        )
