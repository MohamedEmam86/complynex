"""FRA NBFI content pack + its end-to-end demo (lending, prudential, IT, carbon
data with deliberate breaches -> control runs -> inspection findings -> six
remediated and verified)."""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OWNERS = {  # control code prefix / area -> owner
    'FRA-0': 'mlro',
}


def _run(*args):
    p = subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True, timeout=1800)
    tail = [l for l in (p.stdout + p.stderr).splitlines() if l.strip() and 'INFO' not in l and 'faiss' not in l]
    print('    ' + '\n    '.join(tail[-6:]))
    if p.returncode:
        raise RuntimeError(f'{args} failed')


def seed(ctx):
    from regcontrols import packs
    ctx.commit()
    packs.enable('fra_nbfi', user_id=ctx.uid('admin'))
    demo = os.path.join('packs', 'fra_nbfi', 'scripts', 'demo_fra.py')
    _run(demo, 'setup')
    _run(demo, 'remediate')
    # spread ownership over the people who would really own each area
    area_owner = {'climate': 'risk', 'capital_licensing': 'cfo', 'origination': 'ops', 'pricing_conduct': 'cs',
                  'aml_cft': 'mlro', 'financial_reporting': 'cfo', 'it_cyber': 'it', 'remediation': 'mlro'}
    for c in ctx.q("SELECT id, area FROM rc_controls"):
        ctx.q("UPDATE rc_controls SET owner_user_id = %s WHERE id = %s",
              (ctx.uid(area_owner.get(c['area'] or '', 'mlro')), c['id']))
    ctx.q("""UPDATE rc_findings f SET owner_user_id = c.owner_user_id FROM rc_finding_controls fc
             JOIN rc_controls c ON c.id = fc.control_id WHERE fc.finding_id = f.id""")
    ctx.q("""UPDATE rc_corrective_actions a SET owner_user_id = f.owner_user_id FROM rc_findings f
             WHERE f.id = a.finding_id""")
    # Nile Microfinance holds a microfinance licence (not the first code alphabetically).
    lt = ctx.one("SELECT code FROM rc_licence_types WHERE pack_code = 'fra_nbfi' "
                 "ORDER BY (code = 'microfinance') DESC, code LIMIT 1")
    if lt:
        ctx.q("UPDATE corp_profile SET licence_type = %s", (lt['code'],))
