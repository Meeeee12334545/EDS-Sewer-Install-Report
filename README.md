<<<<<<< HEAD
# EDS Sewer Flow Meter Installation Report

A professional Streamlit application for creating standardized sewer flow meter installation reports for Environmental Data Services (EDS).

## Features

### 📝 Comprehensive Installation Reporting
- Project and site details tracking
- Location and GPS coordinates with interactive map
- Pipe and hydraulic assessment
- Meter, sensor, and configuration details
- Commissioning checks and verification readings
- Calibration suitability ratings
- Photo and diagram uploads

### 💾 Database Storage
- **NEW**: Save completed reports to GitHub repository
- All reports stored as JSON files in `data/reports/`
- Version-controlled with Git for complete history
- Search and filter saved reports
- Load existing reports for editing
- Bulk export capabilities

### 📄 Export Capabilities
- Generate professional PDF reports
- Export data to Excel spreadsheets
- Single-site or multi-site exports
- Embedded metadata for data integrity

### 🗺️ Interactive Features
- Click-to-select GPS coordinates on map
- Automatic address lookup from GPS
- Device GPS support (where available)
- Visual site location maps in PDF reports

## Installation

### Requirements
```
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
```

### Setup
1. Clone this repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the application:
   ```bash
   streamlit run app.py
   ```

## Usage

### Creating a New Report
1. Use the interactive map to select the installation location
2. Fill in the site details form with:
   - Project information (name, client, catchment)
   - Site details (name, ID, GPS, address)
   - Pipe and hydraulic assessment
   - Meter and sensor configuration
   - Commissioning checks
   - Photos and diagrams
3. Click "Add site to current project"

### Saving Reports to Database
1. After adding a site to the current project
2. Select the site from the "Current Sites in Project" list
3. Click **💾 Save to database**
4. The report is saved as a JSON file in `data/reports/`
5. The file is automatically tracked by Git

### Viewing Saved Reports
1. Scroll to the "📚 Saved Reports Database" section
2. Browse all saved reports
3. Use the search box to filter by project, site, or client
4. Sort reports by date, project, or site name
5. For each report you can:
   - **📥 Load to form**: Load the report for editing
   - **📄 PDF**: Export to PDF
   - **📊 Excel**: Export to Excel
   - **🗑️ Delete**: Remove from database

### Bulk Operations
- Export all filtered reports to a single Excel file
- Export all filtered reports to a combined PDF document

## Database Structure

Reports are stored in the `data/reports/` directory with the naming convention:
```
{project_name}_{site_name}_{timestamp}.json
```

Each JSON file contains:
- All form field data
- Base64-encoded photos and diagrams
- Calculated flow and hydraulic values
- Metadata (prepared by, reviewed by, dates)

Since this directory is tracked by Git:
- ✅ Complete version history of all installations
- ✅ Backup and recovery capabilities
- ✅ Collaboration and sharing via GitHub
- ✅ Audit trail for compliance

## Git Workflow

The database storage integrates seamlessly with Git:

1. **After saving a report**: The JSON file is created in `data/reports/`
2. **Commit your changes**: 
   ```bash
   git add data/reports/
   git commit -m "Add installation report for Site XYZ"
   git push
   ```
3. **Your reports are now**: Backed up to GitHub and version controlled

## Testing

Run the test suite:
```bash
python -m pytest tests/
```

Or run individual tests:
```bash
python -m unittest tests/test_database_functions.py -v
python -m unittest tests/test_merge_photo_records.py -v
```

## Project Structure

```
.
├── app.py                          # Main Streamlit application
├── data/
│   └── reports/                    # Saved installation reports (JSON)
│       ├── README.md              # Database documentation
│       └── *.json                 # Individual report files
├── tests/
│   ├── test_database_functions.py # Database functionality tests
│   └── test_merge_photo_records.py # Photo merging tests
├── requirements.txt               # Python dependencies
├── runtime.txt                    # Python version specification
└── README.md                      # This file
```

## License

Proprietary - Environmental Data Services

## Support

For issues or questions, please contact EDS support.
=======
# EDS Sewer Installation Report

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

## Managing reports

### Saving to the Git-backed database (default)
1. Complete the form and click **“Add site to current project.”**
2. Select the site from **Current Sites in Project** and click **💾 Save to database**.
3. Reports are stored as JSON files under `data/reports/` and automatically versioned by Git.
4. Use the **📚 Saved Reports Database** section to search, filter, reload, export, or delete saved reports.

### Uploading directly to GitHub (optional)
1. Create a personal access token with `repo` scope (or at least `contents:write`).
2. Expose the token using one of the following methods:
   - Add it to the `.env` file (placeholder provided) as `GITHUB_REPORT_TOKEN`.
   - Export it in your shell before launching Streamlit: `export GITHUB_REPORT_TOKEN=...`.
   - Supply it via `st.secrets["github_report_token"]` when deploying on Streamlit Cloud.
3. (Optional) set defaults:
   - `GITHUB_REPORT_REPO` – e.g. `your-org/install-reports`
   - `GITHUB_REPORT_BRANCH` – defaults to `main`
   - `GITHUB_REPORT_FOLDER` – defaults to `reports`
4. In the **GitHub Storage** panel, select the target repository/branch/folder and click **⬆️ Upload selected site bundle to GitHub**.

Each upload commits a JSON bundle (site metadata plus base64 PDF) to the specified repository via the GitHub Contents API.

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

>>>>>>> 85dcda8 (Add GitHub storage for reports)
