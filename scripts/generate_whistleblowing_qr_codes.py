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
QR Code Generator for Whistleblowing Portal
============================================
Generates QR codes for posters, business cards, and promotional materials.

Usage:
    python generate_whistleblowing_qr_codes.py

Requires:
    pip install qrcode[pil] pillow
"""

import qrcode
from PIL import Image, ImageDraw, ImageFont
import os

def generate_qr_code(url, filename, size=300):
    """Generate a simple QR code"""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    img = img.resize((size, size))
    img.save(filename)
    print(f"✓ Generated: {filename}")
    return img

def generate_poster(base_url, output_dir="whistleblowing_materials"):
    """Generate a complete poster with QR code and text"""
    os.makedirs(output_dir, exist_ok=True)
    
    # URLs to generate
    report_url = f"{base_url}/whistleblowing/report"
    track_url = f"{base_url}/whistleblowing/track"
    info_url = f"{base_url}/whistleblowing/anonymous"
    
    # 1. Simple QR Code (for basic posters)
    print("\n📱 Generating QR codes...")
    generate_qr_code(report_url, f"{output_dir}/qr_report.png", size=400)
    generate_qr_code(track_url, f"{output_dir}/qr_track.png", size=400)
    generate_qr_code(info_url, f"{output_dir}/qr_info.png", size=400)
    
    # 2. Business Card Size
    print("\n💳 Generating business card QR code...")
    generate_qr_code(report_url, f"{output_dir}/qr_business_card.png", size=200)
    
    # 3. Poster with Text (8.5x11 inch)
    print("\n🖨️  Generating full poster...")
    create_poster_with_text(report_url, f"{output_dir}/poster_full.png")
    
    # 4. Small sticker (2x2 inch)
    print("\n🏷️  Generating sticker...")
    create_sticker(report_url, f"{output_dir}/sticker.png")
    
    print(f"\n✅ All files saved to: {output_dir}/")
    print(f"\n📋 Files generated:")
    print(f"   • qr_report.png - Main QR code for reporting")
    print(f"   • qr_track.png - QR code for tracking cases")
    print(f"   • qr_info.png - QR code for information page")
    print(f"   • qr_business_card.png - Small QR for cards")
    print(f"   • poster_full.png - Complete poster (8.5x11)")
    print(f"   • sticker.png - Small sticker (2x2)")

def create_poster_with_text(url, filename):
    """Create a full poster with QR code and text"""
    # A4 size in pixels (8.5x11 inch at 300 DPI)
    width, height = 2550, 3300
    
    # Create white background
    img = Image.new('RGB', (width, height), 'white')
    draw = ImageDraw.Draw(img)
    
    # Colors
    primary_color = (0, 123, 255)  # Blue
    warning_color = (255, 193, 7)  # Yellow
    text_color = (51, 51, 51)  # Dark gray
    
    # Add colored header
    draw.rectangle([(0, 0), (width, 500)], fill=primary_color)
    
    # Generate QR code
    qr_img = qrcode.make(url, box_size=12, border=2)
    qr_img = qr_img.resize((800, 800))
    
    # Position QR code
    qr_x = (width - 800) // 2
    qr_y = 1000
    img.paste(qr_img, (qr_x, qr_y))
    
    try:
        # Try to use a nice font
        title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 120)
        subtitle_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 80)
        text_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 60)
    except:
        # Fallback to default font
        title_font = ImageFont.load_default()
        subtitle_font = ImageFont.load_default()
        text_font = ImageFont.load_default()
    
    # Title
    title = "SPEAK UP SAFELY"
    title_bbox = draw.textbbox((0, 0), title, font=title_font)
    title_width = title_bbox[2] - title_bbox[0]
    draw.text(((width - title_width) // 2, 150), title, fill='white', font=title_font)
    
    # Subtitle (Arabic)
    subtitle = "تكلم بأمان"
    subtitle_bbox = draw.textbbox((0, 0), subtitle, font=subtitle_font)
    subtitle_width = subtitle_bbox[2] - subtitle_bbox[0]
    draw.text(((width - subtitle_width) // 2, 320), subtitle, fill='white', font=subtitle_font)
    
    # "Scan to Report Anonymously" above QR
    scan_text = "Scan to Report Anonymously"
    scan_bbox = draw.textbbox((0, 0), scan_text, font=subtitle_font)
    scan_width = scan_bbox[2] - scan_bbox[0]
    draw.text(((width - scan_width) // 2, 850), scan_text, fill=text_color, font=subtitle_font)
    
    # URL below QR
    url_short = url.replace('https://', '').replace('http://', '')
    url_bbox = draw.textbbox((0, 0), url_short, font=text_font)
    url_width = url_bbox[2] - url_bbox[0]
    draw.text(((width - url_width) // 2, 1950), url_short, fill=text_color, font=text_font)
    
    # Features at bottom
    y_pos = 2300
    features = [
        "✓ 100% Anonymous",
        "✓ Protected by Law",
        "✓ No Retaliation",
        "✓ Encrypted & Secure"
    ]
    
    for feature in features:
        feat_bbox = draw.textbbox((0, 0), feature, font=text_font)
        feat_width = feat_bbox[2] - feat_bbox[0]
        draw.text(((width - feat_width) // 2, y_pos), feature, fill=text_color, font=text_font)
        y_pos += 120
    
    # Warning box at bottom
    draw.rectangle([(100, 2950), (width-100, 3200)], fill=warning_color)
    warning = "Keep this number visible and accessible to all employees"
    warning_bbox = draw.textbbox((0, 0), warning, font=text_font)
    warning_width = warning_bbox[2] - warning_bbox[0]
    draw.text(((width - warning_width) // 2, 3025), warning, fill=text_color, font=text_font)
    
    img.save(filename, quality=95)

def create_sticker(url, filename):
    """Create a small 2x2 inch sticker"""
    # 2x2 inch at 300 DPI
    size = 600
    
    img = Image.new('RGB', (size, size), 'white')
    draw = ImageDraw.Draw(img)
    
    # Generate QR code
    qr_img = qrcode.make(url, box_size=4, border=1)
    qr_img = qr_img.resize((400, 400))
    
    # Center QR code
    img.paste(qr_img, (100, 50))
    
    try:
        text_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 30)
    except:
        text_font = ImageFont.load_default()
    
    # Text at bottom
    text = "Report Anonymously"
    text_bbox = draw.textbbox((0, 0), text, font=text_font)
    text_width = text_bbox[2] - text_bbox[0]
    draw.text(((size - text_width) // 2, 500), text, fill='black', font=text_font)
    
    img.save(filename, quality=95)

def main():
    """Main function"""
    print("=" * 60)
    print("  WHISTLEBLOWING QR CODE GENERATOR")
    print("=" * 60)
    
    # Get base URL
    print("\nEnter your ComplyNex URL:")
    print("Examples:")
    print("  • https://complynex.online")
    print("  • http://localhost:5000")
    print("  • https://cms.complynex.online")
    
    base_url = input("\nURL: ").strip().rstrip('/')
    
    if not base_url:
        base_url = "https://complynex.online"
        print(f"Using default: {base_url}")
    
    # Generate all materials
    generate_poster(base_url)
    
    print("\n" + "=" * 60)
    print("  NEXT STEPS")
    print("=" * 60)
    print("\n1. Print 'poster_full.png' on 8.5x11 paper")
    print("2. Post in break rooms, bathrooms, elevators")
    print("3. Print 'sticker.png' on label paper")
    print("4. Stick on doors, walls, bulletin boards")
    print("5. Print 'qr_business_card.png' on business cards")
    print("6. Hand out at orientation\n")

if __name__ == "__main__":
    try:
        import qrcode
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("ERROR: Required libraries not installed")
        print("\nPlease run:")
        print("  pip install qrcode[pil] pillow")
        print("\nThen run this script again.")
        exit(1)
    
    main()
