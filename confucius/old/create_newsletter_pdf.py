import re
from fpdf import FPDF

class PDF(FPDF):
    def header(self):
        pass

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

def handle_line(pdf, line):
    """Parses a single line of markdown and adds it to the PDF."""
    line = line.strip()
    if not line:
        return

    # --- HEADERS ---
    if line.startswith('## '):
        pdf.set_font('Arial', 'B', 16)
        pdf.ln(10)
        pdf.cell(0, 10, line[3:].strip(), 0, 1, 'L')
        pdf.ln(2)
    elif line.startswith('# '):
        pdf.set_font('Arial', 'B', 24)
        pdf.ln(10)
        pdf.cell(0, 10, line[1:].strip(), 0, 1, 'C')
        pdf.ln(5)
    # --- LISTS ---
    elif line.startswith('* '):
        pdf.set_font('Arial', '', 11)
        pdf.ln(2)
        with pdf.unbreakable() as doc:
            doc.cell(5, 5, '-', 0, 0)
            doc.multi_cell(0, 5, line[2:].strip())
        pdf.ln(2)
    # --- HORIZONTAL RULE ---
    elif line.startswith('---'):
        pdf.ln(5)
        pdf.line(pdf.get_x(), pdf.get_y(), pdf.get_x() + 190, pdf.get_y())
        pdf.ln(5)
    # --- PARAGRAPHS (and bold/italics) ---
    else:
        pdf.set_font('Arial', '', 11)
        # Split line by bold/italic markers to handle formatting
        parts = re.split(r'(\*\*.*?\*\*|\*.*?\*)', line)
        for part in parts:
            if part.startswith('**'):
                pdf.set_font('', 'B')
                pdf.write(5, part.strip('*'))
                pdf.set_font('', '')
            elif part.startswith('*'):
                pdf.set_font('', 'I')
                pdf.write(5, part.strip('*'))
                pdf.set_font('', '')
            else:
                pdf.write(5, part)
        pdf.ln(6)


def create_newsletter_pdf():
    """Creates the newsletter PDF from the markdown file."""
    pdf = PDF('P', 'mm', 'A4')
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font('Arial', '', 12)

    # Add a header image
    pdf.image('/Users/kim/Documents/ai/confucius/static/images/7facts_pNmCNg.jpeg', x=10, y=8, w=190)
    pdf.ln(80) # Move down after the image

    with open('/Users/kim/Documents/ai/confucius/newsletter.md', 'r', encoding='utf-8') as f:
        for line in f:
            # Skip the first title, as we have an image header
            if line.startswith('# '):
                continue
            handle_line(pdf, line)

            # Add a second image mid-document for visual interest
            if "From Linear to Legendary!" in line:
                 pdf.ln(5)
                 pdf.image('/Users/kim/Documents/ai/confucius/static/images/tvb_invest_CLxxnw.jpg', w=150, x=30)
                 pdf.ln(5)


    pdf.output('newsletter.pdf')
    print("Successfully created newsletter.pdf")

if __name__ == '__main__':
    create_newsletter_pdf()
