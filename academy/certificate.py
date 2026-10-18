# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# =============================================================================
"""Co-branded certificate: Integrys Consulting, powered by ComplyNex."""
import io
import os

import qrcode
from fpdf import FPDF

from .service import PUBLIC_BASE

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG = os.path.join(ROOT, 'static', 'images', 'academy')
FONTS = os.path.join(ROOT, 'static', 'fonts', 'academy')

NAVY = (14, 35, 64)
TEAL = (0, 107, 117)
GREEN = (0, 168, 150)
GREY = (96, 104, 116)
LIGHT = (232, 240, 241)

SIGNERS = [
    ('sig_hussein.png', 'Hussein El Gaafary', 'Founder & Principal Consultant', 'Integrys Consulting'),
    ('sig_emam.png', 'Mohamed Emam', 'Founder', 'ComplyNex'),
]


def verify_url(number):
    return f'{PUBLIC_BASE}/academy/verify/{number}'


def _qr_png(data):
    img = qrcode.make(data, box_size=8, border=1)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf


def build_pdf(cert):
    pdf = FPDF(orientation='L', unit='mm', format='A4')
    pdf.set_auto_page_break(False)
    pdf.set_title(f'Integrys Academy certificate {cert["cert_number"]}')
    pdf.set_author('Integrys Consulting')
    pdf.set_creator('ComplyNex')
    pdf.add_font('Mont', '', os.path.join(FONTS, 'Montserrat-Regular.ttf'))
    pdf.add_font('Mont', 'B', os.path.join(FONTS, 'Montserrat-Bold.ttf'))
    pdf.add_font('MontSB', '', os.path.join(FONTS, 'Montserrat-SemiBold.ttf'))
    pdf.add_page()
    W, H = 297, 210

    # frame
    pdf.set_fill_color(*LIGHT)
    pdf.rect(0, 0, W, H, 'F')
    pdf.set_fill_color(255, 255, 255)
    pdf.rect(8, 8, W - 16, H - 16, 'F')
    pdf.set_draw_color(*TEAL)
    pdf.set_line_width(0.9)
    pdf.rect(8, 8, W - 16, H - 16)
    pdf.set_draw_color(*GREEN)
    pdf.set_line_width(0.25)
    pdf.rect(11, 11, W - 22, H - 22)
    pdf.set_fill_color(*TEAL)
    pdf.rect(8, 8, W - 16, 2.2, 'F')

    provider = cert.get('provider') or 'integrys'
    from PIL import Image
    logo = os.path.join(IMG, 'complynex-logo.png')
    with Image.open(logo) as im:
        ratio = im.width / im.height

    if provider == 'complynex':
        # ComplyNex course: ComplyNex primary, delivered through Integrys Academy
        pdf.image(logo, x=20, y=15, h=26)
        pdf.set_xy(20 + 26 * ratio + 4, 30)
        pdf.set_font('MontSB', '', 8.5)
        pdf.set_text_color(*TEAL)
        pdf.cell(120, 5, 'COMPLYNEX TRAINING  ·  COMPLIANCE TECHNOLOGY')
        pdf.set_xy(W - 92, 19)
        pdf.set_font('Mont', '', 7.5)
        pdf.set_text_color(*GREY)
        pdf.cell(72, 4, 'delivered through', align='R')
        pdf.image(os.path.join(IMG, 'integrys-emblem.png'), x=W - 36, y=23.5, h=15)
        pdf.set_xy(W - 112, 28)
        pdf.set_font('Mont', 'B', 9)
        pdf.set_text_color(*NAVY)
        pdf.cell(74, 5, 'Integrys Academy', align='R')
    else:
        # Integrys course: Integrys primary, powered by ComplyNex
        pdf.image(os.path.join(IMG, 'integrys-emblem.png'), x=20, y=17, h=24)
        pdf.set_xy(50, 21)
        pdf.set_font('Mont', 'B', 17)
        pdf.set_text_color(*NAVY)
        pdf.cell(120, 8, 'Integrys Consulting')
        pdf.set_xy(50, 29.5)
        pdf.set_font('MontSB', '', 8.5)
        pdf.set_text_color(*TEAL)
        pdf.cell(120, 5, 'INTEGRYS ACADEMY  ·  GOVERNANCE · RISK · COMPLIANCE · FINANCIAL CRIME')
        pdf.set_xy(W - 82, 19)
        pdf.set_font('Mont', '', 7.5)
        pdf.set_text_color(*GREY)
        pdf.cell(62, 4, 'powered by', align='R')
        pdf.image(logo, x=W - 20 - 17 * ratio, y=23.5, h=17)

    # title block
    pdf.set_xy(0, 55)
    pdf.set_font('Mont', 'B', 30)
    pdf.set_text_color(*NAVY)
    pdf.cell(W, 13, 'CERTIFICATE OF COMPLETION', align='C')
    pdf.set_draw_color(*GREEN)
    pdf.set_line_width(0.7)
    pdf.line(W / 2 - 35, 71, W / 2 + 35, 71)

    pdf.set_xy(0, 77)
    pdf.set_font('Mont', '', 11.5)
    pdf.set_text_color(*GREY)
    pdf.cell(W, 6, 'This is to confirm that', align='C')

    holder = cert['holder_name'] or '[name redacted]'
    size = 28 if len(holder) <= 32 else 22
    pdf.set_xy(0, 85)
    pdf.set_font('Mont', 'B', size)
    pdf.set_text_color(*TEAL)
    pdf.cell(W, 13, holder, align='C')

    pdf.set_xy(0, 101)
    pdf.set_font('Mont', '', 11.5)
    pdf.set_text_color(*GREY)
    pdf.cell(W, 6, 'has successfully completed the training module', align='C')

    pdf.set_xy(30, 109)
    # shrink long titles so the title block never runs into the date line / signatures
    fs = 16
    pdf.set_font('MontSB', '', fs)
    while fs > 12 and pdf.get_string_width(cert['course_title']) > W - 64:
        fs -= 0.5
        pdf.set_font('MontSB', '', fs)
    pdf.set_text_color(*NAVY)
    pdf.multi_cell(W - 60, 8 if fs >= 16 else 6, cert['course_title'], align='C')

    issued = cert['issued_at'].strftime('%d %B %Y')
    line = f'Completed on {issued}  ·  Assessment score {cert["score"]}%'
    if cert.get('expires_at'):
        line += f'  ·  Valid until {cert["expires_at"].strftime("%d %B %Y")}'
    pdf.set_xy(0, pdf.get_y() + 3)
    pdf.set_font('Mont', '', 10)
    pdf.set_text_color(*GREY)
    pdf.cell(W, 6, line, align='C')

    # signatures
    y_sig = 146
    signers = SIGNERS if provider != 'complynex' else [SIGNERS[1]]
    for i, (img, name, title, org) in enumerate(signers):
        cx = 72 if i == 0 else W - 72
        p = os.path.join(IMG, img)
        if os.path.exists(p):
            pdf.image(p, x=cx - 30, y=y_sig - 15, w=60)
        pdf.set_draw_color(*NAVY)
        pdf.set_line_width(0.3)
        pdf.line(cx - 34, y_sig + 4, cx + 34, y_sig + 4)
        pdf.set_xy(cx - 45, y_sig + 6)
        pdf.set_font('Mont', 'B', 10)
        pdf.set_text_color(*NAVY)
        pdf.cell(90, 5, name, align='C')
        pdf.set_xy(cx - 45, y_sig + 11)
        pdf.set_font('Mont', '', 8)
        pdf.set_text_color(*GREY)
        pdf.cell(90, 4, f'{title}, {org}', align='C')

    # verification block (centre)
    pdf.image(_qr_png(verify_url(cert['cert_number'])), x=W / 2 - 11, y=134, w=22)
    pdf.set_xy(W / 2 - 40, 157)
    pdf.set_font('MontSB', '', 8.5)
    pdf.set_text_color(*NAVY)
    pdf.cell(80, 4, f'Certificate No. {cert["cert_number"]}', align='C')
    pdf.set_xy(W / 2 - 50, 161.5)
    pdf.set_font('Mont', '', 6.8)
    pdf.set_text_color(*GREY)
    pdf.cell(100, 3.5, f'Verify: {PUBLIC_BASE.replace("https://", "")}/academy/verify', align='C')
    pdf.set_xy(W / 2 - 50, 165)
    pdf.cell(100, 3.5, f'Integrity hash {cert["sha256"][:16]}', align='C')

    # footer disclaimer
    pdf.set_xy(20, 180)
    pdf.set_font('Mont', '', 6.8)
    pdf.set_text_color(*GREY)
    pdf.multi_cell(W - 40, 3.4,
        'This certificate confirms completion of the stated training module and assessment. It is not a '
        'professional accreditation, licence or regulatory qualification, and is not endorsed by any regulator. '
        'Signatures are reproduced for attribution. Authenticity can be confirmed at the verification address above.',
        align='C')
    pdf.set_xy(0, 193)
    pdf.set_font('MontSB', '', 7)
    pdf.set_text_color(*TEAL)
    pdf.cell(W, 4, ('ComplyNex  ·  complynex.online  ·  Cairo, Egypt  ·  Delivered through Integrys Academy'
                    if provider == 'complynex' else
                    'Integrys Consulting  ·  integrysconsult.com  ·  Cairo, Egypt  ·  Training delivered on ComplyNex'),
             align='C')

    return bytes(pdf.output())
