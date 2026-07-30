# Setup — custom GitHub profile dashboard

## 1. Create the special profile repository

Create a **public** GitHub repository whose name is exactly your GitHub username. For example, username `octocat` requires a repository named `octocat`.

Upload everything in this ZIP to the repository root.

## 2. Personalize the text

Edit `config.json`:

- `display_name`: your public name
- `github_username`: leave as `AUTO` to use the repository owner automatically
- `handle`: terminal-style label, for example `van@github`
- `headline`, `location`, and `status`: your own copy
- `website` and `email`: optional

## 3. Replace the portrait

`assets/portrait.txt` is the character portrait rendered on the left.

Replace it with ASCII or Unicode art. Keep it around 18–24 lines tall and avoid very wide lines. The renderer escapes unsafe characters automatically.

## 4. Generate once manually

Open **Actions → Update profile dashboard → Run workflow**.

The workflow queries GitHub, regenerates both SVG themes, and commits them into `generated/`.

The repository workflow explicitly requests `contents: write`. If the commit step is denied, open:

**Repository Settings → Actions → General → Workflow permissions → Read and write permissions**

Then run it again.

## 5. Automatic updates

The included workflow runs twice per day and can also be run manually. Change the cron expression in `.github/workflows/update-profile.yml` as needed.

## What updates automatically

- Contributions during the trailing 365 days
- Public repositories
- Stars earned by repositories you own
- Pull requests during the trailing 365 days
- Followers
- Current contribution streak
- Monthly contribution line plot
- Top repositories by stars

## Important metric limitations

The default `GITHUB_TOKEN` reliably exposes public GitHub activity. It should not be treated as a complete measure of private company work or activity on another GitHub Enterprise/GitLab instance.

## Local preview

Python 3.11+ is enough; there are no third-party packages.

```bash
python3 scripts/update_profile.py --mock
```

This writes:

- `generated/profile-dark.svg`
- `generated/profile-light.svg`

Open either file in a browser.

To fetch live public data locally:

```bash
export GITHUB_TOKEN='your_fine_grained_token'
export GITHUB_REPOSITORY_OWNER='your_username'
python3 scripts/update_profile.py
```

Do not commit personal access tokens.
