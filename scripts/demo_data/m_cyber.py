"""Cyber: incidents (+response team, timelines), resilience complements (assets, backups, integrations,
assessments, maturity history, BCP site) and four phishing-simulation campaigns showing improvement."""
import json
from datetime import timedelta


def _ts(d):
    return d.strftime('%Y-%m-%d %H:%M:%S')


# days ago, type, severity, status, systems, users, description, vector, root cause, containment, eradication,
# recovery, lessons, preventive, regulator-notified
INCIDENTS = [
    (342, 'PHISHING', 'MEDIUM', 'CLOSED', 'E-mail', 35,
     'Credential-harvesting e-mail impersonating the IT helpdesk ("mailbox quota exceeded") received by 35 staff; 4 entered passwords.',
     'E-mail link to fake login page', 'Users not trained to verify sender domain; MFA not yet enabled for e-mail.',
     'Malicious URL blocked at proxy; 4 passwords reset', 'Phishing e-mails purged from mailboxes', 'Normal service',
     'Start a quarterly phishing simulation programme.', 'Phishing awareness training; MFA roadmap approved.', False),
    (301, 'MALWARE', 'LOW', 'CLOSED', 'Branch PC - Assiut', 1,
     'EDR detected a trojan on a loan officer PC after a personal USB stick was connected.',
     'Infected USB stick', 'USB storage allowed on branch PCs.', 'PC isolated by EDR', 'PC re-imaged',
     'PC returned to user after scan', 'USB control policy needed.', 'USB storage blocked on all branch PCs.', False),
    (268, 'DDOS', 'HIGH', 'CLOSED', 'Customer portal / mobile API', 0,
     'Volumetric DDoS against the customer portal for 3 hours; mobile app repayments unavailable.',
     'UDP flood from botnet', 'No upstream DDoS scrubbing contract.', 'ISP null-routing and WAF rate limits',
     'Upstream scrubbing service activated', 'Services restored after 3h 10m', 'Need an always-on DDoS service.',
     'DDoS protection contract signed with ISP.', True),
    (233, 'UNAUTHORIZED_ACCESS', 'MEDIUM', 'CLOSED', 'VPN gateway', 0,
     'Brute-force attempts on the VPN gateway from foreign IPs; one dormant account locked out.',
     'Password spraying', 'Dormant accounts not disabled; geo-blocking absent.', 'Source IPs blocked; account disabled',
     'Dormant accounts review (17 disabled)', 'No impact', 'Joiner-mover-leaver process gap.',
     'Geo-blocking and MFA on VPN.', False),
    (190, 'SYSTEM_OUTAGE', 'HIGH', 'CLOSED', 'Core lending system', 0,
     'Core lending database ran out of storage at month-end; branches could not disburse for 5 hours.',
     'Capacity', 'Storage monitoring threshold misconfigured.', 'Archive logs moved, storage extended',
     'Monitoring thresholds corrected', 'Service restored after 5h', 'Capacity reviews monthly.',
     'Automated capacity alerting.', True),
    (151, 'RANSOMWARE', 'CRITICAL', 'CLOSED', 'File server (head office)', 0,
     'Ransomware executable delivered by e-mail attachment was blocked by EDR before encryption started on the file server.',
     'Malicious ISO attachment', 'Mail gateway allowed ISO attachments.', 'Host isolated in 4 minutes; hash blocked',
     'Attachment type blocked; IOC sweep across all hosts', 'No data loss', 'Attachment filtering policy outdated.',
     'Block executable/ISO attachments; tabletop exercise held.', True),
    (88, 'DATA_BREACH', 'HIGH', 'IN_PROGRESS', 'Collection dialler (agency access)', 1840,
     'Overdue-customer list exported by a collection-agency employee to a USB stick (see data breach BRC-202607-1C7E).',
     'Insider - third party', 'Agency workstations allowed USB storage and bulk export.', 'Agency access suspended; USB recovered',
     'USB blocking on agency workstations', None, None, 'Agency audit and DPA amendment.', True),
    (33, 'PHISHING', 'MEDIUM', 'RESOLVED', 'Cloud e-mail', 1,
     'Head-office mailbox accessed from abroad after the user entered credentials on a fake login page (data breach BRC-202609-2B19).',
     'Adversary-in-the-middle phishing page', 'MFA not enforced for the last migrated mailbox group.',
     'Sessions revoked, password reset', 'MFA enforced for all users', 'Mailbox restored', 'Finish MFA before migration.',
     'Conditional access policy.', False),
    (12, 'MALWARE', 'MEDIUM', 'IN_PROGRESS', 'Giza branch network', 3,
     'Cryptominer detected on three Giza branch PCs; investigation of the infection path in progress.',
     'Under investigation', None, 'PCs isolated', None, None, None, None, False),
    (1, 'UNAUTHORIZED_ACCESS', 'HIGH', 'NEW', 'Mobile app API', 0,
     'Spike of failed logins on the mobile app API (credential stuffing suspected) flagged by the SIEM this morning.',
     'Credential stuffing (suspected)', None, None, None, None, None, None, False),
]

