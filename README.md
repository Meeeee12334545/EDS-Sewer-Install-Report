# EDS Sewer Flow Meter Installation Report

A professional Streamlit application for creating standardised sewer flow meter installation reports for Environmental Data Services (EDS). The tool captures all site details, produces polished PDF/Excel exports, and now offers both Git-backed storage and optional direct uploads to GitHub via the API.

## Features

### 📝 Comprehensive Installation Reporting
 - Guided form covering project, site, hydraulic, and commissioning details
 - Interactive map with click-to-fill GPS coordinates and reverse geocoding
 - Supports device GPS (where available) and automatic address lookup
 - Photo and diagram uploads with captions for inclusion in reports

### 💾 Flexible Storage Options
 - **Local database**: Save completed reports as JSON inside `data/reports/` (tracked by Git for version history).
 - **GitHub upload (optional)**: Push a bundled JSON (metadata + base64 PDF) straight to a GitHub repository using the Contents API.

### 📄 Export Capabilities
 - Single-site PDF export with embedded metadata
 - Excel exports for collections of sites
 - Bulk PDF/Excel exports of saved reports
 - Static site maps and photo pages in generated PDFs

### 🔍 Saved Reports Dashboard
 - Search, sort, and filter saved installations
 - Reload a saved report back into the form for editing
 - One-click delete, PDF, and Excel options for each saved record

## Installation

### Requirements

```text
streamlit
reportlab
pandas
folium
streamlit-folium
staticmap
streamlit-js-eval
openpyxl
PyPDF2
geopy
requests
```

### Setup
1. Clone this repository.
2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Run the Streamlit application:

   ```bash
   streamlit run app.py
   ```

## Usage Workflow

### Creating a new installation record
1. Use the interactive map (or device GPS) to populate the site coordinates.
2. Complete the project, site, hydraulic, meter, and commissioning sections.
3. Attach photos and diagrams with optional captions.
4. Click **Add site to current project** to stage the site for exporting or storage.

### Working with saved reports
1. Navigate to **📚 Saved Reports Database**.
2. Search or filter by project, site, or client.
3. For each saved report you can:
   - **📥 Load to form** for further edits.
   - **📄 PDF** to regenerate a report.
   - **📊 Excel** to export to spreadsheet.
   - **🗑️ Delete** to remove unwanted entries.

### Bulk exports
- Export filtered reports to a single Excel workbook.
- Export filtered reports to a combined PDF document.

## Storage Options

### Git-backed local database (default)
1. After staging a site, select it from **Current Sites in Project**.
2. Click **💾 Save to database** to persist the JSON record in `data/reports/`.
3. Commit the generated JSON files to version them with Git:

   ```bash
   git add data/reports/
   git commit -m "Add installation report for <site name>"
   git push
   ```

### Direct GitHub uploads (optional)
1. Create a personal access token with `repo` (or at least `contents:write`) scope.
2. Provide the token using one of the following patterns:
   - Populate the `.env` file (placeholder included) with `GITHUB_REPORT_TOKEN`.
   - Export `GITHUB_REPORT_TOKEN` in your shell before launching Streamlit.
   - Supply `st.secrets["github_report_token"]` when deploying on Streamlit Cloud.
3. (Optional) prefill defaults with:
   - `GITHUB_REPORT_REPO` – e.g. `your-org/install-reports`
   - `GITHUB_REPORT_BRANCH` – defaults to `main`
   - `GITHUB_REPORT_FOLDER` – defaults to `reports`
4. In **GitHub Storage**, choose the repository, branch, and folder, then click **⬆️ Upload selected site bundle to GitHub**.

Each upload stores a JSON bundle containing the site metadata and the base64-encoded PDF directly in the target repository.

## Database Structure

Saved reports use the naming convention `{project_name}_{site_name}_{timestamp}.json` and contain:
- All form field data
- Base64-encoded photos and diagrams
- Calculated hydraulic values and metadata

Because the directory is version-controlled you get:
- ✅ Full history of every installation
- ✅ Backup and recovery via GitHub
- ✅ Collaboration across the team
- ✅ An auditable change trail

## Testing

Run the full suite:

```bash
pytest
```

Or execute individual modules:

```bash
python -m unittest tests/test_database_functions.py -v
python -m unittest tests/test_merge_photo_records.py -v
python -m unittest tests/test_github_storage.py -v
```

## Project structure

```
.
├── app.py                          # Main Streamlit application
├── data/
│   └── reports/                    # Saved installation reports (JSON)
├── tests/
│   ├── test_database_functions.py  # Database functionality tests
│   ├── test_github_storage.py      # GitHub upload helpers tests
│   └── test_merge_photo_records.py # Photo merging tests
├── requirements.txt                # Python dependencies
├── runtime.txt                     # Python version specification
└── README.md                       # Project documentation
```

## License & Support

Proprietary – Environmental Data Services. For issues or questions, please contact the EDS support team.
