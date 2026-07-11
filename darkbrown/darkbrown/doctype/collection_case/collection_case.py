import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import nowdate


class CollectionCase(Document):
    def validate(self):
        old = self.get_doc_before_save()
        old_status = old.status if old else None

        if self.status == "Legal" and old_status != "Legal":
            # Only GM (or admin) may escalate. Workflow enforces this too;
            # this is the server-side backstop.
            roles = set(frappe.get_roles(frappe.session.user))
            if not roles & {"General Manager", "System Manager", "Administrator"}:
                frappe.throw(_("Only the General Manager can escalate a case to Legal"))
            self.escalated_on = nowdate()
            self.escalated_by = frappe.session.user

        if self.status == "Collected" and old_status != "Collected":
            self.collected_on = self.collected_on or nowdate()

        if self.status == "Contacted" and not self.contacted_on:
            self.contacted_on = nowdate()
