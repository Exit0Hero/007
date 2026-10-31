# GitHub Push Instructions

The repository is fully prepared and committed locally on branch `main`.

To push to GitHub:

1. Add the SSH key to your GitHub account:
   ```bash
   cat ~/.ssh/github_key.pub
   ```
   Add this key at https://github.com/settings/keys

2. Push the repository:
   ```bash
   cd /home/akkushon-kamen/Desktop/007/atlas_opencode_starter_kit/atlas_opencode_starter
   git push -u origin main
   ```

Or use HTTPS with a personal access token:
```bash
git remote set-url origin https://github.com/Exit0Hero/007.git
git push -u origin main
```

Repository is ready at: https://github.com/Exit0Hero/007
