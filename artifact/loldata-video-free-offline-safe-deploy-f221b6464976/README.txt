LOLDataSystem video-free offline safe deployment

Target commit: f221b64649763eb8d325d87348fd2f42f48a6485

Usage:
1. Extract this ZIP completely.
2. Double-click run-deploy.cmd.
3. Approve the Administrator prompt.
4. Keep the final console output for acceptance.

Safety:
- Imports only the fixed Git bundle in this package.
- Runs full candidate tests before stopping production.
- Backs up code-adjacent runtime state and ACL-protects the backup.
- Removes only QUERY_VIDEO_PROVIDERS_JSON after deployment.
- Preserves risk Provider and custom dynamic Provider settings.
- Validates that video is rejected after deployment.
- Rolls back the full deployment if post-deployment retirement validation fails.

Never deploy the revoked GroupGuard dist commit 029118346adaa9232aeceeb283f5d243a407dc95.
