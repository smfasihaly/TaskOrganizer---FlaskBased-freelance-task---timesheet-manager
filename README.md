# Task Organizer

A Flask-based time-tracking and reporting application with multi-user support, dynamic currency handling, exportable timesheets, and printable monthly reports.

---

## Features

* **Multi-User Authentication**

  * Register and log in/out
  * Soft-deletion of accounts (deactivation)

* **Per-User Currency Settings**

  * Users choose **report** and **payout** currencies on signup & in profile
  * Currency metadata loaded from `static/currencies.json`
  * Global Jinja helper `get_currency_symbol(code)` for symbols

* **Clients & Tasks Management**

  * Create, edit, soft-delete clients & tasks
  * Parent/child client hierarchy
  * Hourly, project, or monthly payment types

* **Timesheet Logging**

  * Log, edit, delete entries (soft-delete)
  * Mark entries as paid
  * Filter by client & month

* **Export to Excel (XLSX)**

  * One sheet per month (or single-month export)
  * Columns: Date, Task Short Name, Description, Hours, with a total row
  * Sheet named `mmm-YYYY` (e.g. `May-2025`)
  * Dates formatted as `DD-MMM-YYYY`

* **Printable Monthly Earnings Report**

  * Filterable by month(s) and client(s)
  * “Filters” card UI matching timesheet export styling
  * Print-only header, CSS-hidden controls on print
  * Shows earnings, paid, pending in both payout and report currency

* **UI & Styling**

  * Bootstrap 5 cards, pills, dropdowns, responsive tables
  * Consistent “Export” / “Filters” pills with border & background
  * Print scaling and print-only elements via CSS

---

## Installation

1. **Clone & enter project**

   ```bash
   git clone https://github.com/yourusername/task-organizer.git
   cd task-organizer
   ```

2. **Create virtualenv & install dependencies**

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate      # Linux/macOS
   .venv\Scripts\activate.bat     # Windows
   pip install -r requirements.txt
   ```

3. **Set up currency metadata**
   Ensure `static/currencies.json` exists with entries like:

   ```json
   {
     "USD": { "code":"USD", "name":"United States Dollar", "symbol":"$", "symbolNative":"$" },
     "EUR": { ... },
     ...
   }
   ```

4. **Run the app**

   ```bash
   flask run
   # or
   python app.py
   ```

   Visit `http://127.0.0.1:5000`

---

## Configuration

* **Secret key**:
  Edit `app.secret_key` in `app.py` for production.

* **Data storage**:
  Default uses `Data/freelance_organizer.xlsx`.
  Ensure write permissions; backed up on each save.

* **Exchange rate caching**:
  Cached per-currency for 1 hour to minimize API calls.

---

## Usage

1. **Register / Login**

   * Choose a default **report currency** (always USD on register)
   * Choose a **payout currency**

2. **Profile**

   * Update name, email, report & payout currencies, language, password

3. **Clients & Tasks**

   * Add top-level clients, then children under them
   * Set payment type & rate
   * Add tasks under child clients

4. **Timesheet**

   * Log hours: select “Client – Task” from autocomplete
   * Edit, delete, and mark entries paid
   * **Export** via the “Export Timesheet” pill, filtered by client/month

5. **Monthly Earnings**

   * Filter by month(s) + client(s) using the “Filters” pill
   * View summary table and totals
   * Print-friendly report via “Print PDF” button

---

## Development

* **Templates**: Jinja2 in `/templates`
* **Static assets**: `/static` (CSS, JS, currencies.json)
* **UI components**: Bootstrap 5 classes + custom `filter-tab` styles

---

## License

MIT © Your Name
