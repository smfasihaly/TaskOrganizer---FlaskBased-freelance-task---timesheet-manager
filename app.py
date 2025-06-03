import os
import uuid
import json
import requests
import pandas as pd
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, jsonify, session,send_file
)
from io import BytesIO
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'replace-with-a-secure-random-key'
EXCEL_FILE = os.path.join('Data', 'freelance_organizer.xlsx')

# ── Exchange Rate Caching ─────────────────────────────────────────────────────
_exchange_cache: dict[str, tuple[float, datetime]] = {}

def fetch_exchange_rate(currency: str, timeout: float = 5.0) -> float:
    """
    Fetch USD → <currency> rate from floatrates.com, caching for 1h.
    `currency` is 3-letter code (e.g. 'EUR', 'GBP').
    """
    now = datetime.now()
    # serve from cache if <1h old
    cached = _exchange_cache.get(currency.upper())
    if cached and (now - cached[1]) < timedelta(hours=1):
        return cached[0]

    resp = requests.get('https://www.floatrates.com/daily/usd.json', timeout=timeout)
    resp.raise_for_status()
    data  = resp.json()
    block = data.get(currency.lower(), {})
    rate  = block.get("rate")
    if rate is None:
        raise KeyError(f"{currency.upper()} rate not found")
    rate = float(rate)
    _exchange_cache[currency.upper()] = (rate, now)
    return rate

# ── Currency Metadata ─────────────────────────────────────────────────────────
CURRENCY_FILE = os.path.join(app.root_path, 'static', 'currencies.json')
with open(CURRENCY_FILE, 'r', encoding='utf-8') as f:
    _CURRENCY_DATA = json.load(f)

def get_currency_list() -> list[tuple[str,str]]:
    """Return sorted list of (code, name) from currencies.json."""
    return sorted(
        [(code, info.get('name','')) for code, info in _CURRENCY_DATA.items()],
        key=lambda x: x[0]
    )

def get_currency_symbol(code: str) -> str:
    code = str(code) + ''
    """Lookup native symbol for code, or fallback to code."""
    entry = _CURRENCY_DATA.get(code.upper(), {})
    return entry.get('symbolNative') or entry.get('symbol') or code.upper()
app.jinja_env.globals['get_currency_symbol'] = get_currency_symbol
# Make both payout & report currency available in templates
@app.context_processor
def inject_user_currencies():
    report_code = 'USD'
    payout_code = 'USD'
    if session.get('user_id'):
        _, _, _, users = load_data()
        row = users[users.id == session['user_id']]
        if not row.empty:
            report_code = row.iloc[0].currency or 'USD'
            payout_code = row.iloc[0].pay_currency or report_code
    return {
        'report_currency': report_code,
        'report_symbol':   get_currency_symbol(report_code),
        'payout_currency': payout_code,
        'payout_symbol':   get_currency_symbol(payout_code),
    }

