def generate_requirements_txt(
    input_toml_path="pyproject.toml",
    output_txt_path="qgis_plugin_landlensdb/requirements.txt",
):
    with open(input_toml_path, "r") as f:
        lines = f.readlines()

    in_project_section = False
    in_dependencies_list = False
    deps = []

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("[project]"):
            in_project_section = True
            continue
        elif stripped.startswith("[") and not stripped.startswith("[project."):
            in_project_section = False
            in_dependencies_list = False
            continue

        if in_project_section and stripped.startswith("dependencies"):
            in_dependencies_list = True
            continue

        if in_dependencies_list:
            if stripped.startswith("]") or stripped.startswith("["):
                break
            if stripped:
                dep = stripped.strip().rstrip(",").strip('"').strip("'")
                deps.append(dep)

    with open(output_txt_path, "w") as f:
        for dep in deps:
            f.write(dep + "\n")


if __name__ == "__main__":
    generate_requirements_txt()