TEAM = [('it', 'Incident Commander'), ('itsup', 'Technical Lead'), ('co', 'Compliance Liaison'),
        ('dpo', 'Privacy Advisor'), ('cs', 'Customer Communications')]


def _incidents(ctx):
    rnd, U = ctx.rnd, ctx.uid
    ids = []
    yr_n = {}
    for (d, typ, sev, st, systems, users, desc, vector, root, cont, erad, rec, lessons, prev, notify) in INCIDENTS:
        disc = ctx.ago(d, rnd.randint(8, 18))
        occurred = disc - timedelta(hours=rnd.randint(1, 30))
        yr_n[disc.year] = yr_n.get(disc.year, 0) + 1
        num = f"INC-{disc:%Y%m%d}-{0xA10 + len(ids) * 0x1D:04X}"
        crit = sev in ('HIGH', 'CRITICAL')
        t_cont = disc + timedelta(hours=rnd.randint(1, 6)) if cont else None
        t_erad = disc + timedelta(days=rnd.randint(1, 4)) if erad else None
        t_rec = disc + timedelta(days=rnd.randint(2, 6)) if rec else None
        closed = disc + timedelta(days=rnd.randint(14, 30)) if st == 'CLOSED' else None
        reporter = {'PHISHING': 'Staff report to IT helpdesk', 'MALWARE': 'EDR alert', 'DDOS': 'NOC monitoring',
                    'UNAUTHORIZED_ACCESS': 'SIEM alert', 'SYSTEM_OUTAGE': 'Branch helpdesk calls',
                    'RANSOMWARE': 'EDR alert', 'DATA_BREACH': 'Whistleblowing report'}[typ]
        iid = ctx.ins('cyber_incidents', incident_number=num, incident_date=_ts(occurred), discovery_date=_ts(disc),
                      reported_by=reporter, incident_type=typ, incident_description=desc, affected_systems=systems,
                      affected_users_count=users, severity=sev, cbe_notification_required=1 if crit else 0,
                      cbe_notification_deadline=_ts(disc + timedelta(hours=24)) if crit else None,
                      cbe_notified=1 if notify else 0,
                      cbe_notification_date=_ts(disc + timedelta(hours=rnd.randint(5, 20))) if notify else None,
                      cbe_reference=f'FRA-CYB-DEMO-{disc:%y}{len(ids) + 11:03d}' if notify else None,
                      containment_actions=cont, containment_date=_ts(t_cont) if t_cont else None,
                      eradication_actions=erad, eradication_date=_ts(t_erad) if t_erad else None,
                      recovery_actions=rec, recovery_date=_ts(t_rec) if t_rec else None, root_cause=root,
                      attack_vector=vector, indicators_of_compromise='IOC list kept in the SIEM case' if st != 'NEW' else None,
                      lessons_learned=lessons, preventive_measures=prev, status=st, created_at=_ts(disc),
                      created_by=U('itsup'), closed_date=_ts(closed) if closed else None,
                      closed_by=U('it') if closed else None)
        ids.append(iid)
        ctx.ins('cybersecurity_incidents', incident_reference=num, detection_date=_ts(disc), detection_method=reporter,
                detected_by=ctx.name('itsup'), incident_type=typ, severity=sev,
                classification_date=_ts(disc + timedelta(hours=1)), classified_by=U('it'), incident_description=desc,
                affected_systems=systems, affected_data='Customer personal data' if typ == 'DATA_BREACH' else None,
                estimated_impact={'CRITICAL': 'Severe (prevented)', 'HIGH': 'Service disruption', 'MEDIUM': 'Limited',
                                  'LOW': 'Minimal'}[sev],
                containment_actions=cont, containment_completed=1 if t_cont else 0,
                containment_date=_ts(t_cont) if t_cont else None, cbe_notification_required=1 if crit else 0,
                cbe_notification_deadline=_ts(disc + timedelta(hours=24)) if crit else None,
                cbe_notified=1 if notify else 0,
                cbe_notification_date=_ts(disc + timedelta(hours=12)) if notify else None,
                cbe_reference_number=f'FRA-CYB-DEMO-{disc:%y}{len(ids) + 10:03d}' if notify else None,
                cbe_detailed_report_sent=1 if notify and st == 'CLOSED' else 0,
                cbe_detailed_report_date=_ts(disc + timedelta(days=7)) if notify and st == 'CLOSED' else None,
                eradication_actions=erad, eradication_completed=1 if t_erad else 0,
                eradication_date=_ts(t_erad) if t_erad else None, recovery_actions=rec,
                recovery_completed=1 if t_rec else 0, recovery_date=_ts(t_rec) if t_rec else None,
                systems_restored=1 if t_rec else 0, root_cause=root, lessons_learned=lessons,
                preventive_measures=prev, policies_updated=1 if st == 'CLOSED' and prev else 0,
                board_notified=1 if sev == 'CRITICAL' or (crit and st == 'CLOSED') else 0,
                board_notification_date=_ts(disc + timedelta(days=10)) if crit and st == 'CLOSED' else None,
                status=st, closed_date=_ts(closed) if closed else None, assigned_to=U('it'),
                ciso_notified=1, ciso_notification_date=_ts(disc + timedelta(minutes=30)),
                created_at=_ts(disc), updated_at=_ts(closed or t_rec or t_cont or disc))
        # response team
        team = TEAM[:2] + ([TEAM[2]] if crit else []) + ([TEAM[3]] if typ in ('DATA_BREACH', 'PHISHING') else []) + \
            ([TEAM[4]] if typ in ('DDOS', 'SYSTEM_OUTAGE', 'DATA_BREACH') else [])
        for key, role in team:
            ctx.ins('incident_response_team', incident_id=iid, user_id=U(key), role=role,
                    assigned_date=_ts(disc + timedelta(minutes=rnd.randint(10, 90))))
        # timeline
        ev = [(disc, 'DETECTION', f'Detected via {reporter.lower()}', 'Ticket opened, severity triage', 'itsup'),
              (disc + timedelta(minutes=40), 'CLASSIFICATION', f'Classified as {sev}', 'Incident team activated', 'it')]
        if crit:
            ev.append((disc + timedelta(hours=2), 'ESCALATION', 'Escalated to CEO and Compliance', 'Regulatory clock started', 'it'))
        if notify:
            ev.append((disc + timedelta(hours=rnd.randint(5, 20)), 'REGULATOR_NOTIFICATION',
                       'Initial notification sent to the regulator', 'Reference received', 'co'))
        if t_cont:
            ev.append((t_cont, 'CONTAINMENT', 'Threat contained', cont, 'itsup'))
        if t_erad:
            ev.append((t_erad, 'ERADICATION', 'Root cause removed', erad, 'itsup'))
        if t_rec:
            ev.append((t_rec, 'RECOVERY', 'Services recovered', rec, 'it'))
        if closed:
            ev.append((closed, 'POST_INCIDENT_REVIEW', 'Lessons-learned review held', lessons, 'it'))
        for at, et, edesc, act, by in sorted(ev, key=lambda x: x[0]):
            if at <= ctx.now:
                ctx.ins('incident_timeline', incident_id=iid, event_date=_ts(at), event_type=et,
                        event_description=edesc, action_taken=act, recorded_by=U(by))
    return ids


