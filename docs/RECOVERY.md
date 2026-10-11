# Recovery guide

## Backups
- Daily workflow `backup.yml` creates `nexus-<UTC>.bundle` (all branches and tags), verifies it, and uploads it as a 30‑day Actions artifact.
- **Independent copy:** set repository secrets `BACKUP_REPO_URL` (SSH URL of an empty private repo elsewhere) and `BACKUP_SSH_KEY` (a write-only deploy key for that repo). Pushes are non-force and never delete refs. Without these secrets there is no independent backup.
- Releases (`release.yml`) provide source archives and `SHA256SUMS` only, not history.

## Restore from a bundle
```bash
sha256sum -c SHA256SUMS
git bundle verify nexus-<stamp>.bundle
git clone --mirror nexus-<stamp>.bundle nexus-restored.git
git --git-dir=nexus-restored.git fsck
# working copy:
git clone nexus-restored.git nexus && cd nexus
# publish to a new, empty remote:
git --git-dir=../nexus-restored.git push --mirror <new-empty-remote-url>
```
`--mirror` is safe only on a new, empty remote.

## Restore from the independent backup
`git clone --mirror <BACKUP_REPO_URL> nexus-restored.git`, then proceed as above.

## Verify a bundle
`scripts/verify_bundle_restore.sh <bundle>` (run inside a clone) restores into a temp repo and compares all refs.

## Policy
Work happens on feature branches via pull requests; nothing merges to `main` automatically. Enable branch protection on `main` (require PR + `CI / test`).
