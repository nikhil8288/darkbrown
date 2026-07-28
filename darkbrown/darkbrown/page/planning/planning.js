frappe.pages['planning'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Planning',
		single_column: true,
	});

	const waiting = ["A full period of posted operational data", "Q10 \u2014 excess cash as a stock or a flow", "Q14 \u2014 the cash-impact threshold that sends a scenario to the MD"];
	const planned = ["Forecast and scenario workspace", "Capacity curve and building models", "Targets and planning actions", "Forecast against actual", "Digital CFO, with every number traced to a governed service"];

	$(page.body).html(`
		<div class="db-stub">
			<div class="db-stub-tag">Not built yet</div>
			<h2>Planning</h2>
			<p class="db-stub-lead">Scenario modelling, the capacity curve and the Digital CFO. Specified in Bible Addendum 2.3 but held out of this build: planning reads from the operational record, so it cannot be built before that record exists.</p>

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
