# Contributing to landlens_db

First off, thank you for considering contributing to `landlens_db`. It's people like you that make this project a great tool.

## Code of Conduct

By participating, you are expected to uphold our code of conduct. Please report unacceptable behavior to [ipercival@gmail.com](ipercival@gmail.com).

## How to Contribute

### Reporting Bugs

- **Ensure the bug was not already reported** by searching on GitHub under [Issues](https://github.com/username/landlens_db/issues).
- If you're unable to find an open issue addressing the problem, [open a new one](https://github.com/username/landlens_db/issues/new).

### Suggesting Enhancements

- Open a new issue detailing your suggestion. Include a clear title and description, as much relevant information as possible, and any examples that help to explain the enhancement.

### Code Contributions

#### Setup Development Environment

1. Fork the repository on GitHub.
2. Clone the forked repository to your machine.
3. Install the required development dependencies:

   ```bash
   pip install -r requirements-dev.txt
    ```

#### Code Formatting

We use Black with Python 3.9. Make sure your code is formatted accordingly before submitting a pull request:

    ```bash
    pre-commit run --all-files
    ```

#### Submitting a Pull Request

1. Create a new branch from `main` for your feature or bug fix.
2. Make your changes, following our coding style and guidelines.
3. Commit your changes and push to your fork.
4. Open a pull request with a clear title and description against the `main` branch.

## Testing

Before submitting your changes, please make sure to run the full test suite. Instructions on how to run the tests are found in the project's README.

## Writing Documentation

Documentation is a vital part of `landlens_db`, helping users and developers understand the functionality and usage of the library. We use Sphinx with the Read the Docs theme to generate the documentation.

### Guidelines

- Follow the Google style for docstrings.
- Include examples where appropriate.
- Ensure compatibility with Sphinx for autogenerating documentation using the "read the docs" theme.

### Building Documentation Locally

1. Ensure you have installed the required development dependencies, including Sphinx and the Read the Docs theme:

   ```bash
   pip install -r requirements-dev.txt
   ```

2. Navigate to the `docs` directory:

   ```bash
   cd docs
   ```

3. Build the HTML documentation:

   ```bash
   make html
   ```

4. Open the generated HTML files in your browser to preview the documentation.

If you're contributing new code, please make sure to include well-written docstrings following our guidelines. Review the existing documentation to understand the style and content that we expect.

### Adding to the Official Documentation

When your changes are merged, the official documentation will be automatically updated. Ensure that your documentation is clear, concise, and follows the established conventions.

## License

By contributing, you agree that your contributions will be licensed under the project's MIT License.

## Acknowledgments

Your contributions to `landlens_db` are much appreciated. Thank you for your support!
