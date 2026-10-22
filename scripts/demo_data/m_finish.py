"""Last step: put back the company profile (the FRA pack's prudential demo writes
its own), size the prudential figures so ESG/carbon thresholds and prudential
data agree, re-run every regulatory control on the full data set and store
today's readiness score."""
from common import COMPANY_EN, COMPANY_AR, DOMAIN

SCALE = 10  # prudential demo figures x10: a mid-size MFI (assets ~EGP 1.7bn, equity ~EGP 180m)


def seed(ctx):
    ctx.q("""UPDATE corp_profile SET legal_name_en = %s, legal_name_ar = %s,
             registered_address_en = %s, registered_address_ar = %s, commercial_register_no = %s,
             tax_card_no = %s, licence_number = %s, phone = %s, email = %s, website = %s WHERE id = 1""",
          (COMPANY_EN, COMPANY_AR, '12 Example Street, Fifth Settlement, New Cairo, Egypt (demo address)',
           '12 شارع المثال، التجمع الخامس، القاهرة الجديدة (عنوان وهمي)', 'DEMO-CR-104233', 'DEMO-552-118-907',
           'FRA-MF-DEMO-0417', '+20 2 0000 0000', f'info@{DOMAIN}', f'https://www.{DOMAIN}'))
    # paid-up capital stays at EGP 15m (below the EGP 20m licence minimum: the FRA-001 inspection finding)
    ctx.q("""UPDATE pr_financial_periods SET total_assets = total_assets * %s, total_liabilities = total_liabilities * %s,
             equity = equity * %s, capital_base = capital_base * %s, loan_portfolio = loan_portfolio * %s
             WHERE total_assets < 1000000000""", (SCALE,) * 5)
    last = ctx.one("SELECT equity, paid_up_capital FROM pr_financial_periods ORDER BY period_end DESC LIMIT 1")
    if last:
        ctx.q("UPDATE carbon_scope_config SET issued_capital_egp = %s, net_equity_egp = %s",
              (last['paid_up_capital'], last['equity']))
    ctx.commit()

    from regcontrols import engine, readiness
    from database.db import get_db
    db = get_db()
    st = {}
    for r in db.execute("SELECT control_code FROM rc_controls WHERE is_active ORDER BY control_code").fetchall():
        try:
            res = engine.run_control(r['control_code'], triggered_by='schedule')
            st[res['status']] = st.get(res['status'], 0) + 1
        except Exception as e:  # one broken check must not stop the demo
            st['error'] = st.get('error', 0) + 1
            print(f"    {r['control_code']}: {str(e)[:120]}")
    readiness.snapshot(db)
    s = readiness.overview(db=db)['overall']
    print(f'    controls re-run: {st} · readiness {s["score"]} / 100')
