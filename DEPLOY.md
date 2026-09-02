# Read the documents — onboarding extraction

Four files. Unzip over the repo root, commit, push, then on the bench:

    bench --site erp.darkbrown.qa migrate
    bench build
    bench clear-cache
    bench restart

## Before it will read anything

The extractor needs an Anthropic key. Either:

- `site_config.json` → `"anthropic_api_key": "sk-ant-..."`  (takes precedence), or
- **DBR Settings → Document reading → Anthropic API key** (new field, encrypted).

With no key, pressing Read returns "Anthropic API key is not configured"
before any file is sent anywhere. The wizard still works by hand.

## Files

| File | Change |
|---|---|
| `darkbrown/api/doc_intake.py` | new `extract_for_wizard()` — reads a set of files and returns wizard field values with confidence and source |
| `darkbrown/api/doc_intake_prompts.py` | schema gained `building_name`, `floors`, `total_units`, `annual_rent` |
| `darkbrown/shell/index.html` | Documents step gained a Read button and a review panel |
| `.../dbr_settings.json` | `anthropic_api_key` field |

## What it does not do

- The tenant and cheque wizards still only attach. Their field maps are not written.
- Cheque rows are read and counted but not created. Cheques are still logged from the Cheques screen.
- Each file read is also uploaded a second time on save, as the Building's own
  attachment. The reading copy lives in the Document Register.
