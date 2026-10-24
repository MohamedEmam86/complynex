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

# ENHANCED GOVERNANCE MODELS - COMPLYNEX CMS
# File: models/governance_enhanced.py
# Compatible with: Raw SQL pattern (no ORM)
# Integrates with: existing database/db.py

from database.db import get_db
from datetime import datetime, timedelta
import json

# ============================================================================
# FIT & PROPER ASSESSMENTS
# ============================================================================

class FitProperAssessment:
    """CBE Mandatory Fit & Proper Assessment Model"""
    
    def __init__(self, id=None, member_id=None, assessment_date=None,
                 assessment_type=None, total_score=None, assessment_result=None,
                 cbe_approval_status=None, next_review_date=None, **kwargs):
        self.id = id
        self.member_id = member_id
        self.assessment_date = assessment_date
        self.assessment_type = assessment_type
        self.total_score = total_score
        self.assessment_result = assessment_result
        self.cbe_approval_status = cbe_approval_status
        self.next_review_date = next_review_date
        
        # Store all other fields
        for key, value in kwargs.items():
            setattr(self, key, value)
    
    @staticmethod
    def create(data):
        """Create new Fit & Proper assessment"""
        db = get_db()
        
        # Calculate total score from individual scores
        total_score = (
            data.get('honesty_integrity_score', 0) +
            data.get('competence_capability_score', 0) +
            data.get('financial_soundness_score', 0) +
            data.get('reputation_score', 0) +
            data.get('time_commitment_score', 0)
        )
        
        cursor = db.execute('''
            INSERT INTO fit_proper_assessments (
                member_id, assessment_date, assessment_type, assessment_period,
                honesty_integrity_score, competence_capability_score,
                financial_soundness_score, reputation_score, time_commitment_score,
                criminal_record_check, criminal_record_clear, criminal_record_details,
                credit_check, credit_score, credit_check_clear,
                regulatory_actions_check, regulatory_actions_found, regulatory_actions_details,
                litigation_check, active_litigation, litigation_details,
                bankruptcy_check, bankruptcy_history, bankruptcy_details,
                references_checked, references_satisfactory, references_summary,
                qualifications_verified, professional_licenses_valid,
                relevant_experience_years, board_experience_adequate,
                total_score, assessment_result, conditions_imposed,
                submitted_to_cbe, cbe_submission_date, cbe_reference_number,
                regulator_id, submitted_to_regulator, regulator_submission_date,
                regulator_reference_number, regulator_approval_date,
                regulator_approval_status, regulator_feedback,
                next_review_date, assessment_report_path, created_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', (
            data.get('member_id'),
            data.get('assessment_date') or datetime.now().date(),
            data.get('assessment_type', 'PERIODIC'),
            data.get('assessment_period'),
            data.get('honesty_integrity_score', 0),
            data.get('competence_capability_score', 0),
            data.get('financial_soundness_score', 0),
            data.get('reputation_score', 0),
            data.get('time_commitment_score', 0),
            1 if data.get('criminal_record_check') else 0,
            1 if data.get('criminal_record_clear', True) else 0,
            data.get('criminal_record_details'),
            1 if data.get('credit_check') else 0,
            data.get('credit_score'),
            1 if data.get('credit_check_clear', True) else 0,
            1 if data.get('regulatory_actions_check') else 0,
            1 if data.get('regulatory_actions_found') else 0,
            data.get('regulatory_actions_details'),
            1 if data.get('litigation_check') else 0,
            1 if data.get('active_litigation') else 0,
            data.get('litigation_details'),
            1 if data.get('bankruptcy_check') else 0,
            1 if data.get('bankruptcy_history') else 0,
            data.get('bankruptcy_details'),
            1 if data.get('references_checked') else 0,
            1 if data.get('references_satisfactory', True) else 0,
            data.get('references_summary'),
            1 if data.get('qualifications_verified') else 0,
            1 if data.get('professional_licenses_valid', True) else 0,
            data.get('relevant_experience_years', 0),
            1 if data.get('board_experience_adequate', True) else 0,
            total_score,
            data.get('assessment_result', 'APPROVED'),
            data.get('conditions_imposed'),
            1 if data.get('submitted_to_cbe') else 0,
            data.get('cbe_submission_date'),
            data.get('cbe_reference_number'),
            data.get('regulator_id'),
            1 if data.get('submitted_to_regulator') else 0,
            data.get('regulator_submission_date'),
            data.get('regulator_reference_number'),
            data.get('regulator_approval_date'),
            data.get('regulator_approval_status'),
            data.get('regulator_feedback'),
            data.get('next_review_date'),
            data.get('assessment_report_path'),
            data.get('created_by')
        ))
        db.commit()
        return cursor.fetchone()['id']
    
    @staticmethod
    def get_by_member(member_id):
        """Get all assessments for a member"""
        db = get_db()
        rows = db.execute('''
            SELECT * FROM fit_proper_assessments 
            WHERE member_id = %s 
            ORDER BY assessment_date DESC
        ''', (member_id,)).fetchall()
        return [FitProperAssessment(**dict(row)) for row in rows]
    
    @staticmethod
    def get_latest_by_member(member_id):
        """Get most recent assessment for a member"""
        db = get_db()
        row = db.execute('''
            SELECT * FROM fit_proper_assessments 
            WHERE member_id = %s 
            ORDER BY assessment_date DESC 
            LIMIT 1
        ''', (member_id,)).fetchone()
        return FitProperAssessment(**dict(row)) if row else None
    
    @staticmethod
    def get_due_for_review():
        """Get members due for Fit & Proper review"""
        db = get_db()
        rows = db.execute('''
            SELECT bm.id as member_id, bm.member_name, fpa.next_review_date
            FROM board_members bm
            LEFT JOIN (
                SELECT member_id, MAX(assessment_date) as max_date
                FROM fit_proper_assessments
                GROUP BY member_id
            ) latest ON bm.id = latest.member_id
            LEFT JOIN fit_proper_assessments fpa 
                ON bm.id = fpa.member_id AND fpa.assessment_date = latest.max_date
            WHERE bm.status = 'ACTIVE' 
            AND (fpa.next_review_date IS NULL OR fpa.next_review_date::date <= CURRENT_DATE + INTERVAL '30 days')
        ''').fetchall()
        return rows

# ============================================================================
# INDEPENDENCE DECLARATIONS
# ============================================================================

class IndependenceDeclaration:
    """Track board member independence status"""
    
    def __init__(self, id=None, member_id=None, declaration_date=None,
                 independence_status=None, next_declaration_due=None, **kwargs):
        self.id = id
        self.member_id = member_id
        self.declaration_date = declaration_date
        self.independence_status = independence_status
        self.next_declaration_due = next_declaration_due
        
        for key, value in kwargs.items():
            setattr(self, key, value)
    
    @staticmethod
    def create(data):
        """Create independence declaration"""
        db = get_db()
        
        # Calculate independence status based on criteria
        criteria_met = all([
            1 if data.get('no_material_interest', True) else 0,
            1 if data.get('no_employment_5years', True) else 0,
            1 if data.get('no_relative_employment', True) else 0,
            1 if data.get('no_professional_relationship', True) else 0,
            1 if data.get('no_significant_business', True) else 0,
            1 if data.get('no_remuneration_except_fees', True) else 0,
            1 if data.get('served_less_than_9years', True) else 0,
            1 if data.get('no_other_directorships', True) else 0
        ])
        
        independence_status = 'INDEPENDENT' if criteria_met else 'NON_INDEPENDENT'
        
        cursor = db.execute('''
            INSERT INTO independence_declarations (
                member_id, declaration_date, declaration_type, declaration_period,
                no_material_interest, no_employment_5years, no_relative_employment,
                no_professional_relationship, no_significant_business,
                no_remuneration_except_fees, no_other_directorships,
                served_less_than_9years, criteria_not_met, explanation,
                independence_status, reviewed_by, review_date,
                next_declaration_due, declaration_document_path
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', (
            data.get('member_id'),
            data.get('declaration_date') or datetime.now().date(),
            data.get('declaration_type', 'ANNUAL'),
            data.get('declaration_period'),
            1 if data.get('no_material_interest', True) else 0,
            1 if data.get('no_employment_5years', True) else 0,
            1 if data.get('no_relative_employment', True) else 0,
            1 if data.get('no_professional_relationship', True) else 0,
            1 if data.get('no_significant_business', True) else 0,
            1 if data.get('no_remuneration_except_fees', True) else 0,
            1 if data.get('no_other_directorships', True) else 0,
            1 if data.get('served_less_than_9years', True) else 0,
            data.get('criteria_not_met'),  # JSON
            data.get('explanation'),
            independence_status,
            data.get('reviewed_by'),
            data.get('review_date'),
            data.get('next_declaration_due'),
            data.get('declaration_document_path')
        ))
        db.commit()
        return cursor.fetchone()['id']
    
    @staticmethod
    def get_by_member(member_id):
        """Get member's independence declarations"""
        db = get_db()
        rows = db.execute('''
            SELECT * FROM independence_declarations 
            WHERE member_id = %s 
            ORDER BY declaration_date DESC
        ''', (member_id,)).fetchall()
        return [IndependenceDeclaration(**dict(row)) for row in rows]
    
    @staticmethod
    def get_latest(member_id):
        """Latest declaration row (id, declaration_date, independence_status) or None."""
        db = get_db()
        return db.execute('''
            SELECT id, declaration_date, independence_status FROM independence_declarations
            WHERE member_id = %s
            ORDER BY declaration_date DESC NULLS LAST, id DESC
            LIMIT 1
        ''', (member_id,)).fetchone()

    @staticmethod
    def get_current_status(member_id):
        """Get member's current independence status"""
        db = get_db()
        row = db.execute('''
            SELECT independence_status FROM independence_declarations 
            WHERE member_id = %s 
            ORDER BY declaration_date DESC 
            LIMIT 1
        ''', (member_id,)).fetchone()
        return row['independence_status'] if row else None

