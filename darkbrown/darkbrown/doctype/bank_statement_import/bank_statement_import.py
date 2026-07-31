import frappe
from frappe.model.document import Document


class BankStatementImport(Document):
    """Minimal on purpose. Lines arrive already parsed — QNB and Doha Bank
    exports are pasted or fed through their own parsers — and the only
    intelligence here is a conservative auto-match. Anything the matcher is
    not sure about stays Unmatched, visibly, on the Command Centre."""

    def before_insert(self):
        self.imported_by = frappe.session.user

    def before_save(self):
        self.total_lines = len(self.lines or [])
        self.matched = len([l for l in (self.lines or [])
                            if l.status == "Matched"])
        self.unmatched = len([l for l in (self.lines or [])
                              if l.status == "Unmatched"])
