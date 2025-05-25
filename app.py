import os
import uuid
import webbrowser
from threading import Timer
from datetime import datetime

import pandas as pd
import requests
from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, jsonify
)

app = Flask(__name__)
app.secret_key = 'replace-with-a-secure-random-key'

EXCEL_FILE = os.path.join('Data', 'freelance_organizer.xlsx')


def fetch_eur_rate(timeout: float = 5.0) -> float:
    """
    Fetch USD→EUR rate once per app invocation.
    """
    resp = requests.get('https://www.floatrates.com/daily/usd.json', timeout=timeout)
    resp.raise_for_status()
    payload   = resp.json()
    eur_block = payload.get("eur", {})
    eur       = eur_block.get("rate")
    if eur is None:
        raise KeyError("EUR rate not found in API response")
    return float(eur)


def load_data():
    """
    Load or initialize the three sheets:
      - Clients:    ClientID, ClientName, ParentID, PaymentType, PaymentAmount, IsDeleted
      - Tasks:      TaskID, ClientID, TaskDescription, CreatedDate, Status, ShortName, IsDeleted
      - Timesheet:  EntryID, TaskID, Date, Hours, Description, Paid, IsDeleted
    """
    client_cols = ['ClientID','ClientName','ParentID','PaymentType','PaymentAmount','IsDeleted']
    task_cols   = ['TaskID','ClientID','TaskDescription','CreatedDate','Status','ShortName','IsDeleted']
    ts_cols     = ['EntryID','TaskID','Date','Hours','Description','Paid','IsDeleted']

    if os.path.exists(EXCEL_FILE):
        xls = pd.ExcelFile(EXCEL_FILE, engine='openpyxl')
        clients = (pd.read_excel(xls, 'Clients')    if 'Clients'    in xls.sheet_names
                   else pd.DataFrame(columns=client_cols))
        tasks   = (pd.read_excel(xls, 'Tasks')      if 'Tasks'      in xls.sheet_names
                   else pd.DataFrame(columns=task_cols))
        ts      = (pd.read_excel(xls, 'Timesheet')  if 'Timesheet'  in xls.sheet_names
                   else pd.DataFrame(columns=ts_cols))
    else:
        clients = pd.DataFrame(columns=client_cols)
        tasks   = pd.DataFrame(columns=task_cols)
        ts      = pd.DataFrame(columns=ts_cols)

    # Ensure IsDeleted exists on all
    for df in (clients, tasks, ts):
        if 'IsDeleted' not in df.columns:
            df['IsDeleted'] = False

    # Fill defaults / sanitize
    clients['ParentID']      = clients['ParentID'].fillna('')
    clients['PaymentType']   = clients['PaymentType'].fillna('Hourly')
    clients['PaymentAmount'] = clients['PaymentAmount'].fillna(0.0)

    if 'Status'      not in tasks.columns: tasks['Status']      = 'Pending'
    if 'ShortName'   not in tasks.columns: tasks['ShortName']   = ''
    if 'CreatedDate' not in tasks.columns: tasks['CreatedDate'] = ''

    ts['Paid']        = ts['Paid'].fillna(False)
    ts['Hours']       = ts['Hours'].fillna(0.0)
    ts['Description'] = ts['Description'].fillna('')
    ts['Date']        = ts['Date'].fillna('')

    return clients, tasks, ts


def save_data(clients, tasks, ts):
    """
    Write all three DataFrames back to the Excel file.
    """
    os.makedirs(os.path.dirname(EXCEL_FILE), exist_ok=True)
    with pd.ExcelWriter(EXCEL_FILE, engine='openpyxl') as writer:
        clients.to_excel(writer, sheet_name='Clients', index=False)
        tasks.to_excel(writer, sheet_name='Tasks', index=False)
        ts.to_excel(writer, sheet_name='Timesheet', index=False)


@app.route('/')
def home():
    return redirect(url_for('view_tasks'))


# ——— Clients ——————————————————————————————————————————————

@app.route('/clients')
def view_clients():
    clients, tasks, ts = load_data()
    clients = clients[clients.IsDeleted == False]
    clients_map = {c.ClientID: c.ClientName for _, c in clients.iterrows()}
    return render_template('view_clients.html',
                           clients=clients.to_dict('records'),
                           clients_map=clients_map)


