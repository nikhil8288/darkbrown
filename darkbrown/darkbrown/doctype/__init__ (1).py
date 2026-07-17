# Copyright (c) 2026, DarkBrown RealEstate and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class DocumentArchive(Document):
	def before_insert(self):
		self.archived_on = self.archived_on or now_datetime()
		self.archived_by = self.archived_by or frappe.session.user

	def validate(self):
		if self.id_number:
			self.id_number = self.id_number.replace(" ", "").strip()