def _resilience(ctx):
    rnd, U = ctx.rnd, ctx.uid
    # extra BCP site (cloud backup vault) - DR tests left as the base has them (they drive the FRA IT controls)
    ctx.ins('cy_bcp_sites', name='Cloud backup vault (demo)', site_type='cloud', location='In-country cloud region (demo)',
            provider='Example Cloud Egypt (demo)', rto_hours=24, rpo_hours=24, is_active=True,
            note='Immutable copies of core lending and accounting backups', created_by=U('it'),
            created_at=ctx.ago(240, 10))
    # security tools & licences
    for t, prod, vendor, ref, exp, note in [
        ('siem', 'Example SIEM (demo)', 'Example Vendor', 'SIEM-DEMO-7', 210, '24x7 monitoring by MSSP (demo)'),
        ('firewall', 'Example NGFW cluster (demo)', 'Example Vendor', 'FW-DEMO-2', 400, 'Head office + 3 branches'),
        ('email_security', 'Example Mail Gateway (demo)', 'Example Vendor', 'MAIL-DEMO-4', 160, 'Attachment sandboxing'),
        ('mfa', 'Example MFA (demo)', 'Example Vendor', 'MFA-DEMO-1', 300, 'E-mail, VPN, core lending admin'),
        ('pam', 'Example PAM (demo)', 'Example Vendor', 'PAM-DEMO-3', 95, 'Privileged accounts vault'),
        ('vuln_scanner', 'Example Vulnerability Scanner (demo)', 'Example Vendor', 'VS-DEMO-5', 130, 'Monthly scans'),
        ('backup', 'Example Backup Suite (demo)', 'Example Vendor', 'BK-DEMO-8', 250, 'Core lending, accounting, archive'),
    ]:
        ctx.ins('cy_security_assets', asset_type=t, product=prod, vendor=vendor, licence_ref=ref,
                licence_expiry=ctx.today + timedelta(days=exp), coverage_note=note, is_active=True,
                sends_data_abroad=False, data_location='Egypt', residency_attested_on=ctx.dago(rnd.randint(30, 200)),
                residency_attested_by='Vendor letter', updated_by=U('it'), updated_at=ctx.ago(rnd.randint(5, 90), 11))
    # backups
    for name, bt, lt, det, hrs, st, msg, rt in [
        ('E-mail archive (demo)', 'incremental', 'cloud', 'Cloud backup vault', 6, 'success', None, 95),
        ('HR & payroll system (demo)', 'full', 'offsite', 'DR site', 20, 'success', None, 140),
        ('Mobile app database (demo)', 'replication', 'offsite', 'DR site (async replica)', 1, 'success', None, 60),
        ('ComplyNex database (demo)', 'snapshot', 'cloud', 'Cloud backup vault', 10, 'partial',
         '1 of 12 tablespaces skipped; retried successfully next run', 120),
    ]:
        ctx.ins('cy_backups', system_name=name, backup_type=bt, location_type=lt, location_detail=det, encrypted=True,
                last_success_at=ctx.now - timedelta(hours=hrs), last_status=st, last_message=msg,
                last_restore_test=ctx.dago(rt), is_active=True, source='api' if bt != 'full' else 'manual',
                updated_at=ctx.now - timedelta(hours=hrs))
    # integrations
    for code, name, cp, purpose, it, st, hrs in [
        ('credit_bureau', 'Credit bureau inquiry & monthly file (demo)', 'Credit bureau (demo)',
         'Inquiry before approval; monthly repayment file', 'api', 'live', 3),
        ('payment_aggregator', 'Bill-payment aggregator repayments (demo)', 'Payment aggregator (demo)',
         'Daily repayment settlement file', 'sftp', 'live', 9),
        ('fra_reporting_portal', 'FRA regulatory reporting portal', 'Financial Regulatory Authority (FRA)',
         'Monthly prudential and statistical returns', 'portal', 'live', 20),
        ('ewallet_collections', 'E-wallet collections (pilot, demo)', 'Mobile wallet provider (demo)',
         'Instalment collection from mobile wallets', 'api', 'testing', None),
    ]:
        ctx.ins('cy_integrations', code=code, name=name, counterparty=cp, purpose=purpose, integration_type=it,
                status=st, last_success_at=ctx.now - timedelta(hours=hrs) if hrs else None,
                last_checked_at=ctx.now - timedelta(hours=hrs or 2), note='UAT with provider until next month' if not hrs else None,
                updated_by=U('it'), updated_at=ctx.now - timedelta(hours=hrs or 30))
    # assessments: quarterly vulnerability scans trending down + app pentest
    for d, crit, high in [(330, 2, 14), (240, 1, 9), (150, 0, 6), (60, 0, 3)]:
        on = ctx.dago(d)
        ctx.ins('cy_assessments', assessment_type='vulnerability_scan', title=f'Quarterly vulnerability scan {on:%b %Y}',
                provider='Internal IT (scanner)', performed_on=on, valid_until=on + timedelta(days=100),
                scope='All servers, firewalls and branch endpoints', critical_open=crit, high_open=high,
                status='accepted', accepted_by=U('it'), accepted_at=ctx.ago(d - 5, 12), created_by=U('itsup'),
                created_at=ctx.ago(d, 15))
    on = ctx.dago(118)
    ctx.ins('cy_assessments', assessment_type='app_pentest', title='Mobile app & API penetration test',
            provider='Example AppSec Partners (demo)', provider_qualification='OSCP / CREST (demo)', performed_on=on,
            valid_until=on + timedelta(days=365), scope='Android/iOS app and repayment API', critical_open=0, high_open=1,
            status='accepted', accepted_by=U('it'), accepted_at=ctx.ago(100, 12), created_by=U('it'),
            created_at=ctx.ago(118, 10))
    on = ctx.dago(4)
    ctx.ins('cy_assessments', assessment_type='phishing_simulation', title='Phishing simulation Q3 2026 - results',
            provider='Internal IT', performed_on=on, valid_until=on + timedelta(days=120),
            scope='All staff with e-mail', critical_open=0, high_open=0, status='draft', created_by=U('itsup'),
            created_at=ctx.ago(4, 14))
    # maturity history (same IT-governance framework as the base assessment) -> trend
    fw = ctx.one("SELECT framework_id FROM cy_maturity_assessments ORDER BY id LIMIT 1")
    if fw:
        base = {r['requirement_id']: r for r in ctx.q("SELECT * FROM cy_maturity_scores WHERE assessment_id = "
                                                     "(SELECT min(id) FROM cy_maturity_assessments)")}
        for d, title, drop in [(335, 'IT self-assessment 2025 (baseline)', 1), (170, 'IT self-assessment mid-2026', 0.5)]:
            aid = ctx.ins('cy_maturity_assessments', framework_id=fw['framework_id'], title=title,
                          assessed_on=ctx.dago(d), status='final', created_by=U('it'), created_at=ctx.ago(d, 10))
            for rid, s in base.items():
                cur = s['current_level'] or 2
                lvl = max(1, cur - (1 if drop == 1 or (drop == 0.5 and rnd.random() < 0.5) else 0))
                ctx.ins('cy_maturity_scores', assessment_id=aid, requirement_id=rid, current_level=lvl,
                        target_level=s['target_level'] or 3, note='Baseline' if drop == 1 else 'Mid-year review')


