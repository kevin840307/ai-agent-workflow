from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .base import ValidatorPlan


class MarkerValidator:
    def __init__(self, *, id: str, title: str, markers: tuple[str, ...], command: list[str], category: str = "test", required: bool = True) -> None:
        self.id = id
        self.title = title
        self.markers = markers
        self.command = command
        self.category = category
        self.required = required

    def detect(self, project: Path) -> bool:
        return any((project / marker).exists() for marker in self.markers)

    def plan(self, project: Path) -> ValidatorPlan:
        found = [marker for marker in self.markers if (project / marker).exists()]
        return ValidatorPlan(self.id, self.title, list(self.command), found, self.required, self.category)


class PythonValidator(MarkerValidator):
    def __init__(self) -> None:
        super().__init__(id="python", title="Python tests", markers=("pytest.ini", "pyproject.toml", "requirements.txt", "setup.py", "tests"), command=[os.environ.get("PYTHON", "python"), "-m", "pytest", "-q"])

    def detect(self, project: Path) -> bool:
        return super().detect(project) or any(project.glob("*.py"))


class DotNetValidator(MarkerValidator):
    def __init__(self) -> None:
        super().__init__(id="dotnet", title=".NET tests", markers=("*.sln", "*.csproj"), command=["dotnet", "test", "--nologo"])

    def detect(self, project: Path) -> bool:
        return any(project.glob("*.sln")) or any(project.rglob("*.csproj"))

    def plan(self, project: Path) -> ValidatorPlan:
        marker = next(iter(project.glob("*.sln")), None)
        cmd = ["dotnet", "test", str(marker.name), "--nologo"] if marker else ["dotnet", "test", "--nologo"]
        return ValidatorPlan(self.id, self.title, cmd, [str(marker.name)] if marker else ["*.csproj"], self.required, self.category)


class MavenValidator(MarkerValidator):
    def __init__(self) -> None:
        super().__init__(id="maven", title="Maven tests", markers=("pom.xml",), command=["mvn", "-q", "test"])


class GradleValidator(MarkerValidator):
    def __init__(self) -> None:
        super().__init__(id="gradle", title="Gradle tests", markers=("build.gradle", "build.gradle.kts", "gradlew", "gradlew.bat"), command=["gradle", "test"])

    def plan(self, project: Path) -> ValidatorPlan:
        if (project / "gradlew.bat").exists():
            cmd = ["gradlew.bat", "test"]
        elif (project / "gradlew").exists():
            cmd = ["./gradlew", "test"]
        else:
            cmd = ["gradle", "test"]
        return ValidatorPlan(self.id, self.title, cmd, [marker for marker in self.markers if (project / marker).exists()], self.required, self.category)


class NodeValidator(MarkerValidator):
    def __init__(self) -> None:
        super().__init__(id="node", title="Node tests", markers=("package.json",), command=["npm", "test", "--", "--runInBand"])


class YamlValidator(MarkerValidator):
    def __init__(self) -> None:
        super().__init__(id="yaml", title="YAML syntax", markers=(".yamllint", ".yamllint.yml"), command=["yamllint", "."], category="syntax", required=False)

    def detect(self, project: Path) -> bool:
        return super().detect(project) or any(project.rglob("*.yaml")) or any(project.rglob("*.yml"))


class DockerValidator(MarkerValidator):
    def __init__(self) -> None:
        super().__init__(id="docker", title="Docker compose validation", markers=("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"), command=["docker", "compose", "config", "--quiet"], category="configuration", required=False)


class KubernetesValidator(MarkerValidator):
    def __init__(self) -> None:
        super().__init__(id="kubernetes", title="Kubernetes manifest validation", markers=("Chart.yaml", "kustomization.yaml", "kustomization.yml"), command=["kubectl", "apply", "--dry-run=client", "-f", "."], category="configuration", required=False)


class XmlValidator(MarkerValidator):
    def __init__(self) -> None:
        script = (
            "import pathlib,xml.etree.ElementTree as E,sys; "
            "files=list(pathlib.Path('.').rglob('*.xml')); "
            "[(E.parse(str(p))) for p in files]; print(f'validated {len(files)} XML files')"
        )
        super().__init__(id="xml", title="XML syntax", markers=("pom.xml",), command=[sys.executable, "-c", script], category="syntax", required=False)

    def detect(self, project: Path) -> bool:
        return any(project.rglob("*.xml"))


class SqlValidator(MarkerValidator):
    def __init__(self) -> None:
        super().__init__(id="sql", title="SQL lint", markers=(".sqlfluff", "pyproject.toml"), command=["sqlfluff", "lint", "."], category="syntax", required=False)

    def detect(self, project: Path) -> bool:
        return any(project.rglob("*.sql"))


class CustomCommandValidator:
    id = "custom"
    title = "Project validation command"

    def _config(self, project: Path) -> dict:
        candidates = [project / ".ai-workflow-validator.json", project / ".ai-workflow" / "validators.json"]
        for path in candidates:
            if not path.is_file():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and isinstance(data.get("command"), list):
                return {**data, "_path": path.relative_to(project).as_posix()}
        return {}

    def detect(self, project: Path) -> bool:
        return bool(self._config(project))

    def plan(self, project: Path) -> ValidatorPlan:
        data = self._config(project)
        return ValidatorPlan(
            str(data.get("id") or self.id),
            str(data.get("title") or self.title),
            [str(item) for item in data.get("command") or []],
            [str(data.get("_path") or ".ai-workflow-validator.json")],
            bool(data.get("required", True)),
            str(data.get("category") or "custom"),
        )


PLUGINS = [CustomCommandValidator(), PythonValidator(), MavenValidator(), GradleValidator(), DotNetValidator(), NodeValidator(), YamlValidator(), XmlValidator(), SqlValidator(), DockerValidator(), KubernetesValidator()]


__all__ = ["PLUGINS", "DockerValidator", "DotNetValidator", "GradleValidator", "KubernetesValidator", "MavenValidator", "NodeValidator", "PythonValidator", "YamlValidator"]
