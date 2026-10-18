# Free cloud runner (GitHub Actions) - applies while your laptop is off

GitHub runs the pipeline for you on a schedule (about 07:00, 10:30, 13:30, 16:30 and 20:00 India time): it reads the
Telegram channel, tailors a resume per job, emails recruiters, fills Google Forms that do not need a sign-in, and
**emails you a summary** with links of anything you still have to do. Cost: $0 (a private repo gets 2,000 free minutes a
month; a run with no new posts takes about 2 minutes).

## What it can and cannot do
| Works in the cloud | Still needs your PC (dashboard) |
|---|---|
| Telegram posts, AI matching, tailored resume | Google Forms that force a Google sign-in |
| Email to recruiters with the PDF attached | Drive-link questions |
| Open Google Forms (no sign-in), company sites | LinkedIn Easy Apply |
Jobs it cannot finish are listed in the summary email with their links.

## One-time setup (about 10 minutes)
1. **Create a PRIVATE repo** on GitHub, empty (for example `auto-job-apply-runner`). Private matters: its run logs and
   saved state stay private.
2. **Push the code there** (the `runner` branch already contains the workflow file):
   `git remote add runner https://github.com/<you>/auto-job-apply-runner.git` then `git push runner runner:main`
3. **Log in to Telegram once for the runner** (a separate login, so your PC session is not kicked out):
   `python -m telegram_apply.login runner`
4. **Create the secrets:** `python deploy/github_actions/export_secrets.py <you>/auto-job-apply-runner`
   It copies each private value to your clipboard; paste it as a repository secret with the shown name.
5. In the repo: **Actions** tab -> *Daily job run* -> **Run workflow**. The first runs are a **dry run** (nothing is sent);
   check the summary email.
6. When happy: repo **Settings -> Secrets and variables -> Actions -> Variables -> New variable** `DRY_RUN` = `false`.

## Important
- Keep **"Run automatically every day" OFF on the PC dashboard** once the cloud runner is live, or both would apply to
  the same job.
- To stop everything: disable the workflow (Actions tab -> Daily job run -> ... -> Disable workflow) or set `DRY_RUN=true`.
- To change settings (batch, channels, minimum fit): edit the `UI_SETTINGS_JSON` secret (copy of `ui_settings.json`).
