"""Generate the test fixtures a fresh clone needs: a sample resume and a
sample target workbook. Both are synthetic — no real person, no real contact.

    python tests\\make_fixtures.py
"""
from __future__ import annotations

from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"

RESUME_TEXT = """Alex Doe
alex.doe@example.edu | +00-000-000-0000 | Example City

EDUCATION
B.Tech in Engineering Physics, Example Institute of Technology, expected 2029
CGPA: 8.9/10

RESEARCH INTERESTS
Machine learning for high-energy physics, jet tagging, graph neural networks,
anomaly detection, transformer architectures, generative models for simulation,
physics-informed neural networks, scientific computing.

PROJECTS
Gated Dual-Stream Particle Transformer
Built a modified Particle Transformer for jet classification, adding a gated
dual-stream attention path and multiplicative feature-space gating. Trained on a
small subset of the JetClass dataset, mostly to understand the architecture.

Graph Neural Networks for Calorimeter Clustering
Implemented a GNN that groups calorimeter hits into clusters, using PyTorch
Geometric. Spent most of the time on the edge-construction step.

Normalising Flows for Fast Detector Simulation
Tried a conditional normalising flow as a surrogate for a slow simulation step.
Still working out why the tails are mismodelled.

SKILLS
Python, PyTorch, NumPy, ROOT, C++, Git, Linux, PyTorch Geometric, scikit-learn,
pandas, Matplotlib, LaTeX, Slurm, Docker.

ACHIEVEMENTS
Department rank 3 of 120. Institute merit scholarship.
"""

PROFESSORS = [
    ("Prof. Jane Smith", "jane.smith@uni-example.de", "Example University", "Germany",
     "Machine learning for collider physics; transformer models for jet tagging",
     "Direct overlap with my Particle Transformer project", "Likely Funded",
     "Yes (DAAD WISE)", "Direct email + DAAD", "Nov 2026"),
    ("Prof. Marco Rossi", "m.rossi@uni-example.it", "Example Polytechnic", "Italy",
     "Deep learning for high-energy physics; anomaly detection at the LHC",
     "Overlap on anomaly detection", "Likely Funded", "Yes", "Direct email", "Jan 2027"),
    ("Dr. Anna Mueller", "anna.mueller@uni-example.de", "Example Institute", "Germany",
     "Graph neural networks for calorimeter reconstruction",
     "Matches my GNN clustering project", "Funded", "Yes (DAAD)", "Direct email", "Dec 2026"),
    ("Prof. Pierre Dubois", "p.dubois@lab-example.fr", "Example Laboratory", "France",
     "Generative models for fast detector simulation; normalising flows",
     "Matches my flow-based simulation project", "Likely Funded", "Yes",
     "Direct email", "Feb 2027"),
    ("Prof. Sofia Lindqvist", "s.lindqvist@uni-example.se", "Example Nordic University",
     "Sweden", "Physics-informed neural networks for scientific computing",
     "Adjacent: PINNs and SciML", "Unclear", "Yes", "Direct email", "Mar 2027"),
    ("Dr. Liam O'Connor", "l.oconnor@uni-example.ie", "Example College", "Ireland",
     "Statistical inference and likelihood-free methods in particle physics",
     "Adjacent: simulation-based inference", "Likely Funded", "Yes",
     "Direct email", "Jan 2027"),
    ("Prof. Elena Petrova", "e.petrova@uni-example.nl", "Example Technical University",
     "Netherlands", "Representation learning for jet substructure",
     "Strong overlap with jet tagging", "Funded", "Yes", "Direct email", "Dec 2026"),
    ("Prof. Thomas Weber", "t.weber@uni-example.ch", "Example Federal Institute",
     "Switzerland", "Transformers and self-supervised learning for detector data",
     "Direct overlap", "Likely Funded", "Yes", "Direct email", "Nov 2026"),
    ("Dr. Priya Nair", "p.nair@uni-example.uk", "Example University of Science", "UK",
     "Machine learning for astrophysical surveys; anomaly detection",
     "Adjacent: anomaly detection, different domain", "Unclear", "Yes",
     "Direct email", "Feb 2027"),
    ("Prof. Hans Berg", "h.berg@uni-example.dk", "Example Danish University", "Denmark",
     "Quantum computing for optimisation", "Weak overlap", "Unclear", "Yes",
     "Direct email", "Mar 2027"),
    ("Prof. Chiara Bianchi", "c.bianchi@uni-example.it", "Example Research Centre",
     "Italy", "Deep learning for medical imaging", "Weak overlap: different domain",
     "Unclear", "Yes", "Direct email", "Apr 2027"),
    ("Prof. Olaf Nilsen", "o.nilsen@uni-example.no", "Example Norwegian University",
     "Norway", "Organic chemistry of natural products",
     "No overlap; included as a negative control", "Unclear", "Yes",
     "Direct email", "May 2027"),
]

HEADERS = ["Priority/Rank", "Professor Name", "Institution", "Country", "Research Area",
           "Fit with My Profile", "Funding Status", "Eligibility", "Application Route",
           "Deadline", "Email Address"]


def make_resume(path: Path) -> Path:
    """Write the sample resume as a real PDF so pdfplumber can read it."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except ImportError:
        return _make_resume_minimal_pdf(path)

    c = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    y = height - 50
    for line in RESUME_TEXT.splitlines():
        if y < 50:
            c.showPage()
            y = height - 50
        c.setFont("Helvetica-Bold" if line.isupper() and line.strip() else "Helvetica", 10)
        c.drawString(50, y, line)
        y -= 14
    c.save()
    return path


def _make_resume_minimal_pdf(path: Path) -> Path:
    """Hand-rolled single-stream PDF, so fixtures need no extra dependency."""
    lines = RESUME_TEXT.splitlines()
    parts = ["BT", "/F1 10 Tf", "12 TL", "50 800 Td"]
    for line in lines:
        safe = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        parts.append(f"({safe}) Tj T*")
    parts.append("ET")
    stream = "\n".join(parts).encode("latin-1", "replace")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_at}\n%%EOF\n").encode()
    path.write_bytes(bytes(out))
    return path


def make_workbook(path: Path) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Targets"
    ws.append(HEADERS)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for rank, prof in enumerate(PROFESSORS, 1):
        name, email, inst, country, area, fit, funding, elig, route, deadline = prof
        ws.append([rank, name, inst, country, area, fit, funding, elig, route,
                   deadline, email])
    for col, width in zip("ABCDEFGHIJK", (12, 26, 28, 14, 46, 38, 16, 16, 20, 12, 32)):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = "B2"
    wb.save(path)
    return path


def main() -> int:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    resume = make_resume(FIXTURES / "sample_resume.pdf")
    workbook = make_workbook(FIXTURES / "sample_targets.xlsx")
    print(f"wrote {resume}")
    print(f"wrote {workbook}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
