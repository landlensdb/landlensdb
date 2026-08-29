# Contributing to landlensdb

Thank you for contributing to landlensdb! Your involvement helps make this project a great tool for point cloud data processing and visualization of forest structure.

## Code of Conduct

By participating in this project, please follow our [Code of Conduct](code_of_conduct.md).

## How Can I Contribute?

### Reporting Bugs

- **Check Existing Issues** — Before opening a new bug report, see if the issue has already been reported. If it has, add any additional details in a comment.
  
- **Submit a Report** — If the issue hasn't been reported, open a new issue and fill out the provided template.

### Suggesting Enhancements

Have an idea to improve landlensdb? Please open an issue to discuss your suggestion.

### Pull Requests

To contribute via pull requests:

1. **Fork the Repository** — Fork the landlensdb repository and clone it locally.
2. **Create a Branch** — Make changes in a new branch. Use descriptive names like `feat/`, `fix/`, or `docs/` followed by the feature or fix name.
3. **Commit Your Changes** — Write a clear commit message describing your changes.
4. **Push to Your Fork** — Push the branch to your fork on GitHub.
5. **Create a Pull Request** — Open a pull request (PR) in the landlensdb repository. Link any relevant issues.
6. **Code Review** — A maintainer will review your changes. You may need to make updates based on feedback.
7. **Merge** — Once approved, your PR will be merged into the main codebase.

## Style Guidelines

### Python

- Follow the [PEP 8](https://pep8.org/) style guide.
- Use type hints in functions.
- Add documentation to public APIs.

### Git Commit Messages

- Use present tense ("Add feature" not "Added feature").
- Limit the first line to 72 characters or fewer.
- Reference related issues and PRs when relevant.

## Releasing a New Version

### Steps for Creating a New Release

1. **Prepare and verify the release**:
   Confirm all intended changes are merged into `main`, the test workflow is green,
   and the working tree is clean.

2. **Update the release metadata**:
   Set the version in `pyproject.toml`, update `CITATION.cff`, and prepare the
   GitHub Release notes. Version numbers follow
   [semantic versioning](https://semver.org/).

3. **Run the release checks**:

   ```bash
   pytest
   python -m build
   twine check dist/*
   ```

4. **Create and push an annotated tag**:
   After reviewing the exact commit to release, tag it using the format `vX.Y.Z`.
   Pushing this tag starts the publishing workflow, so do not push it until the
   release is approved.

   ```bash
   git tag -a v0.2.0 -m "Release v0.2.0"
   git push origin v0.2.0
   ```

5. **Monitor automated publishing**:
   `.github/workflows/publish.yml` builds and validates the Python distributions,
   uploads them to PyPI, and then publishes Docker images tagged with both the
   release tag and `latest`.

6. **Create the GitHub Release**:
   The publishing workflow does not create a GitHub Release. Create it manually
   from the pushed tag, add the prepared release notes, and confirm any connected
   archival service (such as Zenodo) completed successfully.

### Semantic Versioning Guidelines
- **Major version**: For incompatible API changes.
- **Minor version**: For backward-compatible features.
- **Patch version**: For backward-compatible bug fixes.

## Contributing to Documentation

Documentation uses `mkdocs`. Install dependencies using:

```bash
pip install -e ."[docs]"
```

Commit changes and deploy using:

```bash
mkdocs gh-deploy
```

## Additional Notes

- Ensure compatibility with the latest dependencies.
- Update documentation when adding or changing features.