# ============================================================================
# BOARD SKILLS MATRIX
# ============================================================================

class BoardSkillsMatrix:
    """Track board member skills and competencies"""
    
    def __init__(self, id=None, member_id=None, assessment_date=None, **kwargs):
        self.id = id
        self.member_id = member_id
        self.assessment_date = assessment_date
        
        for key, value in kwargs.items():
            setattr(self, key, value)
    
    @staticmethod
    def create(data):
        """Create skills assessment"""
        db = get_db()
        
        # Calculate total skill score
        skill_scores = [
            data.get('financial_expertise', 0),
            data.get('risk_management', 0),
            data.get('compliance_regulatory', 0),
            data.get('technology_digital', 0),
            data.get('strategy_business', 0),
            data.get('human_resources', 0),
            data.get('legal', 0),
            data.get('audit', 0),
            data.get('marketing_sales', 0),
            data.get('operations', 0)
        ]
        
        total_score = sum(skill_scores)
        avg_score = total_score / len(skill_scores) if skill_scores else 0
        
        # Determine skill level
        if avg_score >= 4:
            skill_level = 'EXPERT'
        elif avg_score >= 3:
            skill_level = 'ADVANCED'
        elif avg_score >= 2:
            skill_level = 'INTERMEDIATE'
        else:
            skill_level = 'DEVELOPING'
        
        cursor = db.execute('''
            INSERT INTO board_skills_matrix (
                member_id, assessment_date, assessment_period,
                financial_expertise, risk_management, compliance_regulatory,
                technology_digital, strategy_business, human_resources,
                legal, audit, marketing_sales, operations,
                banking_finance, payments_fintech, technology, retail,
                board_experience, committee_chair_experience,
                crisis_management, stakeholder_management,
                arabic_proficiency, english_proficiency, other_languages,
                has_professional_certifications, certifications_list,
                total_skill_score, skill_level, skill_gaps, development_plan,
                assessed_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', (
            data.get('member_id'),
            data.get('assessment_date') or datetime.now().date(),
            data.get('assessment_period'),
            data.get('financial_expertise', 0),
            data.get('risk_management', 0),
            data.get('compliance_regulatory', 0),
            data.get('technology_digital', 0),
            data.get('strategy_business', 0),
            data.get('human_resources', 0),
            data.get('legal', 0),
            data.get('audit', 0),
            data.get('marketing_sales', 0),
            data.get('operations', 0),
            data.get('banking_finance', 0),
            data.get('payments_fintech', 0),
            data.get('technology', 0),
            data.get('retail', 0),
            data.get('board_experience', 0),
            data.get('committee_chair_experience', 0),
            data.get('crisis_management', 0),
            data.get('stakeholder_management', 0),
            data.get('arabic_proficiency', 0),
            data.get('english_proficiency', 0),
            data.get('other_languages'),
            1 if data.get('has_professional_certifications') else 0,
            data.get('certifications_list'),
            int(total_score),
            skill_level,
            data.get('skill_gaps'),
            data.get('development_plan'),
            data.get('assessed_by')
        ))
        db.commit()
        return cursor.fetchone()['id']
    
    @staticmethod
    def get_board_skills_summary():
        """Get aggregated skills across entire board"""
        db = get_db()
        
        # Get latest assessment for each active member
        query = '''
            SELECT 
                AVG(COALESCE(financial_expertise, 0)) as avg_financial,
                AVG(COALESCE(risk_management, 0)) as avg_risk,
                AVG(COALESCE(compliance_regulatory, 0)) as avg_compliance,
                AVG(COALESCE(technology_digital, 0)) as avg_technology,
                SUM(CASE WHEN financial_expertise >= 4 THEN 1 ELSE 0 END) as expert_financial,
                SUM(CASE WHEN risk_management >= 4 THEN 1 ELSE 0 END) as expert_risk,
                SUM(CASE WHEN compliance_regulatory >= 4 THEN 1 ELSE 0 END) as expert_compliance
            FROM board_members bm
            LEFT JOIN (
                SELECT bsm.*
                FROM board_skills_matrix bsm
                INNER JOIN (
                    SELECT member_id, MAX(assessment_date) as max_date
                    FROM board_skills_matrix
                    GROUP BY member_id
                ) latest ON bsm.member_id = latest.member_id 
                    AND bsm.assessment_date = latest.max_date
            ) latest_bsm ON bm.id = latest_bsm.member_id
            WHERE bm.status = 'ACTIVE'
        '''
        
        row = db.execute(query).fetchone()
        return dict(row) if row else {}
    
    @staticmethod
    def get_by_member(member_id):
        """Get member's skills assessments"""
        db = get_db()
        rows = db.execute('''
            SELECT * FROM board_skills_matrix 
            WHERE member_id = %s 
            ORDER BY assessment_date DESC
        ''', (member_id,)).fetchall()
        return [BoardSkillsMatrix(**dict(row)) for row in rows]

# ============================================================================
# BOARD EVALUATIONS
# ============================================================================

class BoardEvaluation:
    """Board and Committee Performance Evaluations"""
    
    def __init__(self, id=None, evaluation_period=None, evaluation_type=None, **kwargs):
        self.id = id
        self.evaluation_period = evaluation_period
        self.evaluation_type = evaluation_type
        
        for key, value in kwargs.items():
            setattr(self, key, value)
    
    @staticmethod
    def create(data):
        """Create board evaluation"""
        db = get_db()
        
        # Calculate total score
        scores = [
            data.get('strategy_effectiveness', 0),
            data.get('risk_oversight', 0),
            data.get('financial_oversight', 0),
            data.get('compliance_oversight', 0),
            data.get('decision_quality', 0),
            data.get('meeting_effectiveness', 0),
            data.get('board_dynamics', 0),
            data.get('stakeholder_engagement', 0)
        ]
        
        total_score = sum(scores)
        avg_score = total_score / len(scores) if scores else 0
        
        # Determine rating
        if avg_score >= 80:
            overall_rating = 'EXCELLENT'
        elif avg_score >= 70:
            overall_rating = 'GOOD'
        elif avg_score >= 60:
            overall_rating = 'SATISFACTORY'
        else:
            overall_rating = 'NEEDS_IMPROVEMENT'
        
        cursor = db.execute('''
            INSERT INTO board_evaluations (
                evaluation_period, evaluation_type, board_committee_id, member_id,
                methodology, is_external, evaluator,
                strategy_effectiveness_score, risk_oversight_score, financial_oversight_score,
                compliance_oversight_score, decision_quality_score, meeting_effectiveness_score,
                board_dynamics_score, stakeholder_engagement_score,
                individual_contribution_score, individual_expertise_score, individual_commitment_score,
                total_score, overall_rating, strengths, areas_for_improvement,
                recommendations, action_plan, improvement_deadline,
                evaluation_report_path, conducted_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', (
            data.get('evaluation_period'),
            data.get('evaluation_type'),
            data.get('committee_id'),
            data.get('member_id'),
            data.get('methodology'),
            1 if data.get('is_external') else 0,
            data.get('evaluator'),
            data.get('strategy_effectiveness', 0),
            data.get('risk_oversight', 0),
            data.get('financial_oversight', 0),
            data.get('compliance_oversight', 0),
            data.get('decision_quality', 0),
            data.get('meeting_effectiveness', 0),
            data.get('board_dynamics', 0),
            data.get('stakeholder_engagement', 0),
            data.get('individual_contribution', 0),
            data.get('individual_expertise', 0),
            data.get('individual_commitment', 0),
            int(total_score),
            overall_rating,
            data.get('strengths'),
            data.get('areas_for_improvement'),
            data.get('recommendations'),
            data.get('action_plan'),
            data.get('improvement_deadline'),
            data.get('evaluation_report_path'),
            data.get('conducted_by')
        ))
        db.commit()
        return cursor.fetchone()['id']
    
    @staticmethod
    def get_by_period(evaluation_period):
        """Get evaluations for a specific period"""
        db = get_db()
        rows = db.execute('''
            SELECT * FROM board_evaluations 
            WHERE evaluation_period = %s
        ''', (evaluation_period,)).fetchall()
        return [BoardEvaluation(**dict(row)) for row in rows]

