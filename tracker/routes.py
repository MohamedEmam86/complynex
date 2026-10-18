# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
#
# This software is the proprietary and confidential intellectual property of
# ComplyNex (complynex.online), owned by Mohamed Emam.
# Unauthorized copying, reproduction, modification,
# distribution, reverse engineering, or use of this software, in whole or in
# part, via any medium, is strictly prohibited without prior written
# permission from the owner.
#
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# Contact: f.mohemam85@gmail.com | admin@complynex.online
#
# Registered deployment: complynex.online
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================

"""
Declaration Tracker Routes
Provides unified dashboard for tracking COI, COBEC, and GHE declarations
"""
from flask import Blueprint, render_template, request, Response
from flask_login import login_required, current_user
from utils.decorators import permission_required
from database.db import get_db
from datetime import datetime
import csv
import io

tracker_bp = Blueprint('tracker', __name__, url_prefix='/tracker')

def get_declaration_stats(year=None):
    """Get statistics for all declaration types"""
    db = get_db()
    current_year = year or datetime.now().year
    
    # Total active employees
    total_employees = db.execute(
        'SELECT COUNT(*) as count FROM users WHERE is_active = 1'
    ).fetchone()['count']
    
    # COI stats (for active campaigns in the year)
    coi_submitted = db.execute('''
        SELECT COUNT(DISTINCT d.employee_id) 
        FROM coi_declarations d
        JOIN coi_campaigns c ON d.campaign_id = c.id
        WHERE c.campaign_year = %s
    ''', (current_year,)).fetchone()['count']
    
    # COBEC stats
    cobec_submitted = db.execute('''
        SELECT COUNT(*) as count FROM cobec_declarations WHERE declaration_year = %s
    ''', (current_year,)).fetchone()['count']
    
    # GHE stats (total declarations in the year)
    ghe_total = db.execute('''
        SELECT COUNT(*) as count FROM ghe_declarations 
        WHERE TO_CHAR(declaration_date::timestamp, 'YYYY') = %s
    ''', (str(current_year),)).fetchone()['count']
    
    return {
        'total_employees': total_employees,
        'coi': {
            'submitted': coi_submitted,
            'not_submitted': total_employees - coi_submitted,
            'rate': round((coi_submitted / total_employees * 100) if total_employees > 0 else 0, 1)
        },
        'cobec': {
            'submitted': cobec_submitted,
            'not_submitted': total_employees - cobec_submitted,
            'rate': round((cobec_submitted / total_employees * 100) if total_employees > 0 else 0, 1)
        },
        'ghe': {
            'total': ghe_total
        }
    }

def get_employee_submission_status(year=None):
    """Get submission status for each employee"""
    db = get_db()
    current_year = year or datetime.now().year
    
    employees = db.execute('''
        SELECT id, first_name || ' ' || last_name as name, email, department
        FROM users WHERE is_active = 1
        ORDER BY first_name, last_name
    ''').fetchall()
    
    result = []
    for emp in employees:
        emp_dict = dict(emp)
        
        # Check COI submission
        coi = db.execute('''
            SELECT 1 FROM coi_declarations d
            JOIN coi_campaigns c ON d.campaign_id = c.id
            WHERE d.employee_id = %s AND c.campaign_year = %s
        ''', (emp['id'], current_year)).fetchone()
        emp_dict['coi_submitted'] = bool(coi)
        
        # Check COBEC submission
        cobec = db.execute('''
            SELECT 1 FROM cobec_declarations 
            WHERE employee_id = %s AND declaration_year = %s
        ''', (emp['id'], current_year)).fetchone()
        emp_dict['cobec_submitted'] = bool(cobec)
        
        # Count GHE declarations
        ghe_count = db.execute('''
            SELECT COUNT(*) as count FROM ghe_declarations 
            WHERE employee_id = %s AND TO_CHAR(declaration_date::timestamp, 'YYYY') = %s
        ''', (emp['id'], str(current_year))).fetchone()['count']
        emp_dict['ghe_count'] = ghe_count
        
        result.append(emp_dict)
    
    return result

@tracker_bp.route('/')
@login_required
@permission_required('tm', level='view')
def dashboard():
    """Declaration tracker dashboard"""
    year = request.args.get('year', datetime.now().year, type=int)
    stats = get_declaration_stats(year)
    employees = get_employee_submission_status(year)
    
    # Calculate department summaries
    departments = {}
    for emp in employees:
        dept = emp.get('department') or 'Unassigned'
        if dept not in departments:
            departments[dept] = {'total': 0, 'coi': 0, 'cobec': 0}
        departments[dept]['total'] += 1
        if emp['coi_submitted']:
            departments[dept]['coi'] += 1
        if emp['cobec_submitted']:
            departments[dept]['cobec'] += 1
    
    return render_template('tracker/dashboard.html',
                         stats=stats,
                         employees=employees,
                         departments=departments,
                         selected_year=year)

