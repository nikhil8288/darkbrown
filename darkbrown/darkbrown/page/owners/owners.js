frappe.pages['owners'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Owners and Shareholders',
		single_column: true,
	});

	const waiting = ["Clean separation of drawings from operating cost in the ledger", "Q11 \u2014 the reserve denominator", "Q21 \u2014 equity against shareholder loan", "Q24 \u2014 how cash and ATM withdrawals are classified"];
	const planned = ["Distribution policy and the variable target", "Three-month reserve gate, soft-blocking with MD override", "Owner current accounts on a dated shareholding model", "Distribution runs through GM and MD approval", "Suspense for unclassified withdrawals, blocking month close"];

	$(page.body).html(`
		<div class="db-stub">
			<div class="db-stub-tag">Not built yet</div>
			<h2>Owners and Shareholders</h2>
			<p class="db-stub-lead">Owner drawings, the reserve gate and distribution runs. Specified in Bible Addendum 2.4. Held out of this build because the reserve floor cannot be computed until operating cost is clean of owner withdrawals.</p>

			<div class="db-stub-grid">
				<div>
					<h5>What goes here</h5>
					<ul>${planned.map(x => `<li>${x}</li>`).join('')}</ul>
				</div>
				<div>
					<h5>Waiting on</h5>
					<ul>${waiting.map(x => `<li>${x}</li>`).join('')}</ul>
				</div>
			</div>
		</div>
		<style>
		.db-stub { max-width: 860px; padding: 28px 4px 60px; }
		.db-stub-tag { display:inline-block; font-size:11px; letter-spacing:.08em;
			text-transform:uppercase; color:#8a6f3f; border:1px solid #e0d6c2;
			background:#faf6ee; border-radius:3px; padding:3px 9px; margin-bottom:14px; }
		.db-stub h2 { margin:0 0 10px; font-weight:600; }
		.db-stub-lead { color:var(--text-muted); max-width:60ch; line-height:1.6; }
		.db-stub-grid { display:grid; grid-template-columns:1fr 1fr; gap:34px;
			margin-top:30px; padding-top:24px; border-top:1px solid var(--border-color); }
		.db-stub-grid h5 { font-size:11px; letter-spacing:.07em; text-transform:uppercase;
			color:var(--text-muted); margin:0 0 10px; }
		.db-stub-grid ul { margin:0; padding-left:18px; line-height:1.85; }
		.db-stub-grid li { color:var(--text-color); }
		@media (max-width:720px) { .db-stub-grid { grid-template-columns:1fr; gap:22px; } }
		</style>
	`);
};
