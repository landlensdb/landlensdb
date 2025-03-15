# Contributing to landlensdb

First off, thank you for considering contributing to `landlensdb`. It's people like you that make this
project a great tool.

## Code of Conduct

By participating, you are expected to uphold our code of conduct. Please report unacceptable
behavior to [ipercival@gmail.com](ipercival@gmail.com).

## How to Contribute

### Reporting Bugs

- **Ensure the bug was not already reported** by searching on GitHub under [Issues](https://github.com/landlensdb/landlensdb/issues).
- If you're unable to find an open issue addressing the problem, [open a new one](https://github.com/landlensdb/landlensdb/issues/new).

### Suggesting Enhancements

- Open a new issue detailing your suggestion. Include a clear title and description, as much relevant information as possible, and any examples that help to explain the enhancement.

### Code Contributions

#### Setup Development Environment

1. Fork the repository on GitHub.
2. Clone the forked repository to your machine.
3. Install the project in editable mode with development dependencies:

```bash
pip install -e .[dev]
```

#### Code Formatting

We use Black with Python 3.9. Make sure your code is formatted accordingly before submitting a pull request:

```bash
pre-commit run --all-files
```

### Branching and Versioning Strategy

#### Branching Strategy

This project follows the GitHub Flow branching strategy:

- **main branch**:
  - Always contains stable, production-ready code.
  - Releases are tagged on this branch.

- **Feature branches**:
  - Create from `main`:
  
```bash
git checkout -b feature/my-feature-name
```

  - Push your changes:
  
```bash
git push origin feature/my-feature-name
```

- **Bugfix branches**:
  - Create from `main` and reference issue numbers clearly:
  
```bash
git checkout -b bugfix/issue-123-description
```

  - Push fixes:
  
```bash
git push origin bugfix/issue-123-description
```

- **Submitting Pull Requests**:
  - Always submit your feature or bugfix branches via pull requests (PRs) against the `main` branch.
  - PRs must pass all automated tests and CI checks before merging.
  - Code review and approval are required for merging.

#### Versioning Strategy

`landlensdb` uses Semantic Versioning (https://semver.org) to clearly communicate the nature of releases.

- **Patch**: Increment (e.g., `1.0.x`) for bug fixes and minor changes not affecting API.
- **Minor**: Increment (e.g., `1.x.0`) for new backward-compatible features and improvements.
- **Major**: Increment (e.g., `x.0.0`) for breaking changes or significant architectural shifts.

Version tags will always be created in the `main` branch after merging PRs, for example:

```bash
git tag -a v1.2.0 -m "Release version 1.2.0 - Added Mapillary pagination"
git push origin --tags
```

## Testing

Before submitting your changes, please make sure to run the full test suite. Instructions on how to run the tests
are found in the project's README.

## Writing Documentation

Documentation is a vital part of `landlensdb`, helping users and developers understand the functionality
and usage of the library. We use [MkDocs](https://www.mkdocs.org/) to generate the documentation.

### Guidelines

- Follow the Google style for docstrings.
- Include examples where appropriate.
- Keep the documentation clear, concise, and consistent with existing pages.

### Building Documentation Locally

1. Ensure you have installed the required dependencies for docs:
   
```bash
pip install -e .[docs]
```

2. From the project’s root directory (where `mkdocs.yml` is located), build or serve the docs:

```bash
mkdocs serve
```

This will start a local server. Follow the terminal output to view the documentation in your browser.

If you're contributing new code, please make sure to include well-written docstrings following our
guidelines. Review the existing documentation to understand the style and content that we expect.

### Adding to the Official Documentation

When your changes are merged, the official documentation will be automatically updated. Ensure that
your documentation is clear, concise, and follows the established conventions.

## License

By contributing, you agree that your contributions will be licensed under the project's MIT License.

## Acknowledgments

Your contributions to `landlensdb` are much appreciated. Thank you for your support!