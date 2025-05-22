import os
import uuid
from datetime import datetime

import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = 'replace-with-a-secure-random-key'

EXCEL_FILE = os.path.join('Data', 'freelance_organizer.xlsx')


import requests

def fetch_eur_rate( timeout: float = 5.0) -> float:
    """
    Calls the given API URL (which returns a JSON with a top‐level "data" dict),
    and returns the value of data["EUR"] as a float.
    Raises on network errors or if the EUR key is missing.
    """
    # resp = requests.get('https://api.freecurrencyapi.com/v1/latest?apikey=fca_live_TXHyYNYOZIxnOQCyToD5WhRHTr6GGm8u105Xafbk', timeout=timeout)
    resp = requests.get('https://www.floatrates.com/daily/usd.json', timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()
    eur = payload.get("eur").get("rate")
    if eur is None:
        raise KeyError("EUR rate not found in API response")
    return float(eur)


def load_data():
    """
    Load or initialize the three sheets:
    - Clients: ClientID, ClientName, ParentID, PaymentType, 'ProjectRate'
    - Tasks:   TaskID, ClientID, TaskDescription, CreatedDate, Status, ShortName
    - Timesheet: EntryID, TaskID, Date, Hours, Description, Paid
    """
    client_cols = ['ClientID', 'ClientName', 'ParentID', 'PaymentType','ProjectRate']
    task_cols   = ['TaskID', 'ClientID', 'TaskDescription', 'CreatedDate', 'Status', 'ShortName']
    ts_cols     = ['EntryID', 'TaskID', 'Date', 'Hours', 'Description', 'Paid']

    if os.path.exists(EXCEL_FILE):
        xls = pd.ExcelFile(EXCEL_FILE, engine='openpyxl')
        # Clients
        clients = pd.read_excel(xls, 'Clients') if 'Clients' in xls.sheet_names \
                  else pd.DataFrame(columns=client_cols)
        # Tasks
        tasks   = pd.read_excel(xls, 'Tasks')   if 'Tasks' in xls.sheet_names   \
                  else pd.DataFrame(columns=task_cols)
        # Timesheet
        ts      = pd.read_excel(xls, 'Timesheet') if 'Timesheet' in xls.sheet_names \
                  else pd.DataFrame(columns=ts_cols)
    else:
        clients = pd.DataFrame(columns=client_cols)
        tasks   = pd.DataFrame(columns=task_cols)
        ts      = pd.DataFrame(columns=ts_cols)

    clients['ParentID'] = clients.get('ParentID', '').fillna('')
    clients['PaymentType']   = clients['PaymentType'].fillna('Hourly')
    clients['PaymentAmount'] = clients['PaymentAmount'].fillna(0.0)

    if 'Status'   not in tasks.columns: tasks['Status'] = 'Pending'
    if 'ShortName' not in tasks.columns: tasks['ShortName'] = ''
    if 'CreatedDate' not in tasks.columns: tasks['CreatedDate'] = ''

    ts['Paid']        = ts.get('Paid', False)
    ts['Hours']       = ts.get('Hours', 0.0)
    ts['Description'] = ts.get('Description', '').fillna('')
    ts['Date']        = ts.get('Date', '').fillna('')

    return clients, tasks, ts


def save_data(clients, tasks, ts):
    """
    Write all three DataFrames back to the Excel file.
    """
    os.makedirs(os.path.dirname(EXCEL_FILE), exist_ok=True)
    with pd.ExcelWriter(EXCEL_FILE, engine='openpyxl') as writer:
        clients.to_excel(writer, sheet_name='Clients', index=False)
        tasks  .to_excel(writer, sheet_name='Tasks',   index=False)
        ts     .to_excel(writer, sheet_name='Timesheet', index=False)


@app.route('/')
def home():
    return redirect(url_for('view_tasks'))


# ——— Clients ——————————————————————————————————————————————

@app.route('/clients')
def view_clients():
    clients, tasks, ts = load_data()
    # Build a map for parent lookups
    clients_map = {c.ClientID: c.ClientName for _, c in clients.iterrows()}
    return render_template(
        'view_clients.html',
        clients=clients.to_dict('records'),
        clients_map=clients_map
    )


@app.route('/clients/add', methods=['GET','POST'])
def add_client():
    clients, tasks, ts = load_data()
    parent_clients = clients[clients.ParentID==''].to_dict('records')

    if request.method == 'POST':
        name        = request.form['name'].strip()
        parent_id   = request.form.get('parent_id','')
        if not name:
            flash('Client name is required.', 'danger')
            return redirect(url_for('add_client'))

        # Default to no payment if no parent
        payment_type   = 'Hourly'
        payment_amount = 0.0

        if parent_id:
            # read rate type & amount
            payment_type   = request.form.get('rate_type','Hourly')
            payment_amount = float(request.form.get('rate_amount',0) or 0)

        cid = str(uuid.uuid4())
        idx = len(clients)
        clients.loc[idx, ['ClientID','ClientName','ParentID','PaymentType','PaymentAmount']] = [
            cid, name, parent_id, payment_type, payment_amount
        ]
        save_data(clients, tasks, ts)
        flash('Client added successfully.', 'success')
        return redirect(url_for('view_clients'))

    return render_template('add_client.html', clients=parent_clients)
@app.route('/clients/<client_id>/edit', methods=['GET','POST'])
def edit_client(client_id):
    clients, tasks, ts = load_data()
    row = clients[clients.ClientID==client_id]
    if row.empty:
        flash('Client not found.', 'warning')
        return redirect(url_for('view_clients'))

    parent_clients = clients[(clients.ParentID=='') & (clients.ClientID!=client_id)].to_dict('records')
    client = row.iloc[0]

    if request.method == 'POST':
        name        = request.form['name'].strip()
        parent_id   = request.form.get('parent_id','')
        if not name:
            flash('Client name is required.', 'danger')
            return redirect(url_for('edit_client', client_id=client_id))

        payment_type   = 'Hourly'
        payment_amount = 0.0
        if parent_id:
            payment_type   = request.form.get('rate_type','Hourly')
            payment_amount = float(request.form.get('rate_amount',0) or 0)

        mask = clients.ClientID == client_id
        clients.loc[mask, 'ClientName']    = name
        clients.loc[mask, 'ParentID']      = parent_id
        clients.loc[mask, 'PaymentType']   = payment_type
        clients.loc[mask, 'PaymentAmount'] = payment_amount

        save_data(clients, tasks, ts)
        flash('Client updated successfully.', 'success')
        return redirect(url_for('view_clients'))

    return render_template(
        'edit_client.html',
        clients=parent_clients,
        client=client
    )


# ——— Tasks ———————————————————————————————————————————————

@app.route('/tasks')
def view_tasks():
    clients, tasks, ts = load_data()
    merged = tasks.merge(
        clients[['ClientID', 'ClientName']],
        on='ClientID', how='left'
    ).rename(columns={'ClientName': 'Client'})
    return render_template(
        'view_tasks.html',
        tasks=merged.to_dict('records')
    )


@app.route('/tasks/add', methods=['GET', 'POST'])
def add_task():
    clients, tasks, ts = load_data()
    # Only child clients for dropdown
    clients['ParentID'] = clients['ParentID'].fillna('')
    child_clients = clients[clients['ParentID'] != ''].to_dict('records')

    if request.method == 'POST':
        client_id  = request.form['client_id']
        short_name = request.form['short_name'].strip()
        desc       = request.form['description'].strip()

        if not desc:
            flash('Task description is required.', 'danger')
            return redirect(url_for('add_task'))

        tid = str(uuid.uuid4())
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        tasks.loc[len(tasks)] = [
            tid, client_id, desc, now, 'Pending', short_name
        ]

        save_data(clients, tasks, ts)
        flash('Task added successfully.', 'success')
        return redirect(url_for('view_tasks'))

    return render_template(
        'add_task.html',
        clients=child_clients
    )


@app.route('/tasks/<task_id>/update', methods=['GET', 'POST'])
def update_status(task_id):
    clients, tasks, ts = load_data()
    row = tasks.loc[tasks.TaskID == task_id]
    if row.empty:
        flash('Task not found.', 'warning')
        return redirect(url_for('view_tasks'))

    if request.method == 'POST':
        if request.is_json:
            data = request.get_json(silent=True) or {}
            new_status = data.get('status')
        else:
            new_status = request.form.get('status')
        tasks.loc[tasks.TaskID == task_id, 'Status'] = new_status
        save_data(clients, tasks, ts)
        flash('Status updated.', 'info')
        return redirect(url_for('view_tasks'))

    current = row.Status.iloc[0]
    client  = clients.loc[clients.ClientID == row.ClientID.iloc[0], 'ClientName'].iloc[0]
    desc    = row.TaskDescription.iloc[0]
    return render_template(
        'update_status.html',
        task_id=task_id,
        current_status=current,
        client=client,
        description=desc
    )


# ——— Timesheet ————————————————————————————————————————————

@app.route('/timesheet/log', methods=['GET', 'POST'])
def log_hours():
    clients, tasks, ts = load_data()
    merged = (
        tasks
        .merge(clients[['ClientID','ClientName']], on='ClientID', how='left')
        .rename(columns={'ClientName':'Client'})
    )

    if request.method == 'POST':
        selected = request.form['task_input'].strip()
        display  = (
            merged['Client'].astype(str)
                  .add(' – ')
                  .add(merged['TaskDescription'].astype(str))
        )
        mask = display == selected
        if not mask.any():
            flash('Please choose a valid task.', 'danger')
            return redirect(url_for('log_hours'))
        task_id = merged.loc[mask, 'TaskID'].iloc[0]

        date = request.form.get('date') or datetime.now().strftime('%Y-%m-%d')
        try:
            hrs = float(request.form['hours'])
            assert hrs > 0
        except:
            flash('Enter a valid number of hours.', 'danger')
            return redirect(url_for('log_hours'))

        desc = request.form.get('description','').strip()
        eid  = str(uuid.uuid4())
        ts.loc[len(ts)] = [eid, task_id, date, hrs, desc, False]
        save_data(clients, tasks, ts)

        flash('Logged hours successfully.', 'success')
        return redirect(url_for('view_timesheet'))

    initial_task_display = ''
    qid = request.args.get('task_id')
    if qid:
        row = merged.loc[merged.TaskID == qid]
        if not row.empty:
            initial_task_display = (
                f"{row.iloc[0]['Client']} – {row.iloc[0]['TaskDescription']}"
            )

    initial_date = datetime.now().strftime('%Y-%m-%d')

    return render_template(
        'log_hours.html',
        tasks=merged.to_dict('records'),
        initial_task_display=initial_task_display,
        initial_date=initial_date
    )


@app.route('/timesheet')
def view_timesheet():
    clients, tasks, ts = load_data()

    # Build lookups
    clients['ParentID'] = clients['ParentID'].fillna('')
    name_map   = clients.set_index('ClientID')['ClientName'].to_dict()
    parent_map = clients.set_index('ClientID')['ParentID'].to_dict()

    # Merge Timesheet → Tasks → Clients
    df = (
        ts[['EntryID','TaskID','Date','Hours','Description','Paid']]
        .merge(tasks[['TaskID','ClientID','ShortName','TaskDescription']],
               on='TaskID', how='left')
        .merge(clients[['ClientID','ClientName']],
               on='ClientID', how='left')
    )
    df['Date'] = pd.to_datetime(df['Date']).dt.strftime('%Y-%m-%d')

    # Now for each row, determine its top-level parent
    def find_parent(cid):
        pid = parent_map.get(cid, '')
        return pid if pid else cid

    df['ParentID'] = df['ClientID'].apply(find_parent)

    # Group rows by Parent then by Child
    nested = []
    for parent_id, pdf in df.groupby('ParentID'):
        parent_name = name_map.get(parent_id, '—')
        children = []
        for child_id, cdf in pdf.groupby('ClientID'):
            child_name = name_map.get(child_id, '—')
            entries = cdf.to_dict('records')
            children.append({
                'ClientID':   child_id,
                'ClientName': child_name,
                'Entries':    entries
            })
        nested.append({
            'ParentID':   parent_id,
            'ParentName': parent_name,
            'Children':   children
        })

    return render_template('view_timesheet.html', groups=nested)

def view_timesheet():
    # 1) Load all sheets
    clients, tasks, ts = load_data()

    # 2) Make sure our task text fields are strings
    tasks['TaskDescription'] = tasks['TaskDescription'].astype(str)
    tasks['ShortName']       = tasks['ShortName'].astype(str)

    # 3) Merge Timesheet → Tasks → Clients
    df = (
        ts
        .merge(
            tasks[['TaskID','TaskDescription','ShortName','ClientID']],
            on='TaskID', how='left'
        )
        .merge(
            clients[['ClientID','ClientName']],
            on='ClientID', how='left'
        )
    )

    # 4) Fill any NaNs so we never get floats where strings are expected
    df = df.fillna({
        'Date': '',
        'Hours': 0.0,
        'Description': '',
        'TaskDescription': '',
        'ShortName': '',
        'ClientName': ''
    })

    # 5) Build the list of entry‐dicts
    entries = df.to_dict('records')

    # 6) Render
    return render_template('view_timesheet.html', entries=entries)


@app.route('/timesheet/mark_paid/<entry_id>', methods=['POST'])
def mark_paid(entry_id):
    clients, tasks, ts = load_data()
    ts.loc[ts.EntryID == entry_id, 'Paid'] = True
    save_data(clients, tasks, ts)
    flash('Entry marked paid.', 'success')
    return redirect(url_for('view_timesheet'))

@app.route('/reports/monthly')
def monthly_summary():
    clients, tasks, ts = load_data()

    # Normalize ParentID & lookups
    clients['ParentID'] = clients['ParentID'].fillna('')
    name_map = clients.set_index('ClientID')['ClientName'].to_dict()
    children = (
        clients[clients.ParentID!='']
               .groupby('ParentID')['ClientID']
               .apply(list)
               .to_dict()
    )

    # 1) Merge Timesheet → Tasks → Clients (including PaymentType & PaymentAmount)
    df = (
        ts[['TaskID','Date','Hours','Paid']]
        .merge(tasks[['TaskID','ClientID']], on='TaskID', how='left')
        .merge(clients[['ClientID','PaymentType','PaymentAmount']], # bring in rates
               on='ClientID', how='left')
    )
    df['Date']   = pd.to_datetime(df['Date'])
    df['Month']  = df['Date'].dt.to_period('M').astype(str)
    df['Hours']  = df['Hours'].fillna(0.0)

    # 2) Earnings logic: Monthly OR Project → flat PaymentAmount once if any hours
    def compute_earn(r):
        if r['PaymentType'] in ('Monthly','Project') and r['Hours'] > 0:
            return r['PaymentAmount']
        return r['Hours'] * r['PaymentAmount']

    df['Earnings']     = df.apply(compute_earn, axis=1)
    df['PaidEarnings'] = df.apply(lambda r: r['Earnings'] if r['Paid'] else 0.0, axis=1)

    # 3) Aggregate by Month + Client
    agg = (
        df.groupby(['Month','ClientID'], as_index=False)
          .agg(
            TotalHours    = ('Hours','sum'),
            TotalEarnings = ('Earnings','sum'),
            TotalPaid     = ('PaidEarnings','sum')
          )
    )

    # 4) Prepare filters
    month_list   = sorted(df['Month'].unique(), reverse=True)
    parent_ids   = clients[clients.ParentID=='']['ClientID'].tolist()
    parent_names = [name_map[p] for p in parent_ids]
    sel_months   = request.args.getlist('month')
    sel_clients  = request.args.getlist('client')

    # 5) Build nested summary
    summary = []
    for month, mdf in agg.groupby('Month'):
        if sel_months and month not in sel_months:
            continue
        for parent in parent_ids:
            pname = name_map[parent]
            if sel_clients and pname not in sel_clients:
                continue

            # children
            children_list = [
                {
                  'ClientName':    name_map[r.ClientID],
                  'TotalHours':    r.TotalHours,
                  'TotalEarnings': r.TotalEarnings,
                  'TotalPaid':     r.TotalPaid
                }
                for _, r in mdf[mdf.ClientID.isin(children.get(parent, []))].iterrows()
            ]

            # parent self
            p = mdf[mdf.ClientID==parent]
            own_hours    = float(p.TotalHours.sum())    if not p.empty else 0.0
            own_earnings = float(p.TotalEarnings.sum()) if not p.empty else 0.0
            own_paid     = float(p.TotalPaid.sum())     if not p.empty else 0.0
            try:
                eur_rate = fetch_eur_rate()
            except Exception:
                eur_rate = 1.0 
            total_hours    = own_hours + sum(c['TotalHours']    for c in children_list)
            total_earnings = own_earnings + sum(c['TotalEarnings'] for c in children_list)
            total_paid     = own_paid     + sum(c['TotalPaid']     for c in children_list)
            total_pending  = total_earnings - total_paid
            

            summary.append({
                'Month':         month,
                'ParentName':    pname,
                'Children':      children_list,
                'OwnHours':      own_hours,
                'OwnEarnings':   own_earnings,
                'OwnPaid':       own_paid,
                'TotalHours':    total_hours,
                'TotalEarnings': total_earnings,
                'TotalPaid':     total_paid,
                'TotalPending':  total_pending
            })

    # 6) Grand totals
    total_earnings = sum(item['TotalEarnings'] for item in summary)
    total_paid     = sum(item['TotalPaid']     for item in summary)
    total_pending  = total_earnings - total_paid

    return render_template(
        'monthly_summary.html',
        summary=summary,
        month_list=month_list,
        parent_names=parent_names,
        sel_months=sel_months,
        sel_clients=sel_clients,
        total_earnings=total_earnings,
        total_paid=total_paid,
        total_pending=total_pending,
        total_earnings_eur = total_earnings * eur_rate ,   # USD→EUR
        total_paid_eur     = total_paid     * eur_rate,
        total_pending_eur  = total_pending  * eur_rate
    )

from flask import jsonify

@app.route('/tasks/pending_count')
def pending_count():
    clients, tasks, ts = load_data()
    # count tasks where Status != "Completed"
    count = int((tasks.Status != 'Completed').sum())
    return jsonify({'pending': count})




if __name__ == '__main__':
    import webbrowser
    from threading import Timer

    # the URL the app will serve on
    url = "http://127.0.0.1:5000"

    # open the browser after a short delay (so Flask has time to start)
   

    # run the Flask development server (or your chosen host/port)
    app.run(host="127.0.0.1", port=5000, debug=True)
    def _open_browser():
        webbrowser.open(url)

    # schedule browser open in 1 second
    Timer(1, _open_browser).start()

