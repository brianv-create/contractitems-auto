# ContractItems Auto — Setup (10 minutes)

This is a **separate** project from RES. Different repo, different Netlify site, but the SubHub token is the same one you already use for `res-auto`.

## Step 1 — Move this folder out of RES

The kit is currently inside `C:\Users\Brian\Documents\Claude\Projects\RES\contractitems-auto\` because that's the only folder I have file access to. Move it to its own home:

In File Explorer, drag the **`contractitems-auto`** folder out of `RES` and drop it next to it, so the path becomes:

```
C:\Users\Brian\Documents\Claude\Projects\contractitems-auto\
```

(Or anywhere you prefer — just not inside `RES`.)

## Step 2 — Create a new GitHub repo

1. Go to **github.com/new**.
2. Name: `contractitems-auto`.
3. Set to **Private**.
4. Don't check any of the "Add a README/.gitignore" boxes.
5. Click **Create repository**.
6. From the next page, copy the three lines under "**…or push an existing repository from the command line**".

## Step 3 — Push the folder

In Command Prompt:

```bash
cd "C:\Users\Brian\Documents\Claude\Projects\contractitems-auto"
git init
git add .
git commit -m "initial"
git branch -M main
git remote add origin https://github.com/brianv-create/contractitems-auto.git
git push -u origin main
```

(Replace the `git remote add origin` line with the URL from your repo's setup page if different.)

## Step 4 — Add the SubHub secret

Same token you have on `res-auto`. Either:

**Option A — Reuse from `res-auto`**
1. In a browser, log into SubHub (main / vpp-texas account).
2. F12 → Console → paste:
   ```js
   copy(localStorage.getItem('subhubToken'))
   ```
3. New repo → **Settings → Secrets and variables → Actions → New repository secret**.
   - Name: `SUBHUB_TOKEN`
   - Value: paste
   - **Add secret**.

**Option B — Copy the existing token from your `res-auto` repo**

GitHub doesn't let you read existing secrets back, so easiest path is just Option A. (When the token expires, you'll need to update **both** repos — both use it.)

## Step 5 — Connect Netlify

1. **netlify.com → Add new site → Import an existing project → GitHub** → select `contractitems-auto`.
2. **Build settings:**
   - Branch to deploy: `main`
   - Build command: *(leave empty)*
   - Publish directory: `.`
3. Click **Deploy**.
4. Once it deploys (~30 sec), open **Site configuration → General → Site information → Change site name**.
5. Type **`contractitems`** → save. Your URL becomes `https://contractitems.netlify.app`.

(If "contractitems" is taken because your old site is still squatting on it, first go to your old Netlify site and rename it to something like `contractitems-old`, then come back and claim `contractitems` for the new one.)

## Step 6 — Run it once

In your new repo → **Actions** tab → **Update ContractItems Report** → **Run workflow** → green button.

Should finish in ~3 minutes. The run does:
- Scrape SubHub (~1–2 min)
- Run the updater on `report_out.html`
- Commit the updated HTML back to the repo
- Netlify automatically detects the commit and redeploys (~30 sec)

After it's green, https://contractitems.netlify.app/report_out.html shows the live report with today's data.

## Step 7 — Schedule

The workflow auto-runs at **9:25 AM and 3:25 PM Central Time** (off-peak times for reliability — same reason we moved RES off the hour). No further setup.

---

## Ongoing maintenance

Two things to do periodically:

1. **When the SubHub token expires** (every couple weeks): build will fail with `401`. Refresh `SUBHUB_TOKEN` in **both** `res-auto` and `contractitems-auto` repos.

2. **When new closes appear in SubHub but not in the report** (DCE/GHL links missing): run the **DCE scraper** + **GHL mapping** scripts you have, save the enriched JSON as `dce_cache.json`, and commit it to this repo:

   ```bash
   cd "C:\Users\Brian\Documents\Claude\Projects\contractitems-auto"
   # replace dce_cache.json with the new enriched file
   git add dce_cache.json
   git commit -m "refresh DCE cache"
   git pull --rebase
   git push
   ```

   The next scheduled run will pick up new deals + missing links.

That's it. Same maintenance pattern as your RES setup — just two repos to keep tokens fresh on.