@app.route('/clients/add', methods=['GET','POST'])
def add_client():
    clients, tasks, ts = load_data()
    clients = clients[clients.IsDeleted == False]
    parent_clients = clients[clients.ParentID == ''].to_dict('records')

    if request.method == 'POST':
        name          = request.form['name'].strip()
        parent_id     = request.form.get('parent_id','')
        if not name:
            flash('Client name is required.', 'danger')
            return redirect(url_for('add_client'))

        payment_type   = 'Hourly'
        payment_amount = 0.0
        if parent_id:
            payment_type   = request.form.get('rate_type','Hourly')
            payment_amount = float(request.form.get('rate_amount',0) or 0)

        cid = str(uuid.uuid4())
        idx = len(clients)
        clients.loc[idx, ['ClientID','ClientName','ParentID',
                          'PaymentType','PaymentAmount','IsDeleted']] = [
            cid, name, parent_id, payment_type, payment_amount, False
        ]
        save_data(clients, tasks, ts)
        flash('Client added successfully.', 'success')
        return redirect(url_for('view_clients'))

    return render_template('add_client.html', clients=parent_clients)


@app.route('/clients/<client_id>/edit', methods=['GET','POST'])
def edit_client(client_id):
    clients, tasks, ts = load_data()
    row = clients[clients.ClientID == client_id]
    if row.empty:
        flash('Client not found.', 'warning')
        return redirect(url_for('view_clients'))

    parent_clients = clients[
        (clients.ParentID == '') &
        (clients.ClientID != client_id) &
        (clients.IsDeleted == False)
    ].to_dict('records')
    client = row.iloc[0]

    if request.method == 'POST':
        name          = request.form['name'].strip()
        parent_id     = request.form.get('parent_id','')
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
        clients.loc[mask, 'IsDeleted']     = False

        save_data(clients, tasks, ts)
        flash('Client updated successfully.', 'success')
        return redirect(url_for('view_clients'))

    return render_template('edit_client.html',
                           clients=parent_clients,
                           client=client)


@app.route('/clients/<client_id>/delete', methods=['GET'])
def delete_client(client_id):
    clients, tasks, ts = load_data()

    # block if active children
    if not clients[
        (clients.ParentID == client_id) &
        (clients.IsDeleted == False)
    ].empty:
        flash("Cannot delete a parent client with active sub-clients.", "warning")
        return redirect(url_for('view_clients'))

    # block if tasks exist
    if not tasks[
        (tasks.ClientID == client_id) &
        (tasks.IsDeleted == False)
    ].empty:
        flash("Cannot delete a client with existing tasks.", "warning")
        return redirect(url_for('view_clients'))

    clients.loc[clients.ClientID == client_id, 'IsDeleted'] = True
    save_data(clients, tasks, ts)
    flash("Client deleted successfully.", "success")
    return redirect(url_for('view_clients'))


# ——— Tasks ———————————————————————————————————————————————

@app.route('/tasks')
def view_tasks():
    clients, tasks, ts = load_data()
    tasks = tasks[tasks.IsDeleted == False]
    merged = tasks.merge(
        clients[['ClientID','ClientName']],
        on='ClientID', how='left'
    ).rename(columns={'ClientName':'Client'})
    return render_template('view_tasks.html',
                           tasks=merged.to_dict('records'))


@app.route('/tasks/add', methods=['GET','POST'])
def add_task():
    clients, tasks, ts = load_data()
    clients['ParentID'] = clients['ParentID'].fillna('')
    child_clients = clients[
        (clients.ParentID != '') &
        (clients.IsDeleted == False)
    ].to_dict('records')

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
            tid, client_id, desc, now, 'Pending', short_name, False
        ]
        save_data(clients, tasks, ts)
        flash('Task added successfully.', 'success')
        return redirect(url_for('view_tasks'))

    return render_template('add_task.html', clients=child_clients)


@app.route('/tasks/<task_id>/update', methods=['POST'])
def update_status(task_id):
    clients, tasks, ts = load_data()
    row = tasks[tasks.TaskID == task_id]
    if row.empty:
        flash('Task not found.', 'warning')
        return redirect(url_for('view_tasks'))

    if request.is_json:
        new_status = request.get_json(silent=True).get('status')
    else:
        new_status = request.form.get('status')
    tasks.loc[tasks.TaskID == task_id, 'Status'] = new_status
    save_data(clients, tasks, ts)
    flash('Status updated.', 'info')
    return redirect(url_for('view_tasks'))


@app.route('/tasks/<task_id>/edit', methods=['POST'])
def edit_task(task_id):
    clients, tasks, ts = load_data()
    desc   = request.form.get('description','').strip()
    status = request.form.get('status')
    shortName = request.form.get('short_name')
    mask   = tasks.TaskID == task_id
    tasks.loc[mask, 'TaskDescription'] = desc
    tasks.loc[mask, 'Status']          = status
    tasks.loc[mask, 'ShortName']          = shortName
    save_data(clients, tasks, ts)
    flash('Task updated successfully.', 'success')
    return redirect(url_for('view_tasks'))