@tracker_bp.route('/export/<declaration_type>')
@login_required
@permission_required('tm', level='view')
def export_declarations(declaration_type):
    """Export declarations to CSV"""
    db = get_db()
    year = request.args.get('year', datetime.now().year, type=int)
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    if declaration_type == 'coi':
        writer.writerow(['Employee Name', 'Department', 'Declaration Date', 'Status', 
                        'Financial Interests', 'Family in Competitor', 'Family in Supplier',
                        'Outside Employment', 'Received Gifts', 'Other Conflicts'])
        
        rows = db.execute('''
            SELECT u.first_name || ' ' || u.last_name as name, u.department,
                   d.declaration_date, d.status,
                   d.has_financial_interests, d.has_family_in_competitor,
                   d.has_family_in_supplier, d.has_outside_employment,
                   d.has_received_gifts, d.has_other_conflicts
            FROM coi_declarations d
            JOIN users u ON d.employee_id = u.id
            JOIN coi_campaigns c ON d.campaign_id = c.id
            WHERE c.campaign_year = %s
            ORDER BY u.first_name, u.last_name
        ''', (year,)).fetchall()
        
        for row in rows:
            writer.writerow([
                row['name'], row['department'], row['declaration_date'], row['status'],
                'Yes' if row['has_financial_interests'] else 'No',
                'Yes' if row['has_family_in_competitor'] else 'No',
                'Yes' if row['has_family_in_supplier'] else 'No',
                'Yes' if row['has_outside_employment'] else 'No',
                'Yes' if row['has_received_gifts'] else 'No',
                'Yes' if row['has_other_conflicts'] else 'No'
            ])
    
    elif declaration_type == 'cobec':
        writer.writerow(['Employee Name', 'Department', 'Declaration Date', 'Year',
                        'Read Code', 'Understands Responsibilities', 'Commits to Compliance',
                        'Will Report Violations', 'Known Violations', 'Prior Misconduct'])
        
        rows = db.execute('''
            SELECT u.first_name || ' ' || u.last_name as name, u.department,
                   d.declaration_date, d.declaration_year,
                   d.has_read_code, d.understands_responsibilities,
                   d.commits_to_compliance, d.will_report_violations,
                   d.has_known_violations, d.has_prior_misconduct
            FROM cobec_declarations d
            JOIN users u ON d.employee_id = u.id
            WHERE d.declaration_year = %s
            ORDER BY u.first_name, u.last_name
        ''', (year,)).fetchall()
        
        for row in rows:
            writer.writerow([
                row['name'], row['department'], row['declaration_date'], row['declaration_year'],
                'Yes' if row['has_read_code'] else 'No',
                'Yes' if row['understands_responsibilities'] else 'No',
                'Yes' if row['commits_to_compliance'] else 'No',
                'Yes' if row['will_report_violations'] else 'No',
                'Yes' if row['has_known_violations'] else 'No',
                'Yes' if row['has_prior_misconduct'] else 'No'
            ])
    
    elif declaration_type == 'ghe':
        writer.writerow(['Declaration #', 'Employee Name', 'Department', 'Type', 'Direction',
                        'Value (EGP)', 'Date', 'Status', 'Description'])
        
        rows = db.execute('''
            SELECT d.declaration_number, u.first_name || ' ' || u.last_name as name, 
                   u.department, d.ghe_type, d.direction,
                   d.estimated_value_egp, d.event_date, d.status, d.description
            FROM ghe_declarations d
            LEFT JOIN users u ON d.employee_id = u.id
            WHERE TO_CHAR(d.declaration_date::timestamp, 'YYYY') = %s
            ORDER BY d.created_at DESC
        ''', (str(year),)).fetchall()
        
        for row in rows:
            writer.writerow([
                row['declaration_number'], row['name'] or 'Public', row['department'],
                row['ghe_type'], row['direction'], row['estimated_value_egp'],
                row['event_date'], row['status'], row['description'][:100]
            ])
    
    elif declaration_type == 'status':
        # Export employee submission status
        writer.writerow(['Employee Name', 'Email', 'Department', 'COI Submitted', 'COBEC Submitted', 'GHE Count'])
        employees = get_employee_submission_status(year)
        
        for emp in employees:
            writer.writerow([
                emp['name'], emp['email'], emp['department'],
                'Yes' if emp['coi_submitted'] else 'No',
                'Yes' if emp['cobec_submitted'] else 'No',
                emp['ghe_count']
            ])
    
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={declaration_type}_export_{year}.csv'}
    )