# ── Data I/O ─────────────────────────────────────────────────────────────────
def load_data():
    client_cols = ['ClientID','ClientName','ParentID','PaymentType','PaymentAmount','IsDeleted','user_id']
    task_cols   = ['TaskID','ClientID','TaskDescription','CreatedDate','Status','ShortName','IsDeleted','user_id']
    ts_cols     = ['EntryID','TaskID','Date','Hours','Description','Paid','IsDeleted','user_id']
    user_cols   = ['id','name','email','password_hash','currency','pay_currency','created_at','last_login','is_admin','status','lang_pref']

    if os.path.exists(EXCEL_FILE):
        xls     = pd.ExcelFile(EXCEL_FILE, engine='openpyxl')
        clients = pd.read_excel(xls, 'Clients')    if 'Clients'   in xls.sheet_names else pd.DataFrame(columns=client_cols)
        tasks   = pd.read_excel(xls, 'Tasks')      if 'Tasks'     in xls.sheet_names else pd.DataFrame(columns=task_cols)
        ts      = pd.read_excel(xls, 'Timesheet')  if 'Timesheet' in xls.sheet_names else pd.DataFrame(columns=ts_cols)
        users   = pd.read_excel(xls, 'Users')      if 'Users'     in xls.sheet_names else pd.DataFrame(columns=user_cols)
    else:
        clients = pd.DataFrame(columns=client_cols)
        tasks   = pd.DataFrame(columns=task_cols)
        ts      = pd.DataFrame(columns=ts_cols)
        users   = pd.DataFrame(columns=user_cols)

    # ensure required columns
    for df, cols in ((clients,client_cols),(tasks,task_cols),(ts,ts_cols),(users,user_cols)):
        for c in cols:
            if c not in df.columns:
                df[c] = pd.NA

    # sanitize clients
    clients.ParentID      = clients.ParentID.fillna('')
    clients.PaymentType   = clients.PaymentType.fillna('Hourly')
    clients.PaymentAmount = clients.PaymentAmount.fillna(0.0)
    clients.IsDeleted     = clients.IsDeleted.fillna(False)

    # sanitize tasks
    tasks.Status      = tasks.Status.fillna('Pending')
    tasks.ShortName   = tasks.ShortName.fillna('')
    tasks.CreatedDate = tasks.CreatedDate.fillna('')
    tasks.IsDeleted   = tasks.IsDeleted.fillna(False)

    # sanitize timesheet
    ts.Paid        = ts.Paid.fillna(False)
    ts.Hours       = ts.Hours.fillna(0.0)
    ts.Description = ts.Description.fillna('')
    ts.Date        = ts.Date.fillna('')
    ts.IsDeleted   = ts.IsDeleted.fillna(False)

    return clients, tasks, ts, users

def save_data(clients, tasks, ts, users):
    os.makedirs(os.path.dirname(EXCEL_FILE), exist_ok=True)
    with pd.ExcelWriter(EXCEL_FILE, engine='openpyxl') as w:
        clients.to_excel(w, sheet_name='Clients', index=False)
        tasks.to_excel(w, sheet_name='Tasks', index=False)
        ts.to_excel(w, sheet_name='Timesheet', index=False)
        users.to_excel(w, sheet_name='Users', index=False)

# ── Helpers ───────────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get('user_id'):
            flash('Please log in first.', 'warning')
            return redirect(url_for('login_register'))
        return f(*args, **kwargs)
    return wrapped

def load_user_data():
    """Load only the current user's non-deleted clients/tasks/timesheet."""
    clients, tasks, ts, users = load_data()
    me = session['user_id']
    clients = clients[(clients.user_id==me)&(~clients.IsDeleted)]
    tasks   = tasks[(tasks.user_id==me)&(~tasks.IsDeleted)]
    ts      = ts[(ts.user_id==me)&(~ts.IsDeleted)]
    return clients, tasks, ts, users

@app.route('/', methods=['GET'])
def home():
    return redirect(url_for('login_register'))

