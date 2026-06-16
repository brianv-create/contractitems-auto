"""
ContractItems Report Updater
Reads report_out.html + subhub_latest.json, diffs milestones,
detects new closes from dce_cache.json, writes updated HTML.
"""

import os, re, json, sys, csv, io, urllib.request
from datetime import datetime

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
REPORT_PATH  = os.path.join(SCRIPT_DIR, 'report_out.html')
REPORT_DASHBOARD_PATH = os.path.join(SCRIPT_DIR, 'dashboard.html')
SUBHUB_PATH  = os.path.join(SCRIPT_DIR, 'subhub_latest.json')
DCE_CACHE    = os.path.join(SCRIPT_DIR, 'dce_cache.json')
KNOWN_PIDS   = os.path.join(SCRIPT_DIR, 'known_pids.json')

# The 5 milestones that determine the row's flag colour
FLAG_MILESTONES = ['ACH', 'Customer Agreement', 'Utility Bill', 'Welcome Call', 'Title Verification']

ALL_MILESTONE_LABELS = [
    'ACH', 'Customer Agreement', 'Utility Bill', 'Welcome Call',
    'Title Verification', 'Shade Study', 'Building Planset', 'Building Permit',
    'NTP for Install?', 'Monitoring Specification', 'As-Built Planset',
    'Inspection Card', 'Permission To PTO', 'PTO Status',
    'Install Photo Approval', 'M1 Approval Status', 'M2 Approval Status',
]

SUBHUB_BASE_URL = 'https://app.subcontractorhub.com/solrite-electric-llc-vpp-texas/projects/detail/'

# ── Closer-tracking sheet ──────────────────────────────────────────────────────
# The source of truth for which SubHub projects are real closed deals.
# A SubHub project is added to / kept in the report only if its customer name
# matches an entry in this sheet.
CLOSER_SHEET_ID  = '1q58PO-UbDtQLEGe4bVAvLbAovYknh7d4Fu2Z2xdRulA'
CLOSER_SHEET_GID = '1352249267'   # tab: "Closed All"

# Only deals closed in this year are kept; older closes are filtered out.
CLOSER_REQUIRED_YEAR = '2026'

def fetch_closer_keys():
    """Return ({(first,last) tuples}, {emails lowercased}) for the 'Their Full Name'
    and 'Their Email' columns of the closer sheet (only current-year rows)."""
    url = f'https://docs.google.com/spreadsheets/d/{CLOSER_SHEET_ID}/gviz/tq?tqx=out:csv&gid={CLOSER_SHEET_GID}'
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            text = r.read().decode('utf-8', errors='replace')
    except Exception as e:
        print(f'  WARNING: could not fetch closer sheet ({e}); filter disabled.')
        return None
    rows = list(csv.reader(io.StringIO(text)))
    keys = set()
    emails = set()
    skipped_year = 0
    for r in rows[1:]:
        if len(r) < 2 or not r[1].strip():
            continue
        ts = (r[0] or '').strip()
        m = re.search(r'/(\d{4})\b', ts)
        year = m.group(1) if m else ''
        if year != CLOSER_REQUIRED_YEAR:
            skipped_year += 1
            continue
        for c in name_candidates(r[1]):
            keys.add(c)
        em = (r[2] if len(r) > 2 else '').strip().lower()
        if em and '@' in em:
            emails.add(em)
    if skipped_year:
        print(f'  ({skipped_year} closer-sheet rows skipped — not in {CLOSER_REQUIRED_YEAR})')
    return (keys, emails)

def name_candidates(name):
    """(first, last) tuples for a customer name. All-pairs + reversed so
    'Melonie Cogbill' pairs with 'K COGBILL TRUST MELONIE'. Strips trust/
    LLC/family noise plus the usual Jr/Sr/Ref."""
    n = (name or '').strip()
    n = re.sub(r'\([^)]*\)', ' ', n)
    n = re.sub(r'[\-/,]', ' ', n)
    NOISE = {'referral', 'ref', 'jr', 'sr', 'ii', 'iii', 'iv',
             'trust', 'llc', 'family', 'estate', 'and', 'the'}
    parts = [re.sub(r'[^a-z]', '', p) for p in n.lower().split()]
    parts = [p for p in parts if p and p not in NOISE]
    if not parts:
        return set()
    if len(parts) == 1:
        return {(parts[0], parts[0])}
    cands = set()
    for i, a in enumerate(parts):
        for b in parts[i+1:]:
            cands.add((a, b))
            cands.add((b, a))
    return cands