@app.route('/tasks/<task_id>/delete', methods=['POST'])
def delete_task(task_id):
    clients, tasks, ts = load_data()
    # block if any non-deleted logs exist
    if not ts[
        (ts.TaskID == task_id) &
        (ts.IsDeleted == False)
    ].empty:
        return jsonify(error="Cannot delete a task with logged hours"), 400

    tasks.loc[tasks.TaskID == task_id, 'IsDeleted'] = True
    save_data(clients, tasks, ts)
    return jsonify(success=True)


# ——— Timesheet ————————————————————————————————————————————

@app.route('/timesheet/log', methods=['GET','POST'])
def log_hours():
    clients, tasks, ts = load_data()
    merged = tasks.merge(
        clients[['ClientID','ClientName']],
        on='ClientID', how='left'
    ).rename(columns={'ClientName':'Client'})

    if request.method == 'POST':
        selected = request.form['task_input'].strip()
        display  = merged['Client'].astype(str).add(' – ').add(merged['ShortName'])
        mask     = display == selected
        if not mask.any():
            flash('Please choose a valid task.', 'danger')
            return redirect(url_for('log_hours'))

        task_id = merged.loc[mask, 'TaskID'].iloc[0]
        date    = request.form.get('date') or datetime.now().strftime('%Y-%m-%d')
        try:
            hrs = float(request.form['hours']); assert hrs>0
        except:
            flash('Enter a valid number of hours.', 'danger')
            return redirect(url_for('log_hours'))

        eid = str(uuid.uuid4())
        ts.loc[len(ts)] = [eid, task_id, date, hrs,
                           request.form.get('description','').strip(),
                           False, False]
        save_data(clients, tasks, ts)
        flash('Logged hours successfully.', 'success')
        return redirect(url_for('view_timesheet'))

    # prefill
    qid = request.args.get('task_id','')
    initial_task = ''
    if qid:
        row = merged[merged.TaskID == qid]
        if not row.empty:
            initial_task = f"{row.iloc[0].Client} – {row.iloc[0].ShortName}"

    return render_template('log_hours.html',
                           tasks=merged.to_dict('records'),
                           initial_task_display=initial_task,
                           initial_date=datetime.now().strftime('%Y-%m-%d'))


@app.route('/timesheet')
def view_timesheet():
    clients, tasks, ts = load_data()
    ts = ts[ts.IsDeleted == False]

    clients['ParentID'] = clients['ParentID'].fillna('')
    name_map   = clients.set_index('ClientID')['ClientName'].to_dict()
    parent_map = clients.set_index('ClientID')['ParentID'].to_dict()

    df = (ts[['EntryID','TaskID','Date','Hours','Description','Paid']]
          .merge(tasks[['TaskID','ClientID','ShortName','TaskDescription']],
                 on='TaskID', how='left')
          .merge(clients[['ClientID','ClientName']], on='ClientID', how='left'))
    df['Date'] = pd.to_datetime(df['Date']).dt.strftime('%Y-%m-%d')

    def find_parent(cid):
        pid = parent_map.get(cid,'')
        return pid if pid else cid
    df['ParentID'] = df['ClientID'].apply(find_parent)

    nested = []
    for parent_id, pdf in df.groupby('ParentID'):
        children = []
        for child_id, cdf in pdf.groupby('ClientID'):
            children.append({
                'ClientID':   child_id,
                'ClientName': name_map.get(child_id,'—'),
                'Entries':    cdf.to_dict('records')
            })
        nested.append({
            'ParentID':   parent_id,
            'ParentName': name_map.get(parent_id,'—'),
            'Children':   children
        })

    return render_template('view_timesheet.html', groups=nested)


@app.route('/timesheet/entry/<entry_id>/delete', methods=['POST'])
def delete_entry(entry_id):
    clients, tasks, ts = load_data()
    row = ts[ts.EntryID == entry_id]
    if row.empty:
        flash("Entry not found.", "warning")
        return redirect(url_for('view_timesheet'))
    if row.Paid.iloc[0]:
        flash("Cannot delete an entry that has already been paid.", "danger")
        return redirect(url_for('view_timesheet'))

    ts.loc[ts.EntryID == entry_id, 'IsDeleted'] = True
    save_data(clients, tasks, ts)
    flash("Entry deleted.", "success")
    return redirect(url_for('view_timesheet'))


