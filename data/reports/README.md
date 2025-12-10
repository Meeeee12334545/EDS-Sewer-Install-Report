# Installation Reports Database

This directory contains completed sewer flow meter installation reports stored as JSON files.

## File Naming Convention

Reports are saved with the following naming pattern:
```
{project_name}_{site_name}_{timestamp}.json
```

For example:
```
Brisbane_Catchment_Site_MH123_20231210_143022.json
```

## File Structure

Each JSON file contains:
- Project details (name, client, catchment)
- Site information (name, ID, location, GPS coordinates)
- Installation details (date, time, meter info)
- Hydraulic assessment data
- Commissioning check results
- Photos and diagrams (base64 encoded)
- Calibration notes and ratings

## Usage

The Streamlit application provides functionality to:
- Save new reports to this directory
- Load and view existing reports
- Search and filter reports
- Export reports to PDF or Excel

## Version Control

All reports stored in this directory are tracked by Git, providing:
- Complete history of all installations
- Ability to track changes and updates
- Backup and recovery capabilities
