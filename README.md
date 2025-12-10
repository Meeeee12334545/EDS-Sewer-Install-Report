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