STAFF_FIRST = ['Mohamed', 'Ahmed', 'Mahmoud', 'Mostafa', 'Karim', 'Hossam', 'Tamer', 'Sherif', 'Islam', 'Amr', 'Bassem',
               'Walid', 'Ehab', 'Hesham', 'Ramy', 'Nermeen', 'Sara', 'Aya', 'Nourhan', 'Marwa', 'Reham', 'Yara', 'Heba',
               'Mai', 'Engy', 'Ghada', 'Radwa', 'Noha', 'Dalia', 'Hagar']
STAFF_LAST = ['Abdelrahman', 'Saber', 'Mekky', 'Sobhy', 'Galal', 'Shawky', 'Morsy', 'Hafez', 'Anwar', 'Badawy',
              'Selim', 'Fekry', 'Lotfy', 'Wahba', 'Eid', 'Hamza', 'Okasha', 'Zayed']


def _phishing(ctx):
    rnd, U = ctx.rnd, ctx.uid
    from phishing.routes import generate_coupon_design, generate_delivery_design
    for key, lvl in {'admin': 'edit', 'it': 'edit', 'itsup': 'edit', 'mlro': 'view', 'co': 'view', 'hr': 'view',
                     'ceo': 'view', 'audit': 'view'}.items():
        ctx.q("UPDATE users SET perm_phishing = %s WHERE id = %s", (lvl, U(key)))
    staff = [(f"{u['first_name']} {u['last_name']}", u['email'])
             for u in ctx.q("SELECT first_name, last_name, email FROM users WHERE email LIKE %s AND email NOT LIKE 'demo.admin%%' "
                            "ORDER BY id", ('%@nilemicro.example',))]
    seen = {e for _, e in staff}
    while len(staff) < 74:
        f, l = rnd.choice(STAFF_FIRST), rnd.choice(STAFF_LAST)
        e = f"{f.lower()}.{l.lower()}@nilemicro.example"
        if e not in seen:
            seen.add(e)
            staff.append((f"{f} {l}", e))

    def custom(brand, color, headline, body, cta):
        return f"""<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f0f0f0;font-family:Arial,sans-serif;direction:rtl;">
<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:24px 12px;">
<table width="600" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:10px;max-width:600px;">
<tr><td style="background:{color};padding:18px 28px;color:#fff;font-size:20px;font-weight:bold;">{brand}</td></tr>
<tr><td style="padding:28px;text-align:right;"><h2 style="margin:0 0 12px;color:#222;">{headline}</h2>
<p style="color:#444;font-size:15px;line-height:1.8;">مرحباً {{{{RECIPIENT_NAME}}}}، {body}</p></td></tr>
<tr><td style="padding:0 28px 28px;text-align:center;"><a href="{{{{TRACKING_URL}}}}" style="background:{color};color:#fff;
padding:13px 44px;border-radius:6px;text-decoration:none;font-weight:bold;">{cta}</a></td></tr></table></td></tr></table></body></html>"""

    e1, l1 = generate_coupon_design('Nile Rewards Club (demo)', None, '#1f7a4d', '300 EGP', 'حتى 15 ديسمبر 2025',
                                    'استلم القسيمة ←')
    e2, l2 = generate_delivery_design('Example Express (demo)', None, '#c0392b', 'EXP-DEMO-48213',
                                      'خلال 48 ساعة', 'تأكيد عنوان التسليم ←')
    e3 = custom('IT Helpdesk', '#34495e', 'صندوق البريد ممتلئ', 'تجاوز صندوق بريدك المساحة المسموح بها وسيتم إيقاف '
                'استقبال الرسائل خلال 24 ساعة. يرجى التحقق من حسابك.', 'التحقق من الحساب')
    e4 = custom('HR - Payroll', '#8e44ad', 'خطاب المكافأة السنوية 2026', 'تم إصدار خطاب المكافأة الخاص بك. يرجى '
                'تسجيل الدخول للاطلاع عليه قبل نهاية الأسبوع.', 'عرض الخطاب')
    campaigns = [  # days ago, name, scenario, subject, sender, html, landing, click rate, submit share of clicks
        (330, 'Q4-2025 baseline - shopping voucher', 'coupon', 'قسيمة شراء مجانية بمناسبة نهاية العام',
         'Nile Rewards Club (demo)', e1, l1, 0.39, 0.58),
        (238, 'Q1-2026 - courier delivery notice', 'delivery', 'شحنتك في الطريق - تأكيد العنوان',
         'Example Express (demo)', e2, l2, 0.27, 0.50),
        (147, 'Q2-2026 - IT mailbox quota', 'it_notice', 'تنبيه: صندوق البريد ممتلئ', 'IT Helpdesk', e3, None, 0.18, 0.42),
        (40, 'Q3-2026 - HR bonus letter', 'hr_notice', 'خطاب المكافأة السنوية 2026', 'HR - Payroll', e4, None, 0.09, 0.30),
    ]
    agents = ['Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0 Safari/537.36',
              'Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0 Mobile Safari/537.36',
              'Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148']
    out = []
    for d, name, scen, subj, sender, html, landing, cr, sr in campaigns:
        created = ctx.ago(d + 6, 11)
        sent = ctx.ago(d, 9)
        cid = ctx.ins('phishing_campaigns', name=name, description=f'Quarterly phishing simulation ({scen}); '
                      'results reported to the IT Steering Committee.', sender_display=sender, email_subject=subj,
                      offer_title=subj, offer_body=None, expiry_text=None, cta_text=None, status='sent',
                      created_by=U('itsup'), created_at=created, sent_at=sent, custom_html=html,
                      scenario_type=scen if scen in ('coupon', 'delivery') else None, company_name=sender,
                      logo_url=None, custom_landing_html=landing)
        recips = staff[:]
        rnd.shuffle(recips)
        clicks = subs = 0
        n_click = round(cr * len(recips))  # exact rates so the quarter-on-quarter trend is clean
        n_sub = round(sr * n_click)
        for k, (nm, em) in enumerate(recips):
            tok = ''.join(rnd.choice('0123456789abcdef') for _ in range(12))
            clicked = k < n_click
            submitted = k < n_sub
            c_at = sent + timedelta(minutes=rnd.randint(4, 60 * 30)) if clicked else None
            if c_at and not 8 <= c_at.hour < 21:  # people open mail in the working day / evening
                c_at = (c_at + timedelta(hours=11 if c_at.hour >= 21 else 0)).replace(hour=rnd.randint(8, 12))
            s_at = c_at + timedelta(seconds=rnd.randint(20, 240)) if submitted else None
            rid = ctx.ins('phishing_recipients', campaign_id=cid, recipient_name=nm, recipient_email=em, token=tok,
                          sent_at=sent + timedelta(seconds=rnd.randint(1, 900)), clicked_at=c_at, submitted_at=s_at,
                          submitted_email=em if submitted else None, submitted_card=None, created_at=created)
            if clicked:
                clicks += 1
                ua = rnd.choice(agents)
                ip = f'10.20.{rnd.randint(1, 4)}.{rnd.randint(10, 250)}'
                ctx.ins('phishing_events', campaign_id=cid, recipient_id=rid, event_type='click', ip_address=ip,
                        user_agent=ua, created_at=c_at)
                if rnd.random() < 0.2:
                    ctx.ins('phishing_events', campaign_id=cid, recipient_id=rid, event_type='click', ip_address=ip,
                            user_agent=ua, created_at=c_at + timedelta(minutes=rnd.randint(1, 50)))
                if submitted:
                    subs += 1
                    ctx.ins('phishing_events', campaign_id=cid, recipient_id=rid, event_type='submit', ip_address=ip,
                            user_agent=ua, extra_data=json.dumps({'email': em, 'card': ''}), created_at=s_at)
        out.append((name, len(recips), clicks, subs))
    # next campaign prepared, not sent yet
    e5, l5 = generate_delivery_design('Example Express (demo)', None, '#d35400', 'EXP-DEMO-90217', 'غداً',
                                      'تتبع الشحنة ←')
    cid = ctx.ins('phishing_campaigns', name='Q4-2026 - parcel tracking (draft)', description='Next quarterly simulation',
                  sender_display='Example Express (demo)', email_subject='لم نتمكن من تسليم شحنتك', status='draft',
                  created_by=U('itsup'), created_at=ctx.ago(2, 12), custom_html=e5, scenario_type='delivery',
                  company_name='Example Express (demo)', custom_landing_html=l5)
    for nm, em in staff[:20]:
        ctx.ins('phishing_recipients', campaign_id=cid, recipient_name=nm, recipient_email=em,
                token=''.join(rnd.choice('0123456789abcdef') for _ in range(12)), created_at=ctx.ago(2, 12))
    return out


def seed(ctx):
    ids = _incidents(ctx)
    _resilience(ctx)
    ph = _phishing(ctx)
    ctx.commit()
    from models.case import Case
    for iid in ids:
        Case.sync_from_source('CYBER_INCIDENT', iid)
    print(f'    incidents {len(ids)}; phishing ' + '; '.join(f'{n}: {r} sent/{c} clicked/{s} submitted' for n, r, c, s in ph))
