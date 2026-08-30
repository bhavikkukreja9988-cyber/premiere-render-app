# Upload this V2 package to GitHub

Target repository: bhavikkukreja9988-cyber/premiere-render-app
Target branch: feature/v2-transfer-render-return

These files are the complete V2 handoff source package. Upload the files at the repository root, preserving the exact folder structure. Do not put them inside another nested V2 folder.

## Recommended method
1. Download and unzip the package.
2. Open GitHub and open the repository.
3. Switch the branch to `feature/v2-transfer-render-return`.
4. Use **Add file -> Upload files**.
5. Upload the contents of this unzipped folder, preserving paths.
6. Commit to the existing V2 branch.
7. Run `python -m unittest discover -s tests -t .` from the repository root on Windows.

## GitHub Desktop method (recommended for 46 files)
1. Clone the repository with GitHub Desktop.
2. Checkout `feature/v2-transfer-render-return`.
3. Copy the contents of this package over the local repository, replacing matching V2 files when prompted.
4. Review the changed files in GitHub Desktop.
5. Commit with: `feat: working transfer, background render and MP4 return`
6. Push the branch.

Do not upload `.venv`, `build`, `dist`, or `__pycache__`.
