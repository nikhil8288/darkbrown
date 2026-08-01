frappe.ui.form.on("Building", {
    refresh(frm) {
        if (frm.is_new()) return;

        frm.add_custom_button(__("Add Units"), () => open_unit_dialog(frm), __("Portfolio"));

        frm.add_custom_button(__("Unit Register"), () => {
            frappe.set_route("List", "Unit", { building: frm.doc.name });
        }, __("Portfolio"));

        if (frm.doc.status === "Onboarding" && !frm.doc.total_units) {
            frm.dashboard.add_comment(
                __("No units registered yet. Onboarding is not complete until the unit register matches the building."),
                "orange", true
            );
        }
    },
});

function open_unit_dialog(frm) {
    const d = new frappe.ui.Dialog({
        title: __("Add Units to {0}", [frm.doc.name]),
        fields: [
            {
                fieldname: "unit_numbers",
                fieldtype: "Small Text",
                label: __("Unit Numbers"),
                reqd: 1,
                description: __(
                    "One per line, or comma separated. Enter them exactly as they appear on the apartment doors — these are not generated."
                ),
            },
            { fieldtype: "Section Break" },
            {
                fieldname: "unit_type",
                fieldtype: "Select",
                label: __("Unit Type"),
                options: "\nStudio\n1BR\n2BR\n3BR\n4BR\nPenthouse\nVilla\nShop\nOffice\nWarehouse\nLabour Accommodation",
                description: __("Applied to every unit in this batch. Edit individually afterwards where they differ."),
            },
            { fieldtype: "Column Break" },
            { fieldname: "floor", fieldtype: "Data", label: __("Floor") },
            {
                fieldname: "status",
                fieldtype: "Select",
                label: __("Status"),
                options: "Not Ready\nVacant\nReserved\nOccupied\nUnder Maintenance",
                default: "Not Ready",
            },
        ],
        primary_action_label: __("Create Units"),
        primary_action(values) {
            frappe.call({
                method: "darkbrown.darkbrown.doctype.building.building.bulk_create_units",
                args: { building: frm.doc.name, ...values },
                freeze: true,
                freeze_message: __("Creating units..."),
                callback(r) {
                    if (!r.message) return;
                    const { created, skipped } = r.message;
                    let msg = __("{0} unit(s) created.", [created.length]);
                    if (skipped.length) {
                        msg += "<br>" + __("Skipped as already registered: {0}", [skipped.join(", ")]);
                    }
                    frappe.msgprint({ title: __("Units Added"), message: msg, indicator: "green" });
                    d.hide();
                    frm.reload_doc();
                },
            });
        },
    });
    d.show();
}
