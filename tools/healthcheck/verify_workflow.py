#!/usr/bin/env python3
"""End-to-end verification of the screening / alert workflow changes."""
import re
import sys

sys.path.insert(0, '/var/www/complynex')
from app import create_app
from database.db import get_db

app = create_app()


def csrf(client, url):
    m = re.search(r'name="csrf_token" value="([^"]+)"',
                  client.get(url).get_data(as_text=True))
    return m.group(1) if m else ''


with app.test_client() as c:
    with c.session_transaction() as s:
        s['_user_id'] = __import__('models.user', fromlist=['User']).User.session_id_for_app(app, 1)
        s['_fresh'] = True

    print('=== pages render (EN + AR) ===')
    for u in ('/screening/queue', '/screening/result/714', '/aml/alerts',
              '/aml/alerts?status=ALL', '/aml/alerts/1', '/blacklist/',
              '/blacklist/?confirmation_type=TEAM_CONFIRMED',
              '/blacklist/?confirmation_type=IMPORTED',
              '/screening/whitelist'):
        a = c.get(u).status_code
        b = c.get(u + ('&' if '?' in u else '?') + 'lang=ar').status_code
        print('  %-50s en=%s ar=%s' % (u, a, b))

    print('\n=== blacklist filter actually splits the data ===')
    with app.app_context():
        db = get_db()
        for label, q in (
            ('team confirmed',
             "SELECT count(*) AS c FROM internal_blacklist "
             "WHERE confirmation_type = 'TEAM_CONFIRMED'"),
            ('imported',
             "SELECT count(*) AS c FROM internal_blacklist "
             "WHERE confirmation_type IS DISTINCT FROM 'TEAM_CONFIRMED'"),
        ):
            print('  %-20s %s' % (label, db.execute(q).fetchone()['c']))

    print('\n=== AML false-positive closure routes to whitelist ===')
    with app.app_context():
        db = get_db()
        row = db.execute("""
            SELECT a.id, a.alert_reference,
                   COALESCE(cu.full_name, cu.company_name) AS cname
              FROM tm_alerts a
              LEFT JOIN customers cu ON a.customer_id = cu.id
             WHERE a.status = 'NEW'
               AND COALESCE(cu.full_name, cu.company_name) IS NOT NULL
             LIMIT 1""").fetchone()
    if not row:
        print('  no suitable NEW alert with a linked customer to test')
    else:
        alert_id, ref, cname = row['id'], row['alert_reference'], row['cname']
        print('  testing alert %s (%s) customer=%r' % (alert_id, ref, cname))
        with app.app_context():
            db = get_db()
            before = db.execute(
                "SELECT count(*) AS c FROM screening_whitelist "
                "WHERE upper(trim(normalized_name)) = %s",
                (cname.upper().strip(),)).fetchone()['c']
        url = '/aml/alerts/%s' % alert_id
        r = c.post(url, data={'csrf_token': csrf(c, url),
                              'action': 'false_positive',
                              'notes': 'VERIFY_PROBE closure'},
                   follow_redirects=True)
        print('  POST status:', r.status_code)
        with app.app_context():
            db = get_db()
            after = db.execute(
                "SELECT name, reason, status FROM screening_whitelist "
                "WHERE upper(trim(normalized_name)) = %s",
                (cname.upper().strip(),)).fetchall()
            st = db.execute("SELECT status FROM tm_alerts WHERE id = %s",
                            (alert_id,)).fetchone()['status']
        print('  alert status now :', st)
        print('  whitelist before :', before, '-> after:', len(after))
        for w in after:
            print('     ', dict(w))

    print('\n=== alert no longer in the default (open) list ===')
    body = c.get('/aml/alerts').get_data(as_text=True)
    print('  ref present in open list:', (ref in body) if row else 'n/a')
    body_all = c.get('/aml/alerts?status=ALL').get_data(as_text=True)
    print('  ref present in ALL list :', (ref in body_all) if row else 'n/a')
