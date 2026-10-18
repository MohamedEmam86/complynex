#!/usr/bin/env python3
"""
ComplyNex email self-test.

Run after changing mail settings in .env:
    sudo -u complynex env HOME=/tmp /var/www/complynex/venv/bin/python \
         /var/www/complynex/scripts/mailcheck.py [recipient@example.com]

Prints exactly which stage fails. Never prints the password.
"""
import sys, smtplib, socket
from email.mime.text import MIMEText

sys.path.insert(0, '/var/www/complynex')
from app import app

with app.app_context():
    c = app.config
    user, pwd = c.get('MAIL_USERNAME'), c.get('MAIL_PASSWORD')
    host, port = c.get('MAIL_SERVER'), c.get('MAIL_PORT')

    print(f'account : {user or "NOT SET"}')
    print(f'password: {"set" if pwd else "NOT SET"}')
    print(f'server  : {host}:{port}')
    print(f'mock    : {c.get("EMAIL_MOCK_MODE")}\n')

    if not (user and pwd):
        print('FAIL — no credentials. Set EMAIL_USER and EMAIL_PASS in .env.')
        sys.exit(1)

    try:
        if int(port) == 465:
            s = smtplib.SMTP_SSL(host, port, timeout=15); s.ehlo()
            print('1. connect (SSL/465) ... OK')
        else:
            s = smtplib.SMTP(host, port, timeout=15)
            s.ehlo(); s.starttls(); s.ehlo()
            print('1. connect + STARTTLS .. OK')
    except (socket.timeout, OSError) as e:
        print(f'1. connect ............. FAIL — {str(e)[:120]}')
        print('   Outbound SMTP may be blocked by the VPS provider. Try port 465,')
        print('   or ask Contabo to open outbound 587.')
        sys.exit(1)

    try:
        s.login(user, pwd)
        print('2. authenticate ........ OK')
    except smtplib.SMTPAuthenticationError as e:
        print(f'2. authenticate ........ FAIL ({e.smtp_code})')
        print(f'   {(e.smtp_error or b"").decode(errors="replace")[:160]}')
        print('   The password in .env is not accepted by the mail host.')
        print('   Reset the mailbox password in your mail provider and update .env.')
        print('   If the account has 2FA, you need an app-specific password.')
        s.quit(); sys.exit(1)

    to = sys.argv[1] if len(sys.argv) > 1 else user
    m = MIMEText('ComplyNex email delivery is working. '
                 'Declaration and case reminders will now be sent by email as well as in-app.')
    m['Subject'] = 'ComplyNex — email test'
    m['From'] = c.get('MAIL_DEFAULT_SENDER') or user
    m['To'] = to
    try:
        s.send_message(m)
        print(f'3. send test message ... OK -> {to}')
        print('\nEmail delivery is working.')
    except Exception as e:
        print(f'3. send ................ FAIL — {str(e)[:150]}')
        sys.exit(1)
    finally:
        s.quit()
