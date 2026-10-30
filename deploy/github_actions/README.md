# Free cloud runner (GitHub Actions): no PC, no card, use it from your phone

GitHub runs the pipeline for you:
- **Every hour from 06:00 to 23:00 India time** it reads your Telegram channels, tailors a resume per matching job,
  emails recruiters, fills Google Forms that do not need a sign-in, and applies on company sites.
- **Whenever you want to apply to a company:** open the repo on your phone -> **Actions -> Job runner -> Run workflow**,
  paste the job post and/or its link, tap **Run workflow**. A minute or two later you get an email with the result.
- After every run you get an **email summary**, with links of anything you still have to do by hand.

Cost: $0 and no card. A private repo gets 2,000 free minutes a month; the hourly checks use roughly 1,000-1,400.

## What it can and cannot do
| Works in the cloud | Still needs your PC (dashboard) |
|---|---|
| Telegram posts, AI matching, tailored resume | Google Forms that force a Google sign-in |
| Email to recruiters with the PDF attached | Drive-link questions |
| Google Forms (no sign-in), company sites | LinkedIn Easy Apply |
Jobs it cannot finish are listed in the email with their links.

## One-time setup (about 15 minutes, on your PC)
1. **Create a PRIVATE repo** on GitHub: https://github.com/new -> name `auto-job-apply-runner`, choose **Private**,
   do not add a README. Private matters: its run logs and saved state stay private.
2. **Push the code there** (the `runner` branch already contains the workflow), from the project folder:
   ```
   git remote add runner https://github.com/hari-om65/auto-job-apply-runner.git
   git push runner runner:main
   ```
3. **Log in to Telegram once for the runner** (a separate login, so your PC's login is not kicked out):
   `python -m telegram_apply.login runner`  (enter your phone number and the code Telegram sends)
4. **Create the secrets:** `python deploy/github_actions/export_secrets.py hari-om65/auto-job-apply-runner`
   It opens the GitHub secrets page and copies each value to your clipboard; paste it as a repository secret with the
   name shown. Your passwords and Telegram login are stored encrypted by GitHub and never appear in the code or logs.
5. **Test it:** Actions tab -> *Job runner* -> **Run workflow** (leave the boxes empty) -> Run. The first runs are a
   **dry run** (nothing is sent); check the summary email.
6. **Go live:** repo **Settings -> Secrets and variables -> Actions -> Variables -> New variable** `DRY_RUN` = `false`.

## Using it from your phone
- Use the **GitHub app** or github.com in your phone's browser (sign in once). Open `auto-job-apply-runner` ->
  **Actions** -> **Job runner** -> **Run workflow**. If the app does not show the button, use the browser.
- Box 1: the job post / description. Box 2: the apply link or email (optional if it is in the post).
  "Ignore filters" is on: the job is applied to even if the batch or fit score would normally skip it.
- Only one run waits in line at a time: if you add a job while another run is going and then add a second one, the
  first waiting one is replaced. Wait for the result email before adding the next job.

## Important
- Turn the PC dashboard's **automatic runs off** (or the whole PC task: `Unregister-ScheduledTask -TaskName JobDashboard -Confirm:$false`),
  or both would apply to the same jobs.
- Stop everything: Actions tab -> Job runner -> ... -> **Disable workflow**, or set the `DRY_RUN` variable to `true`.
- Change settings (batch, channels, minimum fit): edit the `UI_SETTINGS_JSON` secret (copy of `ui_settings.json`).
- After you change your config or resume on the PC, run step 4 again for the secret that changed.
- GitHub sometimes starts scheduled runs 5-30 minutes late; that is normal.
