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
Display labels (EN/AR via Babel) for the status / category codes used by the
case registry and its source modules: whistleblowing, consumer complaints,
cyber incidents and data protection. Templates use ``{{ code|code_label }}``;
an unknown code falls back to a readable form of the code itself.
"""

from flask_babel import lazy_gettext as _l

LABELS = {
    # unified case statuses / types / priorities
    'OPEN': _l('Open'), 'IN_PROGRESS': _l('In progress'), 'RESOLVED': _l('Resolved'), 'CLOSED': _l('Closed'),
    'TM_ALERT': _l('Transaction monitoring alert'), 'WHISTLEBLOWING': _l('Whistleblowing report'),
    'CONSUMER_COMPLAINT': _l('Consumer complaint'), 'CYBER_INCIDENT': _l('Cyber incident'),
    'DSR': _l('Data subject request'), 'DATA_BREACH': _l('Personal data breach'),
    'REG_CONTROL': _l('Control failure'), 'UNUSUAL_TXN': _l('Unusual transaction'),
    'LOW': _l('Low'), 'MEDIUM': _l('Medium'), 'HIGH': _l('High'), 'CRITICAL': _l('Critical'),
    'NORMAL': _l('Normal'),
    # whistleblowing
    'SUBMITTED': _l('Submitted'), 'UNDER_REVIEW': _l('Under review'), 'INVESTIGATING': _l('Investigating'),
    'ESCALATED': _l('Escalated'), 'DISMISSED': _l('Dismissed'),
    'STATUS_CHANGE': _l('Status change'), 'ASSIGNMENT': _l('Assignment'), 'RESOLUTION': _l('Resolution'),
    'COMMENT': _l('Comment'), 'MESSAGE': _l('Message'),
    # complaints
    'NEW': _l('New'),
    'PUBLIC_FORM': _l('Online form'), 'BRANCH': _l('Branch'), 'PHONE': _l('Phone'), 'EMAIL': _l('Email'),
    'MOBILE_APP': _l('Mobile app'), 'WEBSITE': _l('Website'), 'SOCIAL_MEDIA': _l('Social media'),
    'LETTER': _l('Letter'), 'REGULATOR_REFERRAL': _l('Referred by regulator'), 'CALL_CENTER': _l('Call centre'),
    'PROCESS_FAILURE': _l('Process failure'), 'STAFF_ERROR': _l('Staff error'),
    'SYSTEM_ERROR': _l('System / technical error'), 'PRODUCT_DESIGN': _l('Product design'),
    'THIRD_PARTY': _l('Third party / outsourced provider'), 'MISCOMMUNICATION': _l('Miscommunication / disclosure'),
    'FRAUD': _l('Fraud'), 'CUSTOMER_MISUNDERSTANDING': _l('Customer misunderstanding'),
    'NO_FAULT': _l('No fault found'), 'OTHER': _l('Other'),
    'NONE': _l('None'), 'REFUND': _l('Refund'), 'FEE_WAIVER': _l('Fee waiver / reversal'),
    'COMPENSATION': _l('Compensation'), 'CORRECTION': _l('Record / account correction'),
    'APOLOGY': _l('Apology / explanation'), 'SERVICE_RESTORED': _l('Service restored'),
    # cyber
    'CONTAINED': _l('Contained'),
    # data protection
    'COMPLETED': _l('Completed'), 'REJECTED': _l('Rejected'), 'OVERDUE': _l('Overdue'),
    'REMEDIATING': _l('Remediating'),
    'ACCESS': _l('Access'), 'RECTIFICATION': _l('Rectification'), 'ERASURE': _l('Erasure'),
    'RESTRICTION': _l('Restriction of processing'), 'PORTABILITY': _l('Data portability'),
    'OBJECTION': _l('Objection'),
    'ID_CARD': _l('National ID card'), 'PASSPORT': _l('Passport'), 'EMAIL_TOKEN': _l('Email verification'),
    'IN_PERSON': _l('In person'), 'SMS_OTP': _l('SMS one-time code'), 'KYC_RECORD': _l('Match to KYC record'),
    'GIVEN': _l('Given'), 'WITHDRAWN': _l('Withdrawn'), 'ACTIVE': _l('Active'),
    'CONSENT': _l('Consent'), 'CONTRACT': _l('Contract'), 'LEGAL_OBLIGATION': _l('Legal obligation'),
    'VITAL_INTERESTS': _l('Vital interests'), 'PUBLIC_INTEREST': _l('Public interest'),
    'LEGITIMATE_INTERESTS': _l('Legitimate interests'),
    'PAPER_FORM': _l('Paper form'), 'RECORDED_CALL': _l('Recorded call'), 'IN_APP': _l('In-app'),
    'HOTLINE': _l('Hotline'), 'FRA_REFERRAL': _l('Referred by regulator'), 'UNSPECIFIED': _l('Not specified'),
    'SUBMISSION': _l('Submission'), 'INTERNAL_NOTE': _l('Internal note'), 'NOTE': _l('Note'),
    'RESOLUTION_DETAILS': _l('Root cause / redress'), 'SYSTEM_ESCALATION': _l('Automatic escalation'),
    # incident / breach types
    'DDOS': _l('Denial of service (DDoS)'), 'MALWARE': _l('Malware'), 'PHISHING': _l('Phishing'),
    'RANSOMWARE': _l('Ransomware'), 'SYSTEM_OUTAGE': _l('System outage'),
    'UNAUTHORIZED_ACCESS': _l('Unauthorised access'), 'ACCIDENTAL_DISCLOSURE': _l('Accidental disclosure'),
    'DATA_THEFT': _l('Data theft'), 'HACKING': _l('Hacking'), 'LOSS_OF_DEVICE': _l('Loss of device'),
    'DRAFT': _l('Draft'), 'PENDING_APPROVAL': _l('Pending approval'), 'APPROVED': _l('Approved'),
    'VERY_HIGH': _l('Very high'),
    'RECEIVED': _l('Received'), 'IDENTITY_VERIFIED': _l('Identity verified'), 'ASSIGNED': _l('Assigned'),
    'SMS': _l('SMS'), 'PUBLIC_NOTICE': _l('Public notice'),
    # whistleblowing report types
    'CORRUPTION': _l('Corruption & bribery'), 'HARASSMENT': _l('Harassment & discrimination'),
    'SAFETY': _l('Health & safety'), 'REGULATORY': _l('Regulatory violation'), 'RETALIATION': _l('Retaliation'),
    'CONFLICT_INTEREST': _l('Conflict of interest'), 'MISUSE_ASSETS': _l('Misuse of company assets'),
    'UNETHICAL': _l('Unethical behaviour'), 'AML_VIOLATION': _l('AML/CFT violation'),
}


def label(code):
    if code is None or code == '':
        return '-'
    key = str(code).strip()
    found = LABELS.get(key) or LABELS.get(key.upper())
    if found is not None:
        return str(found)
    return key.replace('_', ' ').title()
