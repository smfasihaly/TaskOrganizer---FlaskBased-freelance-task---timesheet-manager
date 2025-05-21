# TaskOrganizer

A self-contained Flask application for managing freelance clients, tasks, and timesheets—packaged as a single Windows executable.

## Features

- **Clients**: Parent/child hierarchy, hourly/monthly/project rates  
- **Tasks**: Create, status updates, Kanban board view  
- **Timesheet**: Log work hours, mark paid/unpaid  
- **Reports**: Month-wise earnings breakdown by parent & child  
- **Deployment**:  
  - Bundled via PyInstaller to `taskorganizer.exe`  
  - Includes `Data/freelance_organizer.xlsx` for persistent storage  
  - Auto-starts hidden with `launch_taskorganizer.vbs`  

## Installation

1. Clone or download this repo.  
2. Ensure `Data/freelance_organizer.xlsx` exists.
3. Run `dist/taskorganizer.exe` (no Python required).  
4. Navigate to `http://127.0.0.1:5000` in your browser.

## Development

```bash
# Activate venv
.venv\Scripts\Activate.bat

# Install dependencies
pip install -r requirements.txt

# Run locally
python app.py

# Re-bundle
pyinstaller --onefile --name taskorganizer \
  --add-data "templates;templates" \
  --add-data "static;static" \
  --add-data "Data;Data" \
  app.py
