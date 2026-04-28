"""
SubHub Milestone Scraper — Python version of 4. subhub.txt
Runs in GitHub Actions using SUBHUB_TOKEN from environment/secrets.
"""

import os, json, time, sys
from datetime import datetime
import requests

OFFICE_ID  = '5334'
API_BASE   = f'https://api.virtualsaleportal.com/api/{OFFICE_ID}'
TOKEN      = os.environ.get('SUBHUB_TOKEN', '')
BATCH_SIZE = 5
BATCH_DELAY = 0.35   # seconds between batches (polite rate limit)

MILESTONE_MAP = {
    'ACH':                    'ach_status',
    'Customer Agreement':     'agreement_status',
    'Utility Bill':           'utility_bill_status',
    'Welcome Call':           'welcome_call_status',
    'Title Verification':     'title_verification_status',
    'Shade Study':            'shade_study_status',
    'Building Planset':       'building_planset_status',
    'Building Permit':        'building_permit_status',
    'NTP for Install?':       'ntp_install_status',
    'Monitoring Specification':'monitoring_spec_status',
    'As-Built Planset':       'as_built_status',
    'Inspection Card':        'inspection_card_status',
    'Permission To PTO':      'permission_pto_status',
    'PTO Status':             'pto_status',
    'Install Photo Approval': 'install_photo_status',
    'M1 Approval Status':     'm1_status',
    'M2 Approval Status':     'm2_status',
}

def scrape():
    if not TOKEN:
        print('ERROR: SUBHUB_TOKEN not set.', file=sys.stderr)
        sys.exit(1)

    headers = {
        'Authorization': f'Bearer {TOKEN}',
        'Accept': 'application/json',
    }

    # --- Fetch all projects ---
    print('Fetching projects...')
    resp = requests.get(
        f'{API_BASE}/projects?page=1&limit=500&sorting_col=created_at&sorting_dir=desc',
        headers=headers, timeout=60
    )
    if resp.status_code == 401:
        print('ERROR: SubHub token expired. Refresh SUBHUB_TOKEN in GitHub Secrets.', file=sys.stderr)
        sys.exit(1)
    resp.raise_for_status()

    data = resp.json()
    projects = data.get('data', data) if isinstance(data, dict) else data

    # Paginate if needed
    total = data.get('total', len(projects)) if isinstance(data, dict) else len(projects)
    if total > 500:
        pages = (total + 499) // 500
        for p in range(2, pages + 1):
            r2 = requests.get(
                f'{API_BASE}/projects?page={p}&limit=500&sorting_col=created_at&sorting_dir=desc',
                headers=headers, timeout=60
            )
            if r2.ok:
                extra = r2.json()
                items = extra.get('data', extra) if isinstance(extra, dict) else extra
                projects += items

    print(f'  {len(projects)} projects found')

    # --- Fetch milestones per project ---
    results = []
    errors  = []

    for i in range(0, len(projects), BATCH_SIZE):
        batch = projects[i:i + BATCH_SIZE]
        for proj in batch:
            record = build_record(proj, headers)
            if record:
                results.append(record)
            else:
                errors.append(proj.get('id'))

        processed = min(i + BATCH_SIZE, len(projects))
        if processed % 50 == 0 or processed == len(projects):
            print(f'  Milestones: {processed}/{len(projects)}')

        if i + BATCH_SIZE < len(projects):
            time.sleep(BATCH_DELAY)

    # --- Save output ---
    output = {
        'scraped_at':             datetime.utcnow().isoformat() + 'Z',
        'total_projects':         len(results),
        'projects_with_rejections': sum(
            1 for r in results
            if any('Rejected' in str(r.get(v,'')) for v in MILESTONE_MAP.values())
        ),
        'errors':                 len(errors),
        'rejection_summary':      {},
        'projects':               results,
    }

    out_path = os.path.join(os.path.dirname(__file__), 'subhub_latest.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False)
    print(f'Saved → subhub_latest.json ({len(results)} projects, {len(errors)} errors)')


def build_record(proj, headers):
    proposal_id = proj.get('proposal_id')
    base = {
        'project_id':   proj.get('id'),
        'proposal_id':  proposal_id,
        'customer_name': proj.get('project_name', ''),
        'address': ', '.join(filter(None, [
            proj.get('street',''), proj.get('city',''),
            proj.get('state',''), proj.get('postal_code','')
        ])),
        'phone':    (proj.get('contact') or {}).get('phone_number', ''),
        'stage':    proj.get('stage', ''),
        'job_stage': proj.get('stages', ''),
        'job_type': proj.get('job_type', ''),
        'finance_type': proj.get('finance_type', ''),
        'created_at': proj.get('created_at', ''),
        'updated_at': proj.get('updated_at', ''),
        'closer':   ' '.join(filter(None, [
            proj.get('sales_rep_first_name',''),
            proj.get('sales_rep_last_name','')
        ])),
        'contact_active': (proj.get('contact') or {}).get('active', True),
        'milestones': [],
    }
    # Initialise all milestone fields
    for key in MILESTONE_MAP.values():
        base[key] = ''

    if not proposal_id:
        base['error'] = 'No proposal_id'
        return base

    try:
        r = requests.get(
            f'https://api.virtualsaleportal.com/api/{OFFICE_ID}/proposals/solrite-milestone/{proposal_id}',
            headers=headers, timeout=30
        )
        if not r.ok:
            base['error'] = f'HTTP {r.status_code}'
            return base

        payload = r.json()
        statuses = (payload.get('data') or payload).get('statuses', [])

        milestones = []
        for s in statuses:
            label  = s.get('label', '')
            status = s.get('status', '')
            reason = (s.get('rejection_reason') or '').replace('<br>', ' ').strip()
            # Strip HTML tags
            import re
            reason = re.sub(r'<[^>]+>', '', reason).strip()
            milestones.append({'label': label, 'status': status, 'rejection_reason': reason})

            field = MILESTONE_MAP.get(label)
            if field:
                base[field] = status + (f' [{reason}]' if reason else '')

        base['milestones'] = milestones

    except Exception as e:
        base['error'] = str(e)

    return base


if __name__ == '__main__':
    scrape()