def in_closer_set(name, closer_keys):
    """True if name matches a closer-sheet entry by first+last token.
    Strips parenthetical suffixes ('Jessica Mulkey (Michael Mulkey)' -> 'Jessica Mulkey'),
    trailing Referral/Ref/Jr-style notations, and stray punctuation so the filter
    doesn't drop legit deals with messy names."""
    if closer_keys is None:
        return True
    n = (name or '').strip()
    n = re.sub(r'\([^)]*\)', ' ', n)            # drop ()-content
    n = re.sub(r'[\-/,]', ' ', n)                # treat dashes, slashes, commas as space
    NOISE = {'referral', 'ref', 'jr', 'sr', 'ii', 'iii', 'iv'}
    parts = [re.sub(r'[^a-z]', '', p) for p in n.lower().split()]
    parts = [p for p in parts if p and p not in NOISE]
    if not parts:
        return False
    candidates = {(parts[0], parts[-1])}
    if len(parts) >= 2:
        candidates.add((parts[0], parts[1]))      # first + second word
        candidates.add((parts[-2], parts[-1]))    # last two words
    return any(c in closer_keys for c in candidates)



# ── helpers ────────────────────────────────────────────────────────────────────

def parse_status(val):
    """Strip any trailing [reason] from a milestone value."""
    if not val:
        return ''
    val = str(val).strip()
    m = re.match(r'^(.*?)\s*\[(.*)]\s*$', val, re.DOTALL)
    return m.group(1).strip() if m else val

def compute_flag(milestones):
    """Compute row flag from milestone dict (same logic as JS computeFlag)."""
    statuses = [milestones.get(lbl, '') for lbl in FLAG_MILESTONES]
    if any(parse_status(s).upper() == 'REJECTED' for s in statuses):
        return 'rejected'
    # Treat empty / missing milestones as N/A (not blocking 'approved'). A deal
    # is approved when every recorded contract-item milestone is APPROVED.
    non_empty = [s for s in statuses if s and parse_status(s).strip()]
    if non_empty and all(parse_status(s).upper() == 'APPROVED' for s in non_empty):
        return 'approved'
    return 'pending'

def normalize_name(name):
    """Lowercase, strip extra spaces — for fuzzy matching."""
    return ' '.join(str(name or '').lower().split())

def today_month():
    now = datetime.now()
    return now.strftime('%B %Y')   # e.g. "April 2026"

def today_iso():
    return datetime.now().strftime('%Y-%m-%d')

def today_display():
    now = datetime.now()
    return now.strftime('%A, %b %-d, %Y')  # e.g. "Tuesday, Apr 28, 2026"

# ── HTML I/O ───────────────────────────────────────────────────────────────────

def load_html():
    with open(REPORT_PATH, 'r', encoding='utf-8') as f:
        return f.readlines()

def next_row_id(raw_rows):
    used = {r.get('id') for r in raw_rows if isinstance(r.get('id'), int)}
    nid = (max(used) if used else -1) + 1
    while nid in used:
        nid += 1
    return nid

def dedupe_row_ids(raw_rows):
    seen = {}
    fixed = 0
    for row in raw_rows:
        rid = row.get('id')
        if rid in seen:
            new_id = next_row_id(raw_rows)
            row['id'] = new_id
            seen[new_id] = row
            fixed += 1
        else:
            seen[rid] = row
    return fixed

EXTRA_CLOSERS = ['David Mueller']
EXTRA_MONTHS  = ['May 2026', 'June 2026']

def rebuild_closer_dropdown(html_text, raw_rows):
    closers = set()
    for r in raw_rows:
        c = (r.get('closer') or '').strip()
        if c: closers.add(c)
    closers.update(EXTRA_CLOSERS)
    options = '<option value="">All Closers</option>' + ''.join(
        f'<option value="{c}">{c}</option>' for c in sorted(closers, key=str.lower)
    )
    new_sel = f'<select id="filter-closer" onchange="applyFilters()">{options}</select>'
    return re.sub(
        r'<select id="filter-closer"[^>]*>.*?</select>',
        new_sel, html_text, count=1, flags=re.DOTALL,
    )

