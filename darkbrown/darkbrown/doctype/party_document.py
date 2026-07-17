{
 "actions": [],
 "allow_rename": 1,
 "autoname": "format:DOC-{YYYY}-{#####}",
 "creation": "2026-07-13 00:00:00.000000",
 "doctype": "DocType",
 "engine": "InnoDB",
 "field_order": [
  "sec_intake",
  "document_type",
  "status",
  "col_intake_1",
  "source_file",
  "page_count",
  "sec_classify",
  "detected_type",
  "extraction_confidence",
  "col_classify_1",
  "extracted_on",
  "extractor_model",
  "sec_contract",
  "party_name",
  "party_name_ar",
  "id_number",
  "nationality",
  "cr_number",
  "col_contract_1",
  "counterparty_name",
  "counterparty_id",
  "contract_ref_no",
  "sec_property",
  "building_no",
  "zone",
  "street",
  "area_name",
  "col_property_1",
  "unit_no",
  "electricity_no",
  "water_no",
  "sec_terms",
  "monthly_rent",
  "security_deposit",
  "col_terms_1",
  "start_date",
  "end_date",
  "cheques_per_year",
  "sec_cheques",
  "cheques",
  "sec_review",
  "reviewed_by",
  "reviewed_on",
  "col_review_1",
  "pushed_refs",
  "sec_audit",
  "raw_json",
  "extraction_notes"
 ],
 "fields": [
  {
   "fieldname": "sec_intake",
   "fieldtype": "Section Break",
   "label": "Intake"
  },
  {
   "default": "Unknown",
   "fieldname": "document_type",
   "fieldtype": "Select",
   "in_list_view": 1,
   "in_standard_filter": 1,
   "label": "Document Type",
   "options": "Unknown\nCheque Batch\nLandlord Contract\nTenant Agreement\nOwner Contract\nPassport\nQID / National ID\nUtility / Other",
   "reqd": 1
  },
  {
   "default": "Draft",
   "fieldname": "status",
   "fieldtype": "Select",
   "in_list_view": 1,
   "in_standard_filter": 1,
   "label": "Status",
   "options": "Draft\nExtracting\nNeeds Review\nConfirmed\nPushed\nRejected",
   "read_only": 1
  },
  {
   "fieldname": "col_intake_1",
   "fieldtype": "Column Break"
  },
  {
   "fieldname": "source_file",
   "fieldtype": "Attach",
   "label": "Source Document",
   "reqd": 1
  },
  {
   "fieldname": "page_count",
   "fieldtype": "Int",
   "label": "Pages",
   "read_only": 1
  },
  {
   "collapsible": 1,
   "fieldname": "sec_classify",
   "fieldtype": "Section Break",
   "label": "Classification"
  },
  {
   "fieldname": "detected_type",
   "fieldtype": "Data",
   "label": "Detected Type (AI)",
   "read_only": 1
  },
  {
   "fieldname": "extraction_confidence",
   "fieldtype": "Float",
   "label": "Overall Confidence",
   "precision": "2",
   "read_only": 1
  },
  {
   "fieldname": "col_classify_1",
   "fieldtype": "Column Break"
  },
  {
   "fieldname": "extracted_on",
   "fieldtype": "Datetime",
   "label": "Extracted On",
   "read_only": 1
  },
  {
   "fieldname": "extractor_model",
   "fieldtype": "Data",
   "label": "Model Used",
   "read_only": 1
  },
  {
   "depends_on": "eval:['Landlord Contract','Tenant Agreement','Owner Contract'].includes(doc.document_type)",
   "fieldname": "sec_contract",
   "fieldtype": "Section Break",
   "label": "Parties"
  },
  {
   "fieldname": "party_name",
   "fieldtype": "Data",
   "label": "Party Name (EN)"
  },
  {
   "fieldname": "party_name_ar",
   "fieldtype": "Data",
   "label": "Party Name (AR)"
  },
  {
   "fieldname": "id_number",
   "fieldtype": "Data",
   "label": "QID / ID No"
  },
  {
   "fieldname": "nationality",
   "fieldtype": "Data",
   "label": "Nationality"
  },
  {
   "fieldname": "cr_number",
   "fieldtype": "Data",
   "label": "CR No"
  },
  {
   "fieldname": "col_contract_1",
   "fieldtype": "Column Break"
  },
  {
   "fieldname": "counterparty_name",
   "fieldtype": "Data",
   "label": "Counterparty Name"
  },
  {
   "fieldname": "counterparty_id",
   "fieldtype": "Data",
   "label": "Counterparty ID"
  },
  {
   "fieldname": "contract_ref_no",
   "fieldtype": "Data",
   "label": "Contract Reference No"
  },
  {
   "depends_on": "eval:['Landlord Contract','Tenant Agreement','Owner Contract'].includes(doc.document_type)",
   "fieldname": "sec_property",
   "fieldtype": "Section Break",
   "label": "Property"
  },
  {
   "fieldname": "building_no",
   "fieldtype": "Data",
   "label": "Building No"
  },
  {
   "fieldname": "zone",
   "fieldtype": "Data",
   "label": "Zone"
  },
  {
   "fieldname": "street",
   "fieldtype": "Data",
   "label": "Street"
  },
  {
   "fieldname": "area_name",
   "fieldtype": "Data",
   "label": "Area"
  },
  {
   "fieldname": "col_property_1",
   "fieldtype": "Column Break"
  },
  {
   "fieldname": "unit_no",
   "fieldtype": "Data",
   "label": "Unit / Room No"
  },
  {
   "fieldname": "electricity_no",
   "fieldtype": "Data",
   "label": "Electricity No"
  },
  {
   "fieldname": "water_no",
   "fieldtype": "Data",
   "label": "Water No"
  },
  {
   "depends_on": "eval:['Landlord Contract','Tenant Agreement','Owner Contract'].includes(doc.document_type)",
   "fieldname": "sec_terms",
   "fieldtype": "Section Break",
   "label": "Terms"
  },
  {
   "fieldname": "monthly_rent",
   "fieldtype": "Currency",
   "label": "Monthly Rent",
   "options": "QAR"
  },
  {
   "fieldname": "security_deposit",
   "fieldtype": "Currency",
   "label": "Security Deposit",
   "options": "QAR"
  },
  {
   "fieldname": "col_terms_1",
   "fieldtype": "Column Break"
  },
  {
   "fieldname": "start_date",
   "fieldtype": "Date",
   "label": "Start Date"
  },
  {
   "fieldname": "end_date",
   "fieldtype": "Date",
   "label": "End Date"
  },
  {
   "fieldname": "cheques_per_year",
   "fieldtype": "Int",
   "label": "Cheques Per Year"
  },
  {
   "depends_on": "eval:doc.document_type=='Cheque Batch'",
   "fieldname": "sec_cheques",
   "fieldtype": "Section Break",
   "label": "Cheques Detected"
  },
  {
   "fieldname": "cheques",
   "fieldtype": "Table",
   "label": "Cheques",
   "options": "Document Register Cheque"
  },
  {
   "collapsible": 1,
   "fieldname": "sec_review",
   "fieldtype": "Section Break",
   "label": "Review"
  },
  {
   "fieldname": "reviewed_by",
   "fieldtype": "Link",
   "label": "Reviewed By",
   "options": "User",
   "read_only": 1
  },
  {
   "fieldname": "reviewed_on",
   "fieldtype": "Datetime",
   "label": "Reviewed On",
   "read_only": 1
  },
  {
   "fieldname": "col_review_1",
   "fieldtype": "Column Break"
  },
  {
   "fieldname": "pushed_refs",
   "fieldtype": "Small Text",
   "label": "Pushed Records",
   "read_only": 1
  },
  {
   "collapsible": 1,
   "collapsible_depends_on": "eval:false",
   "fieldname": "sec_audit",
   "fieldtype": "Section Break",
   "label": "Audit (raw extraction)"
  },
  {
   "fieldname": "raw_json",
   "fieldtype": "Code",
   "label": "Raw Extraction JSON",
   "options": "JSON",
   "read_only": 1
  },
  {
   "fieldname": "extraction_notes",
   "fieldtype": "Small Text",
   "label": "Extraction Notes / Flags",
   "read_only": 1
  }
 ],
 "index_web_pages_for_search": 1,
 "links": [],
 "modified": "2026-07-17 10:00:00.000000",
 "module": "Darkbrown",
 "name": "Document Register",
 "owner": "Administrator",
 "permissions": [
  {
   "create": 1,
   "delete": 0,
   "email": 1,
   "export": 1,
   "print": 1,
   "read": 1,
   "report": 1,
   "role": "Legal and Documentation",
   "share": 1,
   "write": 1
  },
  {
   "create": 1,
   "delete": 1,
   "email": 1,
   "export": 1,
   "print": 1,
   "read": 1,
   "report": 1,
   "role": "System Manager",
   "share": 1,
   "write": 1
  },
  {
   "create": 0,
   "delete": 0,
   "email": 0,
   "export": 1,
   "print": 1,
   "read": 1,
   "report": 1,
   "role": "Managing Director",
   "share": 0,
   "write": 0
  }
 ],
 "sort_field": "modified",
 "sort_order": "DESC",
 "states": [],
 "track_changes": 1
}