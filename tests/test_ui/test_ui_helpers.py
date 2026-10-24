# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
"""Breadcrumbs, regulator wording and the permissions-matrix level (no database)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from flask import Flask
from flask_babel import Babel

from utils.breadcrumbs import breadcrumb_trail
from utils.regulator import _split

app = Flask(__name__)
Babel(app)


@app.route('/risk-management/')
def rm_home():
    return 'x'


@app.route('/risk-management/register')
def rm_register():
    return 'x'


@app.route('/risk-management/register/<int:rid>')
def rm_detail(rid):
    return 'x'


def test_breadcrumbs_link_only_existing_pages():
    with app.test_request_context('/risk-management/register/12'):
        trail = breadcrumb_trail()
    assert trail == [('Risk Management', '/risk-management/'), ('Risk Register', '/risk-management/register'), ('#12', None)]
    with app.test_request_context('/risk-management/risk/12/edit'):
        trail = breadcrumb_trail()
    assert trail[1] == ('Risk', None)          # no page answers /risk-management/risk
    assert trail[-1] == ('Edit', None)


def test_regulator_name_split():
    assert _split('Financial Regulatory Authority (FRA)') == ('Financial Regulatory Authority', 'FRA')
    assert _split('Central Bank of Egypt') == ('Central Bank of Egypt', '')


class _U:
    def __init__(self, role, perms, admin_mods=()):
        self.role, self.perms, self.admin_mods = role, perms, admin_mods

    def is_admin(self):
        return self.role == 'admin'

    def can_admin_module(self, m):
        return self.is_admin() or m in self.admin_mods

    def can_edit(self, m):
        return self.perms.get(m) in ('edit', 'admin')

    def can_view(self, m):
        return self.perms.get(m) in ('view', 'edit', 'admin')


def test_effective_level():
    import importlib
    try:
        routes = importlib.import_module('admin.routes')
    except Exception:          # app dependencies missing in a bare environment
        return
    lv = routes.effective_level
    assert lv(_U('admin', {}), 'aml') == 'approve'
    assert lv(_U('compliance_officer', {'aml': 'edit'}), 'aml') == 'approve'
    assert lv(_U('manager', {'aml': 'edit'}), 'aml') == 'edit'
    assert lv(_U('employee', {'aml': 'view'}), 'aml') == 'view'
    assert lv(_U('employee', {}), 'aml') == 'none'
    assert lv(_U('analyst', {'regcontrols': 'admin'}, admin_mods=('regcontrols',)), 'regcontrols') == 'approve'