def rebuild_month_dropdown(html_text, raw_rows):
    """Replace the <select id="filter-month"> options with the distinct months present in raw_rows."""
    months = set()
    for r in raw_rows:
        m = (r.get('month') or '').strip()
        if m:
            months.add(m)
    months.update(EXTRA_MONTHS)
    MN = ['January','February','March','April','May','June',
          'July','August','September','October','November','December']
    def _key(m):
        if m == 'Unknown': return (9999, 99)
        parts = m.split()
        if len(parts) == 2 and parts[0] in MN and parts[1].isdigit():
            return (int(parts[1]), MN.index(parts[0]))
        return (9998, 0)
    sorted_months = sorted(months, key=_key)
    options = '<option value="">All Months</option>' + ''.join(
        f'<option value="{m}">{m}</option>' for m in sorted_months
    )
    new_sel = f'<select id="filter-month" onchange="applyFilters()">{options}</select>'
    return re.sub(
        r'<select id="filter-month"[^>]*>.*?</select>',
        new_sel,
        html_text,
        count=1,
        flags=re.DOTALL
    )


def save_html(lines):
    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    with open(REPORT_DASHBOARD_PATH, 'w', encoding='utf-8') as f:
        f.writelines(lines)

def extract_line(lines, prefix):
    """Find the line that starts with `prefix`, return (index, parsed JSON)."""
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(prefix):
            json_str = stripped[len(prefix):].rstrip(';').rstrip()
            return i, json.loads(json_str)
    raise ValueError(f'Could not find line starting with: {prefix}')

def inject_line(lines, index, prefix, data):
    """Replace line at index with updated JSON."""
    lines[index] = prefix + json.dumps(data, ensure_ascii=False) + ';\n'

# ── SubHub data ────────────────────────────────────────────────────────────────

def load_subhub():
    with open(SUBHUB_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)

def build_subhub_index(subhub_data):
    """Index by project_id (matches `pid` in RAW_ROWS)."""
    idx = {}
    for p in subhub_data.get('projects', []):
        pid = str(p.get('project_id', ''))
        if pid:
            idx[pid] = p
    return idx

def milestones_from_subhub(proj):
    """
    Extract milestone dict + rejection_reasons from a SubHub project record.
    Only stores entries with a meaningful status (skips None / empty / "Not Yet").
    """
    milestones = {}
    reasons    = {}
    for m in proj.get('milestones', []):
        label  = m.get('label', '')
        status = m.get('status', '') or ''
        reason = m.get('rejection_reason', '') or ''
        if label not in ALL_MILESTONE_LABELS:
            continue
        status = status.strip()
        if status and status not in ('Not Yet',):
            milestones[label] = status
        if reason.strip():
            reasons[label] = reason.strip()
    return milestones, reasons

# ── DCE cache ──────────────────────────────────────────────────────────────────

