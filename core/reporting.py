from __future__ import annotations

from io import BytesIO

import pandas as pd


def audit_view(results: pd.DataFrame, adjustment_header: str = "Adjustment Amount") -> pd.DataFrame:
    """Present results in the portal-versus-Tally audit layout requested by users."""
    status_labels = {
        "Total match": "Matched - Exact (normalized)",
        "Partial match": "Matched - Amount difference",
        "Needs review": "Matched - Fuzzy (please verify)",
        "No match": "No match found in Tally",
        "No match in TDS": "No match found in Portal",
    }
    notes = {
        "Total match": "",
        "Partial match": "Amount difference - verify",
        "Needs review": "Verify company name before approval",
        "No match": "No matching Tally ledger",
        "No match in TDS": "No matching portal entry",
    }
    output = pd.DataFrame({
        "TAN Number (Portal)": results.get("tds_tan"),
        "Name of Company (Portal)": results["tds_party"],
        "Name of Company (Tally)": results["tally_party"],
        "Total TDS Deposited Rs. (Portal)": results["tds_tax_amount"],
        "Debit Amount Rs. (Tally)": results["tally_tax_amount"],
        "Match Status": results["status"].map(status_labels).fillna(results["status"]),
        adjustment_header: 0.0,
        "_separator": "",
        "difference": 0.0,
        "_notes": results["status"].map(notes).fillna(""),
    })
    portal = pd.to_numeric(output["Total TDS Deposited Rs. (Portal)"], errors="coerce").fillna(0.0)
    tally = pd.to_numeric(output["Debit Amount Rs. (Tally)"], errors="coerce").fillna(0.0)
    output["difference"] = portal - tally - output[adjustment_header]
    output.columns = [
        "TAN Number (Portal)", "Name of Company (Portal)", "Name of Company (Tally)",
        "Total TDS Deposited Rs. (Portal)", "Debit Amount Rs. (Tally)", "Match Status",
        adjustment_header, "", "difference", "",
    ]
    return output


def excel_report(results: pd.DataFrame, mapping_rows: list[dict[str, str]], adjustment_header: str = "Adjustment Amount") -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        audit = audit_view(results, adjustment_header)
        # First sheet: matches the supplied Tally-vs-Portal audit format.
        audit.to_excel(writer, sheet_name="Tally vs Portal Match", index=False, startrow=2)
        workbook = writer.book
        audit_sheet = writer.sheets["Tally vs Portal Match"]
        header_format = workbook.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": "#1F4E78", "align": "center", "valign": "vcenter", "text_wrap": True, "border": 1})
        amount_format = workbook.add_format({"num_format": "#,##0.00"})
        audit_sheet.write_formula(0, 3, f"=SUM(D4:D{len(audit) + 3})", amount_format)
        audit_sheet.write_formula(0, 4, f"=SUM(E4:E{len(audit) + 3})", amount_format)
        audit_sheet.write_formula(0, 6, f"=SUM(G4:G{len(audit) + 3})", amount_format)
        audit_sheet.write_formula(0, 8, "=D1-E1-G1", amount_format)
        audit_sheet.write(1, 3, "Portal")
        audit_sheet.write(1, 4, "Tally")
        for col, header in enumerate(audit.columns):
            audit_sheet.write(2, col, header, header_format)
        for row_number in range(len(audit)):
            excel_row = row_number + 3
            audit_sheet.write_formula(excel_row, 8, f"=D{excel_row + 1}-E{excel_row + 1}-G{excel_row + 1}", amount_format)
        audit_sheet.set_column("A:A", 18)
        audit_sheet.set_column("B:B", 42)
        audit_sheet.set_column("C:C", 42)
        audit_sheet.set_column("D:E", 24, amount_format)
        audit_sheet.set_column("F:F", 32)
        audit_sheet.set_column("G:G", 18, amount_format)
        audit_sheet.set_column("H:H", 3)
        audit_sheet.set_column("I:I", 18, amount_format)
        audit_sheet.set_column("J:J", 32)
        audit_sheet.freeze_panes(3, 0)
        audit_sheet.autofilter(2, 0, len(audit) + 2, len(audit.columns) - 1)
        audit_sheet.conditional_format(3, 5, len(audit) + 2, 5, {"type": "text", "criteria": "containing", "value": "Exact", "format": workbook.add_format({"bg_color": "#E2F0D9"})})
        audit_sheet.conditional_format(3, 5, len(audit) + 2, 5, {"type": "text", "criteria": "containing", "value": "Fuzzy", "format": workbook.add_format({"bg_color": "#FFF2CC"})})
        audit_sheet.conditional_format(3, 5, len(audit) + 2, 5, {"type": "text", "criteria": "containing", "value": "No match", "format": workbook.add_format({"bg_color": "#FCE4D6"})})
        summary = results["status"].value_counts(dropna=False).rename_axis("status").reset_index(name="count")
        summary.to_excel(writer, sheet_name="Summary", index=False)
        results.to_excel(writer, sheet_name="All results", index=False)
        for status, filename in [("Total match", "Total matches"), ("Partial match", "Partial matches"), ("Needs review", "Needs review"), ("No match", "No match")]:
            results[results["status"] == status].to_excel(writer, sheet_name=filename, index=False)
        pd.DataFrame(mapping_rows).to_excel(writer, sheet_name="Approved mapping", index=False)
        for name, worksheet in writer.sheets.items():
            if name == "Tally vs Portal Match":
                continue
            worksheet.freeze_panes(1, 0)
            worksheet.autofilter(0, 0, max(1, len(results)), max(0, len(results.columns) - 1))
    return output.getvalue()
