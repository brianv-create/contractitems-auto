# ContractItems Auto — SubHub Report Automation

Keeps **contractitems.netlify.app** updated twice a day without any manual uploads.

---

## How it works

1. **GitHub Actions** runs at ~9 AM and ~3 PM CDT every day.
2. `scraper.py` fetches all project milestones from the SubHub API → saves `subhub_latest.json`.
3. `updater.py` diffs milestones against the current `report_out.html`, applies changes, and saves the updated HTML.
4. The updated `report_out.html` is committed back to the repo.
5. **Netlify** detects the new commit and auto-deploys within ~30 seconds.

---

## One-time setup

### Step 1 — Create a new GitHub repo

1. Go to github.com → **New repository** (can be private)
2. Name it something like `contractitems-report`
3. Upload all files from this folder to the repo root
4. Also upload your current `report_out.html` to the repo root

### Step 2 — Add the SubHub token as a GitHub Secret

The scraper authenticates with SubHub using a Bearer token. This token expires periodically and needs to be refreshed.

**To get the token:**
1. Log into [app.subcontractorhub.com](https://app.subcontractorhub.com)
2. Open Chrome DevTools → Console
3. Run: `localStorage.getItem('subhubToken')`
4. Copy the token value

**To save it as a GitHub Secret:**
1. Go to your repo → **Settings** → **Secrets and variables** → **Actions**
2. Click **New repository secret**
3. Name: `SUBHUB_TOKEN`
4. Value: paste the token
5. Click **Add secret**

> **When the token expires:** You'll see a failing Actions run. Refresh the token using the steps above and update the GitHub Secret.

### Step 3 — Connect Netlify to the GitHub repo

1. Log into [netlify.com](https://app.netlify.com)
2. Go to your site → **Site configuration** → **Build & deploy** → **Link to Git**
   *(or: Sites → Add new site → Import an existing project)*
3. Choose **GitHub** → select your repo
4. **Build settings:**
   - Build command: *(leave empty)*
   - Publish directory: `.` *(the repo root)*
5. Click **Deploy site**

After this, every commit to the repo auto-deploys. The drag-and-drop method is no longer needed.

---

## Keeping DCE and GHL links working

The DCE and GHL scrapers require your browser session and cannot be automated. To keep links fresh:

1. Run the **DCE scraper** (`1. DCE scraper.txt`) on dce.solriteenergy.com → downloads `dce_deals_metadata_YYYY-MM-DD.json`
2. Run the **GHL mapping script** (`3. GHL mapping.txt`) on app.gohighlevel.com, select the metadata file → downloads enriched JSON
3. Rename the enriched file to **`dce_cache.json`**
4. Upload `dce_cache.json` to the root of your GitHub repo (replace the existing file)

The next automated run will use this file to:
- Fill in any missing DCE/GHL links for existing rows
- Match new closes to add them automatically

> **Recommended frequency:** Run the DCE + GHL scripts once a week, or whenever you notice new closes appear in SubHub that aren't in the report yet.

---

## File reference

| File | Purpose |
|------|---------|
| `report_out.html` | The live report — updated by every automated run |
| `scraper.py` | Fetches SubHub milestone data via API |
| `updater.py` | Diffs milestones, adds new deals, updates HTML |
| `dce_cache.json` | Enriched DCE metadata — upload manually after running DCE+GHL scripts |
| `known_pids.json` | Auto-managed list of SubHub project IDs already in the report |
| `subhub_latest.json` | Last SubHub snapshot — overwritten each run |
| `.github/workflows/update.yml` | GitHub Actions schedule (9 AM + 3 PM CDT) |
| `requirements.txt` | Python dependencies (just `requests`) |

---

## Troubleshooting

**Actions run fails with "ERROR: SUBHUB_TOKEN not set"**
→ The `SUBHUB_TOKEN` secret is missing. Add it under repo Settings → Secrets.

**Actions run fails with "ERROR: SubHub token expired"**
→ Get a fresh token from `localStorage.getItem('subhubToken')` in the SubHub console and update the GitHub Secret.

**New deals aren't appearing automatically**
→ Upload a fresh `dce_cache.json` (run DCE + GHL scripts, rename, push to repo). The next automated run will add matched deals.

**Netlify isn't auto-deploying**
→ Check that the repo is connected under Site configuration → Build & deploy → Linked repository.