# ============================================================================
# SUCCESSION PLANNING
# ============================================================================

class SuccessionPlan:
    """Succession planning for key positions"""
    
    def __init__(self, id=None, position_title=None, position_type=None, **kwargs):
        self.id = id
        self.position_title = position_title
        self.position_type = position_type
        
        for key, value in kwargs.items():
            setattr(self, key, value)
    
    @staticmethod
    def create(data):
        """Create succession plan"""
        db = get_db()
        
        cursor = db.execute('''
            INSERT INTO succession_plans (
                position_title, position_type, current_holder_id,
                succession_risk, critical_position, expected_vacancy_date,
                notice_period_months, internal_candidates, external_search_required,
                interim_successor_id, interim_plan, plan_status,
                last_review_date, next_review_date, plan_document_path
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', (
            data.get('position_title'),
            data.get('position_type'),
            data.get('current_holder_id'),
            data.get('succession_risk', 'MEDIUM'),
            1 if data.get('critical_position') else 0,
            data.get('expected_vacancy_date'),
            data.get('notice_period_months', 3),
            data.get('internal_candidates'),  # JSON
            1 if data.get('external_search_required') else 0,
            data.get('interim_successor_id'),
            data.get('interim_plan'),
            data.get('plan_status', 'ACTIVE'),
            data.get('last_review_date'),
            data.get('next_review_date'),
            data.get('plan_document_path')
        ))
        db.commit()
        return cursor.fetchone()['id']
    
    @staticmethod
    def get_all_active():
        """Get all active succession plans"""
        db = get_db()
        rows = db.execute('''
            SELECT sp.*, bm.member_name as current_holder_name
            FROM succession_plans sp
            LEFT JOIN board_members bm ON sp.current_holder_id = bm.id
            WHERE sp.plan_status = 'ACTIVE'
            ORDER BY 
                CASE sp.succession_risk 
                    WHEN 'HIGH' THEN 1
                    WHEN 'MEDIUM' THEN 2
                    ELSE 3
                END
        ''').fetchall()
        return [SuccessionPlan(**dict(row)) for row in rows]

# ============================================================================
# BOARD TRAINING
# ============================================================================

class BoardTraining:
    """Board training and development tracking"""
    
    def __init__(self, id=None, training_title=None, training_date=None, **kwargs):
        self.id = id
        self.training_title = training_title
        self.training_date = training_date
        
        for key, value in kwargs.items():
            setattr(self, key, value)
    
    @staticmethod
    def create(data):
        """Create training record"""
        db = get_db()
        
        cursor = db.execute('''
            INSERT INTO board_training (
                training_title, training_type, training_date, duration_hours,
                location, delivery_method, provider_name, trainer_name,
                mandatory, target_members, training_objectives,
                training_materials_path, status, created_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', (
            data.get('training_title'),
            data.get('training_type'),
            data.get('training_date'),
            data.get('duration_hours', 0),
            data.get('location'),
            data.get('delivery_method', 'IN_PERSON'),
            data.get('provider_name'),
            data.get('trainer_name'),
            1 if data.get('mandatory') else 0,
            data.get('target_members'),  # JSON
            data.get('training_objectives'),
            data.get('training_materials_path'),
            data.get('status', 'SCHEDULED'),
            data.get('created_by')
        ))
        db.commit()
        return cursor.fetchone()['id']
    
    @staticmethod
    def get_upcoming():
        """Get upcoming training sessions"""
        db = get_db()
        rows = db.execute('''
            SELECT * FROM board_training 
            WHERE training_date::date >= CURRENT_DATE
            AND status IN ('SCHEDULED', 'IN_PROGRESS')
            ORDER BY training_date ASC
        ''').fetchall()
        return [BoardTraining(**dict(row)) for row in rows]
    
    @staticmethod
    def record_attendance(training_id, member_id, data):
        """Record member attendance at training"""
        db = get_db()
        
        db.execute('''
            INSERT INTO board_training_attendance (
                training_id, member_id, attended, attendance_duration,
                completion_status, assessment_score, passed,
                certificate_issued, certificate_path,
                feedback_rating, feedback_comments
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (
            training_id,
            member_id,
            1 if data.get('attended') else 0,
            data.get('attendance_duration'),
            data.get('completion_status', 'COMPLETED'),
            data.get('assessment_score'),
            1 if data.get('passed', True) else 0,
            1 if data.get('certificate_issued') else 0,
            data.get('certificate_path'),
            data.get('feedback_rating'),
            data.get('feedback_comments')
        ))
        db.commit()

# ============================================================================
# GOVERNANCE COMPLIANCE TRACKER
# ============================================================================

class GovernanceCompliance:
    """Track compliance with governance requirements"""

    def __init__(self, id=None, compliance_area=None, requirement_code=None, is_active=True, **kwargs):
        self.id = id
        self.compliance_area = compliance_area
        self.requirement_code = requirement_code
        self.is_active = is_active

        for key, value in kwargs.items():
            setattr(self, key, value)

    @staticmethod
    def get_all(include_inactive=False):
        """Get all compliance requirements, joined to their regulator if linked"""
        db = get_db()
        where = '' if include_inactive else 'WHERE t.is_active = 1'
        rows = db.execute(f'''
            SELECT t.*, reg.regulator_name
            FROM governance_compliance_tracker t
            LEFT JOIN regulators reg ON t.regulator_id = reg.id
            {where}
            ORDER BY
                CASE t.compliance_status
                    WHEN 'NON_COMPLIANT' THEN 1
                    WHEN 'PARTIAL' THEN 2
                    WHEN 'IN_PROGRESS' THEN 3
                    WHEN 'COMPLIANT' THEN 4
                    ELSE 5
                END,
                t.due_date ASC
        ''').fetchall()
        return [GovernanceCompliance(**dict(row)) for row in rows]

    @staticmethod
    def get_by_id(requirement_id):
        """Get a single compliance requirement by ID"""
        db = get_db()
        row = db.execute('''
            SELECT t.*, reg.regulator_name
            FROM governance_compliance_tracker t
            LEFT JOIN regulators reg ON t.regulator_id = reg.id
            WHERE t.id = %s
        ''', (requirement_id,)).fetchone()
        if row:
            return GovernanceCompliance(**dict(row))
        return None

    @staticmethod
    def get_by_status(status):
        """Get requirements by compliance status"""
        db = get_db()
        rows = db.execute('''
            SELECT * FROM governance_compliance_tracker
            WHERE compliance_status = %s
        ''', (status,)).fetchall()
        return [GovernanceCompliance(**dict(row)) for row in rows]

    @staticmethod
    def create(data):
        """Add a new compliance requirement to track — lets an admin extend the
        tracker for a new/foreign regulator without needing a DB script."""
        db = get_db()
        cursor = db.cursor()
        cursor.execute('''
            INSERT INTO governance_compliance_tracker (
                requirement_code, requirement_description, compliance_area,
                regulatory_source, regulator_id, compliance_status, due_date, is_active
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, 1)
            RETURNING id
        ''', (
            data.get('requirement_code'),
            data.get('requirement_description'),
            data.get('compliance_area'),
            data.get('regulatory_source'),
            data.get('regulator_id') or None,
            data.get('compliance_status', 'NON_COMPLIANT'),
            data.get('due_date') or None
        ))
        db.commit()
        return cursor.fetchone()['id']

    @staticmethod
    def update_status(requirement_id, status, evidence=None, notes=None):
        """Update compliance status and notes"""
        db = get_db()

        db.execute('''
            UPDATE governance_compliance_tracker
            SET compliance_status = %s,
                evidence_description = %s,
                notes = %s,
                completion_date = CASE WHEN %s = 'COMPLIANT' THEN CURRENT_DATE ELSE completion_date END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        ''', (status, evidence, notes, status, requirement_id))
        db.commit()

    @staticmethod
    def set_active(requirement_id, is_active):
        """Retire (or restore) a requirement without losing its history"""
        db = get_db()
        db.execute('''
            UPDATE governance_compliance_tracker
            SET is_active = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        ''', (1 if is_active else 0, requirement_id))
        db.commit()

# ============================================================================
# MEETING AGENDA ITEMS
# ============================================================================

class MeetingAgendaItem:
    """Meeting agenda items"""
    
    def __init__(self, id=None, meeting_id=None, item_title=None, **kwargs):
        self.id = id
        self.meeting_id = meeting_id
        self.item_title = item_title
        
        for key, value in kwargs.items():
            setattr(self, key, value)
    
    @staticmethod
    def create(data):
        """Create agenda item"""
        db = get_db()
        
        cursor = db.execute('''
            INSERT INTO meeting_agenda_items (
                meeting_id, item_number, item_title, item_description,
                item_type, estimated_duration, background_paper_path,
                presentation_path, presenter_name, presenter_member_id,
                display_order
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', (
            data.get('meeting_id'),
            data.get('item_number'),
            data.get('item_title'),
            data.get('item_description'),
            data.get('item_type', 'DISCUSSION'),
            data.get('estimated_duration', 15),
            data.get('background_paper_path'),
            data.get('presentation_path'),
            data.get('presenter_name'),
            data.get('presenter_member_id'),
            data.get('display_order')
        ))
        db.commit()
        return cursor.fetchone()['id']
    
    @staticmethod
    def get_by_meeting(meeting_id):
        """Get all agenda items for a meeting"""
        db = get_db()
        rows = db.execute('''
            SELECT * FROM meeting_agenda_items
            WHERE meeting_id = %s
            ORDER BY display_order, item_number
        ''', (meeting_id,)).fetchall()
        return [MeetingAgendaItem(**dict(row)) for row in rows]

