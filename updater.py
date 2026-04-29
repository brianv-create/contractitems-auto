"""
ContractItems Report Updater
Reads report_out.html + subhub_latest.json, diffs milestones,
detects new closes from dce_cache.json, writes updated HTML.
"""

import os, re, json, sys, csv, io, urllib.request
from datetime import datetime

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
REPORT_PATH  = os.path.join(SCRIPT_DIR, 'report_out.html')
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
CLOSER_SHEET_ID  = '1U-1q0c9WzEbhfRkhMfaLDrp7TYKj0NFYzQeJ_ssB0Oc'
CLOSER_SHEET_GID = '1763606603'

# Only deals closed in this year are kept; older closes are filtered out.
CLOSER_REQUIRED_YEAR = '2026'

def fetch_closer_keys():
    """Return set of (first, last) lowercase tuples from 'Their Full Name' column,
    restricted to rows whose Timestamp (column 0) is in CLOSER_REQUIRED_YEAR."""
    url = f'https://docs.google.com/spreadsheets/d/{CLOSER_SHEET_ID}/gviz/tq?tqx=out:csv&gid={CLOSER_SHEET_GID}'
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            text = r.read().decode('utf-8', errors='replace')
    except Exception as e:
        print(f'  WARNING: could not fetch closer sheet ({e}); filter disabled.')
        return None
    rows = list(csv.reader(io.StringIO(text)))
    keys = set()
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
        parts = [p for p in re.split(r'\s+', r[1].strip().lower()) if p and p != '-']
        if parts:
            keys.add((parts[0], parts[-1]))
    if skipped_year:
        print(f'  ({skipped_year} closer-sheet rows skipped — not in {CLOSER_REQUIRED_YEAR})')
    return keys

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

def save_html(lines):
    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
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
        'email':            '',
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

    print('Loading SubHub data…')
    subhub_data = load_subhub()
    sh_idx      = build_subhub_index(subhub_data)
    print(f'  {len(sh_idx)} SubHub projects')

    print('Loading closer-tracking sheet…')
    closer_keys = fetch_closer_keys()
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
                'ts':      ts + 'T00:00:00.000Z',
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
        row_id  = len(raw_rows)
        new_row = build_new_row(proj, dce_by_phone, dce_by_name, row_id)
        raw_rows.append(new_row)
        existing_names.add(dce_name)
        known_pids[sh_pid] = new_row

        changelog.append({
            'id':      row_id,
            'pid':     new_row['pid'],
            'name':    new_row['input_name'],
            'closer':  new_row['closer'],
            'ts':      ts + 'T00:00:00.000Z',
            'changes': [{'field': 'NEW_DEAL', 'from': None, 'to': new_row['flag']}],
            'note':    f'Auto-added from DCE cache {ts}',
        })
        new_deals_added += 1
        print(f'  + New deal: {new_row["input_name"]} (pid={sh_pid})')

    print(f'  {new_deals_added} new deals added')

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

    save_html(lines)
    print(f'\nSaved report_out.html — {len(raw_rows)} rows, '
          f'{total_milestone_changes} changes, {new_deals_added} new deals.')


if __name__ == '__main__':
    update()