def load_dce_cache():
    """
    dce_cache.json is the enriched DCE metadata JSON (with ghl_contact_url added).
    Returns (by_phone dict, by_name dict, raw_list).
    """
    if not os.path.exists(DCE_CACHE):
        return {}, {}, []
    with open(DCE_CACHE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    items = data if isinstance(data, list) else data.get('data', [])
    by_phone = {}
    by_name  = {}
    for d in items:
        phone = re.sub(r'\D', '', str(d.get('contact_phone', '') or ''))[-10:]
        name  = normalize_name(d.get('contact_name', ''))
        if phone:
            by_phone[phone] = d
        if name:
            by_name[name] = d
    return by_phone, by_name, items

# ── Milestone diff ──────────────────────────────────────────────────────────────

def diff_milestones(old_milestones, new_milestones):
    """Return list of {field, from, to} for meaningful milestone changes."""
    changes = []
    all_labels = set(list(old_milestones.keys()) + list(new_milestones.keys()))
    for label in ALL_MILESTONE_LABELS:
        if label not in all_labels:
            continue
        old_v = parse_status(old_milestones.get(label, ''))
        new_v = parse_status(new_milestones.get(label, ''))
        if old_v == new_v:
            continue
        # Skip cosmetic Not Yet → empty / None
        if old_v in ('Not Yet', '') and new_v == '':
            continue
        changes.append({'field': label, 'from': old_v or None, 'to': new_v or None})
    return changes

# ── New deal building ───────────────────────────────────────────────────────────

def build_new_row(proj, dce_by_phone, dce_by_name, row_id):
    """Build a RAW_ROWS entry from a SubHub project dict."""
    phone_raw = (proj.get('contact') or {}).get('phone_number', '') or proj.get('phone', '')
    phone     = re.sub(r'\D', '', str(phone_raw))[-10:] if phone_raw else ''

    milestones, reasons = milestones_from_subhub(proj)

    # DCE enrichment
    dce_entry = dce_by_phone.get(phone) or dce_by_name.get(normalize_name(proj.get('customer_name', ''))) or {}
    dce_url   = dce_entry.get('url', '')
    ghl_url   = dce_entry.get('ghl_contact_url', '')

    email     = str(proj.get('email', '') or '').strip()
    closer    = str(proj.get('closer', '') or '').strip()
    city      = ''
    addr      = proj.get('address', '')
    if addr and ',' in addr:
        parts = [p.strip() for p in addr.split(',')]
        if len(parts) >= 2:
            city = parts[1]

    pid      = str(proj.get('project_id', ''))
    name     = str(proj.get('customer_name', '') or '').strip()

    return {
        'id':               row_id,
        'pid':              int(pid) if pid.isdigit() else pid,
        'input_name':       name,
        'db_name':          name,
        'email':            email,
        'closer':           closer,
        'month':            today_month(),
        'url':              SUBHUB_BASE_URL + pid,
        'flag':             compute_flag(milestones),
        'milestones':       milestones,
        'dce_url':          dce_url,
        'ghl_url':          ghl_url,
        'rejection_reasons': reasons,
        'city':             city,
        'pending_since':    {},
    }

# ── Known PIDs ─────────────────────────────────────────────────────────────────

def load_known_pids():
    if not os.path.exists(KNOWN_PIDS):
        return set()
    with open(KNOWN_PIDS, 'r') as f:
        return set(json.load(f))

def save_known_pids(pids):
    with open(KNOWN_PIDS, 'w') as f:
        json.dump(sorted(pids), f)

# ── Main update ────────────────────────────────────────────────────────────────

def update():
    print('Loading report HTML…')
    lines = load_html()

    raw_idx, raw_rows = extract_line(lines, 'const RAW_ROWS = ')
    cl_idx,  changelog = extract_line(lines, 'const CHANGELOG = ')

    print(f'  {len(raw_rows)} existing rows')
    fixed = dedupe_row_ids(raw_rows)
    if fixed:
        print(f'  Renumbered {fixed} row(s) with duplicate id')

    print('Loading SubHub data…')
    subhub_data = load_subhub()
    sh_idx      = build_subhub_index(subhub_data)
    print(f'  {len(sh_idx)} SubHub projects')

    print('Loading closer-tracking sheet…')
    _ck = fetch_closer_keys()
    closer_keys, closer_emails = (_ck if _ck else (None, set()))
    if closer_keys is not None:
        print(f'  {len(closer_keys)} closed deals on the sheet')
        # Drop existing rows whose customer is no longer (or was never) a real closed deal
        before = len(raw_rows)
        raw_rows = [r for r in raw_rows
                    if in_closer_set(r.get('db_name') or r.get('input_name', ''), closer_keys)]
        dropped = before - len(raw_rows)
        if dropped:
            print(f'  Dropped {dropped} non-closer row(s)')

    print('Loading DCE cache…')
    dce_by_phone, dce_by_name, dce_items = load_dce_cache()
    print(f'  {len(dce_items)} DCE entries')

    # Build index of current RAW_ROWS by pid
    known_pids = {str(r['pid']): r for r in raw_rows}

    ts = today_iso()
    ts_precise = datetime.utcnow().isoformat() + 'Z'
    total_milestone_changes = 0
    total_link_enrichments  = 0

    # ── 1. Diff milestones for existing rows ──────────────────────────────────
    print('Diffing milestones…')
    for row in raw_rows:
        pid_str = str(row['pid'])
        if pid_str not in sh_idx:
            continue

        proj = sh_idx[pid_str]
        new_milestones, new_reasons = milestones_from_subhub(proj)
        old_milestones = row.get('milestones', {})

        changes = diff_milestones(old_milestones, new_milestones)
        if changes:
            row['milestones'] = new_milestones
            row['rejection_reasons'] = new_reasons
            row['flag'] = compute_flag(new_milestones)
            changelog.append({
                'id':      row['id'],
                'pid':     row['pid'],
                'name':    row.get('input_name', ''),
                'closer':  row.get('closer', ''),
                'ts':      ts_precise,
                'changes': changes,
                'note':    '',
            })
            total_milestone_changes += len(changes)
        else:
            # Still refresh flag in case Firebase edits would affect it
            row['flag'] = compute_flag(new_milestones if new_milestones else old_milestones)

        # ── Enrich DCE/GHL links if missing ──
        if not row.get('dce_url') or not row.get('ghl_url'):
            phone = re.sub(r'\D', '', str(row.get('email', '') or ''))
            # Try phone from DCE by name
            name_key = normalize_name(row.get('db_name', '') or row.get('input_name', ''))
            dce_entry = dce_by_name.get(name_key, {})
            if dce_entry:
                if not row.get('dce_url') and dce_entry.get('url'):
                    row['dce_url'] = dce_entry['url']
                    total_link_enrichments += 1
                if not row.get('ghl_url') and dce_entry.get('ghl_contact_url'):
                    row['ghl_url'] = dce_entry['ghl_contact_url']

    print(f'  {total_milestone_changes} milestone changes recorded')
    print(f'  {total_link_enrichments} DCE/GHL links enriched')

    # ── 2. Detect new closes from DCE cache ───────────────────────────────────
    print('Checking for new closes from DCE cache…')
    new_deals_added = 0

    # Normalised names already in report
    existing_names = {normalize_name(r.get('db_name') or r.get('input_name', ''))
                      for r in raw_rows}

    # Build SubHub name→pid index for matching
    sh_name_idx = {}
    for pid_str, proj in sh_idx.items():
        cname = normalize_name(proj.get('customer_name', ''))
        if cname:
            sh_name_idx[cname] = pid_str

    for dce_entry in dce_items:
        dce_name = normalize_name(dce_entry.get('contact_name', ''))
        if not dce_name or dce_name in existing_names:
            continue
        # Skip leads that aren't actually closed deals yet
        if not in_closer_set(dce_entry.get('contact_name',''), closer_keys):
            continue

        # Try to find in SubHub by name
        sh_pid = sh_name_idx.get(dce_name)
        if not sh_pid:
            # Try partial match (first + last word)
            parts = dce_name.split()
            if len(parts) >= 2:
                short = parts[0] + ' ' + parts[-1]
                sh_pid = sh_name_idx.get(short)

        if not sh_pid:
            print(f'  ⚠  New DCE deal not found in SubHub: {dce_entry.get("contact_name")}')
            continue

        proj    = sh_idx[sh_pid]
        row_id  = next_row_id(raw_rows)
        new_row = build_new_row(proj, dce_by_phone, dce_by_name, row_id)
        raw_rows.append(new_row)
        existing_names.add(dce_name)
        known_pids[sh_pid] = new_row

        changelog.append({
            'id':      row_id,
            'pid':     new_row['pid'],
            'name':    new_row['input_name'],
            'closer':  new_row['closer'],
            'ts':      ts_precise,
            'changes': [{'field': 'NEW_DEAL', 'from': None, 'to': new_row['flag']}],
            'note':    f'Auto-added from DCE cache {ts}',
        })
        new_deals_added += 1
        print(f'  + New deal: {new_row["input_name"]} (pid={sh_pid})')

    print(f'  {new_deals_added} new deals added (DCE)')

    # ── 2b. Detect new closes via closer sheet → SubHub directly ──────────────
    # Catches deals on the closer sheet that ARE in SubHub but missed by the
    # DCE pass (e.g. DCE cache is days behind the sheet). Row goes in with
    # empty DCE/GHL — next DCE refresh's enrichment block fills those in.
    closer_added = 0
    if closer_keys:
        existing_candidates = set()
        for row in raw_rows:
            existing_candidates |= name_candidates(
                row.get('db_name') or row.get('input_name', ''))

        sh_candidate_idx = {}
        sh_email_idx = {}
        for pid_str, proj in sh_idx.items():
            for c in name_candidates(proj.get('customer_name', '')):
                sh_candidate_idx.setdefault(c, pid_str)
            em = (proj.get('email') or '').strip().lower()
            if em and '@' in em:
                sh_email_idx.setdefault(em, pid_str)

        print('Discovering new closes via closer sheet -> SubHub...')
        for closer_key in closer_keys:
            if closer_key in existing_candidates:
                continue
            sh_pid = sh_candidate_idx.get(closer_key)
            if not sh_pid:
                continue   # not in SubHub yet — silent skip
            if sh_pid in known_pids:
                continue

            proj    = sh_idx[sh_pid]
            row_id  = next_row_id(raw_rows)
            new_row = build_new_row(proj, dce_by_phone, dce_by_name, row_id)
            raw_rows.append(new_row)
            existing_candidates |= name_candidates(
                new_row.get('db_name') or new_row.get('input_name', ''))
            known_pids[sh_pid] = new_row

            changelog.append({
                'id':      row_id,
                'pid':     new_row['pid'],
                'name':    new_row['input_name'],
                'closer':  new_row['closer'],
                'ts':      ts_precise,
                'changes': [{'field': 'NEW_DEAL', 'from': None, 'to': new_row['flag']}],
                'note':    f'Auto-added from closer sheet {ts}',
            })
            closer_added += 1
            print(f'  + New deal (closer sheet): {new_row["input_name"]} (pid={sh_pid})')

        # ── 2c. Catch any closer-sheet entry whose SubHub record uses a
        # different spelling but the same email ─────────────────────────────
        existing_emails = {(r.get('email') or '').strip().lower() for r in raw_rows}
        for em in closer_emails:
            if em in existing_emails:
                continue
            sh_pid = sh_email_idx.get(em)
            if not sh_pid:
                continue
            if sh_pid in known_pids:
                continue
            proj    = sh_idx[sh_pid]
            row_id  = next_row_id(raw_rows)
            new_row = build_new_row(proj, dce_by_phone, dce_by_name, row_id)
            raw_rows.append(new_row)
            existing_emails.add(em)
            known_pids[sh_pid] = new_row
            changelog.append({
                'id': row_id, 'pid': new_row['pid'],
                'name': new_row['input_name'], 'closer': new_row['closer'],
                'ts': ts_precise,
                'changes': [{'field': 'NEW_DEAL', 'from': None, 'to': new_row['flag']}],
                'note': f'Auto-added from closer sheet (email match) {ts}',
            })
            closer_added += 1
            print(f'  + New deal (email match): {new_row["input_name"]} (pid={sh_pid}, email={em})')

        print(f'  {closer_added} new deals added (closer sheet)')

    new_deals_added += closer_added

    # ── 3. Save known_pids ────────────────────────────────────────────────────
    save_known_pids(set(str(r['pid']) for r in raw_rows))

    # ── 4. Update header date ──────────────────────────────────────────────────
    disp = today_display()
    new_lines = []
    for line in lines:
        if 'Updated:' in line and ('Jan' in line or 'Feb' in line or 'Mar' in line
                                   or 'Apr' in line or 'May' in line or 'Jun' in line
                                   or 'Jul' in line or 'Aug' in line or 'Sep' in line
                                   or 'Oct' in line or 'Nov' in line or 'Dec' in line):
            # Replace the date string after "Updated: "
            line = re.sub(
                r'(Updated:\s*)\w+,\s+\w+\s+\d+,\s+\d{4}',
                r'\g<1>' + disp,
                line
            )
        new_lines.append(line)
    lines = new_lines

    # ── 5. Inject updated data ─────────────────────────────────────────────────
    inject_line(lines, raw_idx, 'const RAW_ROWS = ', raw_rows)
    inject_line(lines, cl_idx,  'const CHANGELOG = ', changelog)

    # Rebuild the month-filter dropdown so newly-arrived months appear in the UI
    joined = ''.join(lines)
    joined = rebuild_month_dropdown(joined, raw_rows)
    joined = rebuild_closer_dropdown(joined, raw_rows)
    lines = joined.splitlines(keepends=True)

    save_html(lines)
    print(f'\nSaved report_out.html — {len(raw_rows)} rows, '
          f'{total_milestone_changes} changes, {new_deals_added} new deals.')


if __name__ == '__main__':
    update()
