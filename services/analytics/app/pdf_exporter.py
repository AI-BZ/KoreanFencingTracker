"""
PDF exporter for fencing match analysis reports.

Converts MatchReport dict to PDF bytes via weasyprint (HTML → PDF).
Falls back gracefully if weasyprint is not installed.
"""

from typing import Optional

from app.report_renderer import ReportRenderer


class PDFExporter:
    """Export MatchReport as PDF using weasyprint."""

    def __init__(self) -> None:
        self._renderer = ReportRenderer()

    def export(self, report_dict: dict) -> bytes:
        """
        Export MatchReport as PDF bytes.

        Uses weasyprint to convert HTML to PDF.
        Falls back gracefully if weasyprint is not installed.

        Args:
            report_dict: MatchReport.to_dict() output

        Returns:
            PDF file content as bytes

        Raises:
            RuntimeError: If weasyprint is not installed
        """
        try:
            import weasyprint  # type: ignore[import-untyped]
        except ImportError:
            raise RuntimeError(
                "weasyprint is not installed. "
                "Install it with: arch -arm64 python3 -m pip install weasyprint"
            )

        html_str = self._renderer.render_html(report_dict, standalone=True)
        doc = weasyprint.HTML(string=html_str)
        return doc.write_pdf()