@app.route('/timesheet/entry/<entry_id>/edit', methods=['GET','POST'])
def edit_entry(entry_id):
    clients, tasks, ts = load_data()
    ts = ts[ts.IsDeleted == False]
    row = ts[ts.EntryID == entry_id]
    if row.empty:
        flash('Entry not found.', 'warning')
        return redirect(url_for('view_timesheet'))

    if request.method == 'POST':
        date = request.form.get('date', row.Date.iloc[0])
        hrs  = float(request.form.get('hours', row.Hours.iloc[0]))
        desc = request.form.get('description', row.Description.iloc[0]).strip()
        ts.loc[ts.EntryID == entry_id, 'Date']        = date
        ts.loc[ts.EntryID == entry_id, 'Hours']       = hrs
        ts.loc[ts.EntryID == entry_id, 'Description'] = desc
        save_data(clients, tasks, ts)
        flash('Entry updated.', 'success')
        return redirect(url_for('view_timesheet'))

    entry = row.iloc[0].to_dict()
    return render_template('edit_entry.html', entry=entry)


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
    ts = ts[ts.IsDeleted == False]

    # single API call
    try:
        eur_rate = fetch_eur_rate()
    except:
        eur_rate = 1.0

    clients['ParentID'] = clients['ParentID'].fillna('')
    name_map   = clients.set_index('ClientID')['ClientName'].to_dict()
    children   = (clients[clients.ParentID!='']
                  .groupby('ParentID')['ClientID']
                  .apply(list).to_dict())

    df = (ts[['TaskID','Date','Hours','Paid']]
          .merge(tasks[['TaskID','ClientID']], on='TaskID', how='left')
          .merge(clients[['ClientID','PaymentType','PaymentAmount']],
                 on='ClientID', how='left'))
    df['Date']  = pd.to_datetime(df['Date'])
    df['Month'] = df['Date'].dt.to_period('M').astype(str)
    df['Hours'] = df['Hours'].fillna(0.0)

    def compute_earn(r):
        if r['PaymentType'] in ('Monthly','Project') and r['Hours']>0:
            return r['PaymentAmount']
        return r['Hours'] * r['PaymentAmount']

    df['Earnings']     = df.apply(compute_earn, axis=1)
    df['PaidEarnings'] = df.apply(lambda r: r['Earnings'] if r['Paid'] else 0.0, axis=1)

    agg = (df.groupby(['Month','ClientID'], as_index=False)
           .agg(TotalHours=('Hours','sum'),
                TotalEarnings=('Earnings','sum'),
                TotalPaid=('PaidEarnings','sum')))

    month_list  = sorted(df['Month'].unique(), reverse=True)
    parent_ids  = clients[clients.ParentID=='']['ClientID'].tolist()
    parent_names= [name_map[p] for p in parent_ids]
    sel_months  = request.args.getlist('month')
    sel_clients = request.args.getlist('client')

    summary = []
    for month, mdf in agg.groupby('Month'):
        if sel_months and month not in sel_months: continue
        for parent in parent_ids:
            pname = name_map[parent]
            if sel_clients and pname not in sel_clients: continue

            children_list = [{
                'ClientName':    name_map[r.ClientID],
                'TotalHours':    r.TotalHours,
                'TotalEarnings': r.TotalEarnings,
                'TotalPaid':     r.TotalPaid
            } for _, r in
               mdf[mdf.ClientID.isin(children.get(parent,[]))].iterrows()]

            p = mdf[mdf.ClientID==parent]
            own_h = float(p.TotalHours.sum())    if not p.empty else 0.0
            own_e = float(p.TotalEarnings.sum()) if not p.empty else 0.0
            own_p = float(p.TotalPaid.sum())     if not p.empty else 0.0

            tot_h = own_h + sum(c['TotalHours']    for c in children_list)
            tot_e = own_e + sum(c['TotalEarnings'] for c in children_list)
            tot_p = own_p + sum(c['TotalPaid']     for c in children_list)
            tot_pending = tot_e - tot_p

            summary.append({
                'Month': month,
                'ParentName': pname,
                'Children': children_list,
                'OwnHours': own_h,
                'OwnEarnings': own_e,
                'OwnPaid': own_p,
                'TotalHours': tot_h,
                'TotalEarnings': tot_e,
                'TotalPaid': tot_p,
                'TotalPending': tot_pending
            })

    total_earnings = sum(i['TotalEarnings'] for i in summary)
    total_paid     = sum(i['TotalPaid']     for i in summary)
    total_pending  = total_earnings - total_paid

    return render_template('monthly_summary.html',
        summary=summary,
        month_list=month_list,
        parent_names=parent_names,
        sel_months=sel_months,
        sel_clients=sel_clients,
        total_earnings=total_earnings,
        total_paid=total_paid,
        total_pending=total_pending,
        total_earnings_eur=total_earnings*eur_rate,
        total_paid_eur=total_paid*eur_rate,
        total_pending_eur=total_pending*eur_rate
    )


@app.route('/tasks/pending_count')
def pending_count():
    clients, tasks, ts = load_data()
    count = int((tasks.Status != 'Completed').sum())
    return jsonify({'pending': count})


if __name__ == '__main__':
    url = "http://127.0.0.1:5000"
    Timer(1, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=5000, debug=True)