@app.route('/auth', methods=['GET', 'POST'])
def login_register():
    
    # If already logged in, go straight to tasks
    if session.get('user_id'):
        return redirect(url_for('view_tasks'))

    clients, tasks, ts, users = load_data()

    if request.method == 'POST':
        action = request.form['action']
        name   = request.form['name'].strip()
        pwd    = request.form['password']

        if action == 'login':
            # — LOGIN FLOW — 
            u = users[users.name == name]
            if not u.empty and check_password_hash(u.iloc[0].password_hash, pwd):
                if u.iloc[0].status.lower() != 'active':
                    flash('Your account is inactive.', 'danger')
                else:
                    session['user_id'] = str(u.iloc[0]['id'])
                    session['user_name'] = str(u.iloc[0]['name'])
                    idx = u.index[0]
                    users.at[idx, 'last_login'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    save_data(clients, tasks, ts, users)
                    flash('Logged in successfully.', 'success')
                    return redirect(url_for('view_tasks'))
            else:
                flash('Invalid username or password.', 'danger')

        else:
            # — REGISTER FLOW —
            if not users[users.name == name].empty:
                flash('Username already taken.', 'warning')
            else:
                user_id      = str(uuid.uuid4())
                email        = request.form.get('email', '').strip()
                payout_curr  = request.form['pay_currency']  # from the form
                report_curr  = 'USD'                         # always default report → USD
                lang_pref    = request.form.get('lang_pref', 'en')
                created_at   = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                users.loc[len(users)] = [
                    user_id,
                    name,
                    email,
                    generate_password_hash(pwd),
                    report_curr,
                    payout_curr,
                    created_at,
                    pd.NA,
                    False,
                    'active',
                    lang_pref
                ]
                save_data(clients, tasks, ts, users)

                session['user_id']   = user_id
                session['user_name'] = name
                flash('Registered and logged in!', 'success')
                return redirect(url_for('view_tasks'))

    return render_template('login_register.html',currencies=get_currency_list())

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out.', 'info')
    return redirect(url_for('login_register'))

# ── Profile ──────────────────────────────────────────────────────────────────
@app.route('/profile', methods=['GET','POST'])
@login_required
def profile():
    clients, tasks, ts, users = load_data()
    me = session['user_id']
    idx = users.index[users.id==me].tolist()
    if not idx:
        flash('User not found.', 'danger')
        return redirect(url_for('logout'))
    i = idx[0]
    user = users.loc[i]
    if request.method=='POST':
        action = request.form['action']
        if action=='update':
            new_name  = request.form['name'].strip()
            new_email = request.form['email'].strip()
            new_curr  = request.form['currency']
            new_pout  = request.form['pay_currency']
            new_lang  = request.form['lang_pref']
            new_pwd   = request.form.get('password','').strip()
            if new_name != user['name'] and not users[users['name'] == new_name].empty:
                flash('Username taken.', 'warning')
                return redirect(url_for('profile'))
            users.at[i,'name']=new_name
            users.at[i,'email']=new_email
            users.at[i,'currency']=new_curr
            users.at[i,'pay_currency']=new_pout
            users.at[i,'lang_pref']=new_lang
            if new_pwd:
                users.at[i,'password_hash']=generate_password_hash(new_pwd)
            save_data(clients,tasks,ts,users)
            session['user_name']=new_name
            flash('Profile updated.', 'success')
            return redirect(url_for('profile'))
        else:  # deactivate
            users.at[i,'status']='inactive'
            save_data(clients,tasks,ts,users)
            session.clear()
            flash('Account deactivated.', 'info')
            return redirect(url_for('login_register'))

    return render_template(
        'profile.html',
        user=user.to_dict(),
        currencies=get_currency_list()
    )

# ── Clients ──────────────────────────────────────────────────────────────────
@app.route('/clients')
@login_required
def view_clients():
    clients_all, tasks_all, ts_all, users = load_data()
    me = session['user_id']
    # filter just for this user
    clients = clients_all[(clients_all.user_id == me) & (~clients_all.IsDeleted)]
    cmap    = {r.ClientID: r.ClientName for _, r in clients.iterrows()}
    return render_template('view_clients.html',
        clients     = clients.to_dict('records'),
        clients_map = cmap
    )

@app.route('/clients/add', methods=['GET','POST'])
@login_required
def add_client():
    clients_all, tasks_all, ts_all, users = load_data()
    me = session['user_id']

    if request.method == 'POST':
        cid = str(uuid.uuid4())
        clients_all.loc[len(clients_all)] = [
            cid,
            request.form['name'].strip(),
            request.form.get('parent_id',''),
            request.form.get('rate_type','Hourly'),
            float(request.form.get('rate_amount',0) or 0),
            False,
            me
        ]
        save_data(clients_all, tasks_all, ts_all, users)
        flash('Client added.', 'success')
        return redirect(url_for('view_clients'))

    # for the dropdown, only top-level parents of this user
    parents = clients_all[
        (clients_all.user_id == me) &
        (clients_all.ParentID == '') &
        (~clients_all.IsDeleted)
    ]
    return render_template('add_client.html',
        clients = parents.to_dict('records')
    )

@app.route('/clients/<client_id>/edit', methods=['GET','POST'])
@login_required
def edit_client(client_id):
    clients_all, tasks_all, ts_all, users = load_data()
    me = session['user_id']

    df = clients_all[
        (clients_all.ClientID == client_id) &
        (clients_all.user_id   == me)
    ]
    if df.empty:
        flash('Client not found.', 'warning')
        return redirect(url_for('view_clients'))
    client = df.iloc[0]

    if request.method == 'POST':
        mask = (
            (clients_all.ClientID == client_id) &
            (clients_all.user_id   == me)
        )
        clients_all.loc[mask,'ClientName']    = request.form['name'].strip()
        clients_all.loc[mask,'ParentID']      = request.form.get('parent_id','')
        clients_all.loc[mask,'PaymentType']   = request.form.get('rate_type','Hourly')
        clients_all.loc[mask,'PaymentAmount'] = float(request.form.get('rate_amount',0) or 0)
        save_data(clients_all, tasks_all, ts_all, users)
        flash('Client updated.', 'success')
        return redirect(url_for('view_clients'))

    parents = clients_all[
        (clients_all.user_id == me) &
        (clients_all.ParentID == '') &
        (clients_all.ClientID != client_id) &
        (~clients_all.IsDeleted)
    ]
    return render_template('edit_client.html',
        clients = parents.to_dict('records'),
        client  = client
    )

@app.route('/clients/<client_id>/delete', methods=['POST'])
@login_required
def delete_client(client_id):
    clients_all, tasks_all, ts_all, users = load_data()
    me = session['user_id']

    # block if children
    if not clients_all[
        (clients_all.ParentID == client_id) &
        (clients_all.user_id   == me) &
        (~clients_all.IsDeleted)
    ].empty:
        flash('Cannot delete parent with children.', 'warning')
    # block if tasks
    elif not tasks_all[
        (tasks_all.ClientID == client_id) &
        (tasks_all.user_id   == me) &
        (~tasks_all.IsDeleted)
    ].empty:
        flash('Cannot delete client with tasks.', 'warning')
    else:
        clients_all.loc[
            (clients_all.ClientID == client_id) &
            (clients_all.user_id   == me),
            'IsDeleted'
        ] = True
        save_data(clients_all, tasks_all, ts_all, users)
        flash('Client deleted.', 'success')

    return redirect(url_for('view_clients'))


# ── Tasks ────────────────────────────────────────────────────────────────────
@app.route('/tasks')
@login_required
def view_tasks():
    clients_all, tasks_all, ts_all, users = load_data()
    me = session['user_id']
    # only non-deleted, this user's tasks
    tasks = tasks_all[
        (tasks_all.user_id == me) &
        (~tasks_all.IsDeleted)
    ]
    clients = clients_all[
        (clients_all.user_id == me) &
        (~clients_all.IsDeleted)
    ][['ClientID','ClientName']]
    merged = tasks.merge(clients, on='ClientID', how='left') \
                  .rename(columns={'ClientName':'Client'})
    return render_template('view_tasks.html',
        tasks = merged.to_dict('records')
    )

@app.route('/tasks/add', methods=['GET','POST'])
@login_required
def add_task():
    clients_all, tasks_all, ts_all, users = load_data()
    me = session['user_id']
    children = clients_all[
        (clients_all.user_id == me) &
        (~clients_all.IsDeleted) &
        (clients_all.ParentID != '')
    ]

    if request.method == 'POST':
        tid = str(uuid.uuid4())
        tasks_all.loc[len(tasks_all)] = [
            tid,
            request.form['client_id'],
            request.form['description'].strip(),
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'Pending',
            request.form['short_name'].strip(),
            False,
            me
        ]
        save_data(clients_all, tasks_all, ts_all, users)
        flash('Task added.', 'success')
        return redirect(url_for('view_tasks'))

    return render_template('add_task.html',
        clients = children.to_dict('records')
    )

@app.route('/tasks/<task_id>/update', methods=['POST'])
@login_required
def update_status(task_id):
    clients_all, tasks_all, ts_all, users = load_data()
    new = (request.get_json(silent=True, force=True) or {}).get('status') \
          if request.is_json else request.form.get('status')
    mask = tasks_all.TaskID == task_id
    tasks_all.loc[mask,'Status'] = new
    save_data(clients_all, tasks_all, ts_all, users)
    return jsonify(success=True)

@app.route('/tasks/<task_id>/edit', methods=['POST'])
@login_required
def edit_task(task_id):
    clients_all, tasks_all, ts_all, users = load_data()
    mask = tasks_all.TaskID == task_id
    tasks_all.loc[mask,'TaskDescription'] = request.form.get('description','').strip()
    tasks_all.loc[mask,'ShortName']       = request.form.get('short_name','').strip()
    tasks_all.loc[mask,'Status']          = request.form.get('status')
    save_data(clients_all, tasks_all, ts_all, users)
    flash('Task updated.', 'success')
    return redirect(url_for('view_tasks'))

@app.route('/tasks/<task_id>/delete', methods=['POST'])
@login_required
def delete_task(task_id):
    clients_all, tasks_all, ts_all, users = load_data()
    # block if any non-deleted logs exist
    if not ts_all[
        (ts_all.TaskID == task_id) &
        (~ts_all.IsDeleted)
    ].empty:
        return jsonify(error="Cannot delete a task with logged hours"), 400

    tasks_all.loc[tasks_all.TaskID == task_id, 'IsDeleted'] = True
    save_data(clients_all, tasks_all, ts_all, users)
    return jsonify(success=True)


# ── Timesheet ────────────────────────────────────────────────────────────────
@app.route('/timesheet/log', methods=['GET','POST'])
@login_required
def log_hours():
    # 1) Load _all_ the sheets
    clients_all, tasks_all, ts_all, users = load_data()
    me = session['user_id']

    # 2) Filter to this user's active clients/tasks
    clients = clients_all[(clients_all.user_id == me) & (~clients_all.IsDeleted)]
    tasks   = tasks_all  [(tasks_all.user_id   == me) & (~tasks_all.IsDeleted)]

    # 3) Build the merged display exactly as before
    merged = tasks.merge(
        clients[['ClientID','ClientName']],
        on='ClientID', how='left'
    )
    
    merged['display'] = merged['ClientName'] + ' – ' + merged['ShortName']

    print(merged['display'])
    if request.method == 'POST':
        sel = request.form['task_input'].strip()
        row = merged[merged.display == sel]
        if row.empty:
            flash('Please choose a valid task.', 'danger')
            return redirect(url_for('log_hours'))

        entry_id = str(uuid.uuid4())
        date     = request.form.get('date') or datetime.now().strftime('%Y-%m-%d')
        hours    = float(request.form['hours'])
        desc     = request.form.get('description','').strip()

        # 4) Append into the **full** ts_all (preserving other users)
        ts_all.loc[len(ts_all)] = [
            entry_id,
            row.TaskID.iloc[0],
            date,
            hours,
            desc,
            False,      # Paid
            False,      # IsDeleted
            me          # user_id
        ]

        # 5) Save **all** sheets back
        save_data(clients_all, tasks_all, ts_all, users)
        flash('Hours logged.', 'success')
        return redirect(url_for('view_timesheet'))

    # prefill logic (unchanged)
    qid = request.args.get('task_id','')
    initial_task = ''
    if qid:
        row = merged[merged.TaskID == qid]
        if not row.empty:
            initial_task = f"{row.iloc[0].ClientName} – {row.iloc[0].ShortName}"

    return render_template('log_hours.html',
        tasks=merged.to_dict('records'),
        initial_task_display=initial_task,
        initial_date=datetime.now().strftime('%Y-%m-%d')
    )

@app.route('/timesheet')
@login_required
def view_timesheet():
    clients_all, tasks_all, ts_all, users = load_data()
    me = session['user_id']

    # filter down to this user's live rows
    clients = clients_all[(clients_all.user_id == me) & (~clients_all.IsDeleted)]
    tasks   = tasks_all[(tasks_all.user_id   == me) & (~tasks_all.IsDeleted)]
    ts      = ts_all[(ts_all.user_id        == me) & (~ts_all.IsDeleted)]

    df = ts.merge(
        tasks[['TaskID','ClientID','ShortName','TaskDescription']],
        on='TaskID', how='left'
    ).merge(
        clients[['ClientID','ClientName']], on='ClientID', how='left'
    )
    df['Date'] = pd.to_datetime(df['Date']).dt.strftime('%Y-%m-%d')

    parent_map = clients.set_index('ClientID')['ParentID'].to_dict()
    def find_parent(cid): return parent_map.get(cid,'') or cid
    df['ParentID'] = df['ClientID'].apply(find_parent)

    grouped = []
    for pid, pdf in df.groupby('ParentID'):
        children = []
        for cid, cdf in pdf.groupby('ClientID'):
            children.append({
                'ClientID':   cid,
                'ClientName': clients.set_index('ClientID').loc[cid,'ClientName'],
                'Entries':    cdf.to_dict('records')
            })
        grouped.append({
            'ParentID':   pid,
            'ParentName': clients.set_index('ClientID').loc[pid,'ClientName'],
            'Children':   children
        })

    return render_template('view_timesheet.html', clients_list=clients.to_dict('records') , groups=grouped)


@app.route('/timesheet/mark_paid/<entry_id>', methods=['POST'])
@login_required
def mark_paid(entry_id):
    clients_all, tasks_all, ts_all, users = load_data()
    me = session['user_id']

    mask = (ts_all.EntryID == entry_id) & (ts_all.user_id == me)
    ts_all.loc[mask, 'Paid'] = True

    save_data(clients_all, tasks_all, ts_all, users)
    flash('Entry marked paid.', 'success')
    return redirect(url_for('view_timesheet'))


@app.route('/timesheet/entry/<entry_id>/delete', methods=['POST'])
@login_required
def delete_entry(entry_id):
    clients_all, tasks_all, ts_all, users = load_data()
    me = session['user_id']

    mask = (ts_all.EntryID == entry_id) & (ts_all.user_id == me)
    row  = ts_all[mask]
    if row.empty or row.iloc[0]['Paid']:
        flash('Cannot delete.', 'danger')
    else:
        ts_all.loc[mask, 'IsDeleted'] = True
        save_data(clients_all, tasks_all, ts_all, users)
        flash('Entry deleted.', 'success')

    return redirect(url_for('view_timesheet'))


@app.route('/timesheet/entry/<entry_id>/edit', methods=['GET','POST'])
@login_required
def edit_entry(entry_id):
    clients_all, tasks_all, ts_all, users = load_data()
    me = session['user_id']

    mask = (ts_all.EntryID == entry_id) & (ts_all.user_id == me) & (~ts_all.IsDeleted)
    df = ts_all[mask]
    if df.empty:
        flash('Entry not found.', 'warning')
        return redirect(url_for('view_timesheet'))

    entry = df.iloc[0].to_dict()
    if request.method == 'POST':
        ts_all.loc[mask, 'Date']        = request.form.get('date', entry['Date'])
        ts_all.loc[mask, 'Hours']       = float(request.form.get('hours', entry['Hours']))
        ts_all.loc[mask, 'Description'] = request.form.get('description', entry['Description']).strip()

        save_data(clients_all, tasks_all, ts_all, users)
        flash('Entry updated.', 'success')
        return redirect(url_for('view_timesheet'))

    return render_template('edit_entry.html', entry=entry)


@app.route('/timesheet/export')
@login_required
def export_timesheet():
    clients, tasks, ts, users = load_user_data()
    me = session['user_id']

    # Prepare DataFrame
    df = (ts
          .merge(tasks[['TaskID','ClientID','ShortName','TaskDescription']],
                 on='TaskID', how='left')
          .merge(clients[['ClientID','ClientName','ParentID']], on='ClientID', how='left'))
    df['Date']  = pd.to_datetime(df['Date'])
    df['Month'] = df['Date'].dt.to_period('M').astype(str)

    # Filters
    client_id   = request.args.get('client_id')  # this can be either a parent or a leaf
    client_name = "all-clients"
    if client_id:
        # if the chosen client_id is actually a parent, include all its children
        is_parent   = client_id in clients.ParentID.values
        if is_parent:
            child_ids = clients.loc[clients.ParentID == client_id, 'ClientID'].tolist()
            df = df[df.ClientID.isin([client_id] + child_ids)]
        else:
            df = df[df.ClientID == client_id]
        client_name = clients.loc[clients.ClientID == client_id, 'ClientName'].iloc[0].replace(" ", "_")


    # Filter by month if provided
    month = request.args.get('month')
    month_label = month or "all-months"
    if month:
        df = df[df.Month == month]

    # Group into sheets by month (flat month string)
    if month:
        sheets = { month: df }
    else:
        sheets = dict(tuple(df.groupby('Month')))

    output = BytesIO()
    with pd.ExcelWriter(
        output,
        engine='xlsxwriter',
        date_format='DD-MMM-YYYY',
        datetime_format='DD-MMM-YYYY'
    ) as writer:

        for sheet_name, sheet_df in sheets.items():
            # Build a list of rows grouped by parent:
            # For each unique parent_id in this sheet, insert a "header" row
            # with ParentName, then all child rows under it.
            rows = []
            # Determine each row's true parent_id
            sheet_df = sheet_df.copy()
            sheet_df['EffectiveParent'] = sheet_df.apply(
                lambda r: r.ClientID if r.ParentID == '' else r.ParentID,
                axis=1
            )
            # Group all entries by that EffectiveParent
            grouped_by_parent = {
                pid: group
                for pid, group in sheet_df.groupby('EffectiveParent')
            }

            # Sort parents by name
            parent_order = sorted(
                grouped_by_parent.keys(),
                key=lambda pid: clients.set_index('ClientID').loc[pid, 'ClientName']
            )

            for pid in parent_order:
                parent_name = clients.loc[clients.ClientID == pid, 'ClientName'].iloc[0]
                # Insert a header row for this parent
                rows.append({
                    'ParentName': parent_name,
                    'ClientName': '',
                    'Date': pd.NaT,
                    'ShortName': '',
                    'TaskDescription': '',
                    'Hours': ''
                })
                # Now append each child entry under this parent
                for _, entry in grouped_by_parent[pid].iterrows():
                    child_name = entry.ClientName
                    rows.append({
                        'ParentName': '',
                        'ClientName': child_name,
                        'Date': entry.Date,
                        'ShortName': entry.ShortName,
                        'TaskDescription': entry.TaskDescription,
                        'Hours': entry.Hours
                    })

            # Convert to DataFrame
            out = pd.DataFrame(rows, columns=[
                'ParentName', 'ClientName', 'Date', 'ShortName', 'TaskDescription', 'Hours'
            ])

            # Append a bottom total row (summing only the numeric Hours)
            total_hours = sheet_df['Hours'].sum()
            total_row = pd.DataFrame([{
                'ParentName': '',
                'ClientName': '',
                'Date': pd.NaT,
                'ShortName': '',
                'TaskDescription': 'Total',
                'Hours': total_hours
            }])
            out = pd.concat([out, total_row], ignore_index=True)

            # Convert “YYYY-MM” into “may-2025”
            dt = pd.to_datetime(sheet_name + "-01")
            sheet_label = dt.strftime('%B-%Y').lower()  # e.g. "May-2025" → "may-2025"
            safe_sheet = sheet_label[:31]  # Excel limit

            out.to_excel(writer, sheet_name=safe_sheet, index=False)

    output.seek(0)
    filename = f"timesheet-{client_name}-{month_label}.xlsx"
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )
# ── Reports ──────────────────────────────────────────────────────────────────
@app.route('/reports/monthly')
@login_required
def monthly_summary():
    clients, tasks, ts, users = load_user_data()
    me = session['user_id']
    user_row = users[users.id==me].iloc[0]
    user_curr = user_row.currency or 'USD'
    exc_rate = 1.0 if user_curr.upper()=='USD' else fetch_exchange_rate(user_curr)

    name_map  = clients.set_index('ClientID').ClientName.to_dict()
    children  = clients[clients.ParentID!=''].groupby('ParentID').ClientID.apply(list).to_dict()

    df = ts[['TaskID','Date','Hours','Paid']].merge(
         tasks[['TaskID','ClientID']], on='TaskID'
    ).merge(
         clients[['ClientID','PaymentType','PaymentAmount']], on='ClientID'
    )
    df['Date']  = pd.to_datetime(df.Date)
    df['Month'] = df.Date.dt.to_period('M').astype(str)
    df['Earnings'] = df.apply(
        lambda r: r.PaymentAmount
                  if r.PaymentType in ('Monthly','Project') and r.Hours>0
                  else r.Hours * r.PaymentAmount,
        axis=1
    )
    df['PaidEarnings'] = df.apply(lambda r: r.Earnings if r.Paid else 0.0, axis=1)

    agg = df.groupby(['Month','ClientID'], as_index=False).agg(
        TotalHours    = ('Hours','sum'),
        TotalEarnings = ('Earnings','sum'),
        TotalPaid     = ('PaidEarnings','sum')
    )

    month_list  = sorted(df.Month.unique(), reverse=True)
    parent_ids  = [p for p in clients.ClientID if clients.set_index('ClientID').loc[p,'ParentID']=='' ]
    parent_names= [name_map[p] for p in parent_ids]
    sel_months  = request.args.getlist('month')
    sel_clients = request.args.getlist('client')

    summary=[]
    for month, mdf in agg.groupby('Month'):
        if sel_months and month not in sel_months: continue
        for p in parent_ids:
            if sel_clients and name_map[p] not in sel_clients: continue
            sub = mdf[mdf.ClientID.isin(children.get(p,[]))]
            children_list = [{
                'ClientName':    name_map[r.ClientID],
                'TotalHours':    r.TotalHours,
                'TotalEarnings': r.TotalEarnings,
                'TotalPaid':     r.TotalPaid
            } for _,r in sub.iterrows()]
            own = mdf[mdf.ClientID==p]
            own_h = float(own.TotalHours.sum())    if not own.empty else 0.0
            own_e = float(own.TotalEarnings.sum()) if not own.empty else 0.0
            own_p = float(own.TotalPaid.sum())     if not own.empty else 0.0
            tot_h = own_h + sum(c['TotalHours']    for c in children_list)
            tot_e = own_e + sum(c['TotalEarnings'] for c in children_list)
            tot_p = own_p + sum(c['TotalPaid']     for c in children_list)
            summary.append({
                'Month':         month,
                'ParentName':    name_map[p],
                'Children':      children_list,
                'OwnHours':      own_h,
                'OwnEarnings':   own_e,
                'OwnPaid':       own_p,
                'TotalHours':    tot_h,
                'TotalEarnings': tot_e,
                'TotalPaid':     tot_p,
                'TotalPending':  tot_e - tot_p
            })

    total_earn  = sum(i['TotalEarnings'] for i in summary)
    total_paid  = sum(i['TotalPaid']     for i in summary)
    total_pend  = total_earn - total_paid

    return render_template('monthly_summary.html',
        summary            = summary,
        month_list         = month_list,
        parent_names       = parent_names,
        sel_months         = sel_months,
        sel_clients        = sel_clients,
        total_earnings     = total_earn,
        total_paid         = total_paid,
        total_pending      = total_pend,
        total_earnings_eur = total_earn * exc_rate,
        total_paid_eur     = total_paid * exc_rate,
        total_pending_eur  = total_pend * exc_rate,
        user_currency      = user_curr
    )


@app.route('/tasks/pending_count')
@login_required
def pending_count():
    _, tasks, _, _ = load_user_data()
    count = int((tasks.Status!='Completed').sum())
    return jsonify(pending=count)

if __name__=='__main__':
    app.run(host="127.0.0.1", port=5000, debug=True)

