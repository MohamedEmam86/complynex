"""Access-control regressions: user management, whistleblowing case management,
policy staff lists, COBEC overview and regcontrols four-eyes. No database: the
checks under test run before any query."""
import pytest
from flask import Flask
from flask_login import LoginManager

from models.user import User


def _user(role, **perms):
    return User(id=99, email='t@example.com', password_hash='x', first_name='T', last_name='U',
                role=role, **perms)


@pytest.fixture()
def client_for():
    from admin import admin_bp
    from whistleblowing.routes import whistleblowing_bp
    from policies.routes import policies_bp
    from cobec.routes import cobec_bp

    app = Flask(__name__, template_folder='/nonexistent')
    app.config.update(SECRET_KEY='t', TESTING=True, WTF_CSRF_ENABLED=False)
    app.add_url_rule('/', 'dashboard', lambda: 'home')
    for bp in (admin_bp, whistleblowing_bp, policies_bp, cobec_bp):
        app.register_blueprint(bp)
    from flask_babel import Babel
    Babel(app)
    from extensions import limiter
    limiter.init_app(app)
    lm = LoginManager(app)
    holder = {}
    lm.request_loader(lambda req: holder.get('u'))

    def make(user):
        holder['u'] = user
        return app.test_client()
    return make


USER_ADMIN_URLS = [('get', '/admin/users'), ('get', '/admin/users/add'), ('post', '/admin/users/add'),
                   ('get', '/admin/users/edit/1'), ('post', '/admin/users/edit/1'),
                   ('post', '/admin/users/upload'), ('post', '/admin/users/delete/1'),
                   ('get', '/admin/security/mfa'), ('post', '/admin/users/1/mfa')]


@pytest.mark.parametrize('method,url', USER_ADMIN_URLS)
@pytest.mark.parametrize('who', [_user('compliance_officer', perm_config='edit'),
                                 _user('compliance_manager', perm_config='edit'),
                                 _user('employee', perm_config='view')])
def test_user_management_is_admin_only(client_for, who, method, url):
    r = getattr(client_for(who), method)(url, data={'role': 'admin'})
    assert r.status_code == 302 and r.headers['Location'].endswith('/')


@pytest.mark.parametrize('method,url', [('get', '/whistleblowing/tracking'),
                                        ('post', '/whistleblowing/tracking/remind-bulk'),
                                        ('get', '/whistleblowing/case/1'),
                                        ('post', '/whistleblowing/case/1/assign'),
                                        ('post', '/whistleblowing/case/1/remind')])
@pytest.mark.parametrize('role', ['employee', 'manager'])
def test_whistleblowing_case_management_needs_permission(client_for, role, method, url):
    r = getattr(client_for(_user(role)), method)(url)
    assert r.status_code == 302


@pytest.mark.parametrize('url', ['/policies/gap-analysis', '/policies/gap-analysis/export',
                                 '/policies/1/acknowledgments', '/policies/acknowledgment-dashboard'])
def test_policy_staff_lists_hidden_from_viewers(client_for, url):
    r = client_for(_user('employee', perm_policies='view')).get(url)
    assert r.status_code == 302 and r.headers['Location'].endswith('/policies/list')


def test_validate_new_user():
    from admin.routes import validate_new_user
    assert validate_new_user('not-an-email', 'Str0ng!Passw0rd', 'employee')
    assert validate_new_user('a@b.example', 'Short1!', 'employee')
    assert validate_new_user('a@b.example', 'Str0ng!Passw0rd', 'superuser')
    assert validate_new_user('a@b.example', 'Str0ng!Passw0rd', 'employee') is None
    assert validate_new_user('a@b.example', '', 'manager') is None


def test_four_eyes():
    from regcontrols.logic import four_eyes_error
    assert four_eyes_error(5, requested_by=5, completed_by=[7])
    assert four_eyes_error(5, requested_by=6, completed_by=[5, None])
    assert four_eyes_error(5, requested_by=6, completed_by=[7]) is None
    assert four_eyes_error(5) is None
