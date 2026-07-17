# Copyright (c) 2026, DarkBrown RealEstate and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class PartyDocument(Document):
	def validate(self):
		# Normalise the ID number: strip spaces, keep it comparable across
		# agreements, cheques and ID copies (it is the primary key linking a
		# person's document set).
		if self.id_number:
			self.id_number = self.id_number.replace(" ", "").strip()