# ============================================================================
# MEETING ACTION ITEMS
# ============================================================================

class MeetingActionItem:
    """Action items from meetings"""
    
    def __init__(self, id=None, meeting_id=None, action_description=None, **kwargs):
        self.id = id
        self.meeting_id = meeting_id
        self.action_description = action_description
        
        for key, value in kwargs.items():
            setattr(self, key, value)
    
    @staticmethod
    def create(data):
        """Create action item"""
        db = get_db()
        
        cursor = db.execute('''
            INSERT INTO meeting_action_items (
                meeting_id, agenda_item_id, action_number, action_description,
                action_category, responsible_person, responsible_department,
                responsible_committee_id, due_date, priority, status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', (
            data.get('meeting_id'),
            data.get('agenda_item_id'),
            data.get('action_number'),
            data.get('action_description'),
            data.get('action_category', 'OPERATIONAL'),
            data.get('responsible_person'),
            data.get('responsible_department'),
            data.get('responsible_committee_id'),
            data.get('due_date'),
            data.get('priority', 'MEDIUM'),
            'PENDING'
        ))
        db.commit()
        return cursor.fetchone()['id']
    
    @staticmethod
    def get_open_actions():
        """Get all open action items"""
        db = get_db()
        rows = db.execute('''
            SELECT mai.*, bm.meeting_reference, bm.meeting_date
            FROM meeting_action_items mai
            INNER JOIN board_meetings bm ON mai.meeting_id = bm.id
            WHERE mai.status IN ('PENDING', 'IN_PROGRESS', 'DELAYED')
            ORDER BY mai.due_date ASC
        ''').fetchall()
        return [MeetingActionItem(**dict(row)) for row in rows]
    
    @staticmethod
    def get_overdue_actions():
        """Get overdue action items"""
        db = get_db()
        rows = db.execute('''
            SELECT * FROM meeting_action_items
            WHERE status IN ('PENDING', 'IN_PROGRESS')
            AND due_date < CURRENT_DATE
            ORDER BY due_date ASC
        ''').fetchall()
        return [MeetingActionItem(**dict(row)) for row in rows]
