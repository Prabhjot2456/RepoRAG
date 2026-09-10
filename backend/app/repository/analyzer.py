"""
Technology detector.

Detects frameworks/databases/tools from repository files without executing code.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from app.repository.metadata import TechInfo
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ── Detection rules ─────────────────────────────────────────────────────────────
# Each entry: tech_name → list of (file_pattern, content_pattern) evidence checks
# file_pattern: substring in file path (case-insensitive)
# content_pattern: substring in file content (case-insensitive, can be None)

TECH_RULES: Dict[str, List[tuple]] = {
    # Languages (detected via file extensions in file tree)
    "Python": [("requirements.txt", None), ("pyproject.toml", None), (".py", None)],
    "JavaScript": [("package.json", None), (".js", None), (".jsx", None)],
    "TypeScript": [("tsconfig.json", None), (".ts", None), (".tsx", None)],
    "Java": [("pom.xml", None), ("build.gradle", None), (".java", None)],
    "Go": [("go.mod", None), (".go", None)],
    "Rust": [("cargo.toml", None), (".rs", None)],
    "Ruby": [("Gemfile", None), (".rb", None)],
    "PHP": [("composer.json", None), (".php", None)],
    "C++": [(".cpp", None), (".cc", None), ("CMakeLists.txt", None)],
    "C": [(".c", None), (".h", None)],
    "C#": [(".cs", None), (".csproj", None)],
    "Swift": [(".swift", None)],
    "Kotlin": [(".kt", None)],
    "Scala": [(".scala", None)],
    "Dart": [(".dart", None), ("pubspec.yaml", None)],

    # Frameworks & Libraries
    "FastAPI": [("requirements.txt", "fastapi"), ("pyproject.toml", "fastapi")],
    "Django": [("requirements.txt", "django"), ("manage.py", None)],
    "Flask": [("requirements.txt", "flask")],
    "Spring Boot": [("pom.xml", "spring-boot"), ("build.gradle", "spring-boot")],
    "Express": [("package.json", "express")],
    "React": [("package.json", "react"), (".jsx", None), (".tsx", None)],
    "Next.js": [("package.json", "next"), ("next.config", None)],
    "Vue": [("package.json", "vue"), (".vue", None)],
    "Angular": [("package.json", "@angular"), ("angular.json", None)],
    "Svelte": [("package.json", "svelte"), (".svelte", None)],
    "NestJS": [("package.json", "@nestjs")],
    "LangChain": [("requirements.txt", "langchain"), ("package.json", "langchain")],
    "Ollama": [("requirements.txt", "ollama"), (".py", "ollama"), (".env", "OLLAMA")],
    "Hugging Face": [("requirements.txt", "transformers"), ("requirements.txt", "sentence-transformers")],

    # Databases
    "PostgreSQL": [("requirements.txt", "psycopg"), ("requirements.txt", "asyncpg"), ("requirements.txt", "postgresql"), (".py", "postgresql"), (".env", "postgres")],
    "MySQL": [("requirements.txt", "mysqlclient"), ("requirements.txt", "pymysql"), (".env", "mysql")],
    "MongoDB": [("requirements.txt", "pymongo"), ("requirements.txt", "motor"), (".env", "mongodb")],
    "Redis": [("requirements.txt", "redis"), ("requirements.txt", "aioredis")],
    "SQLite": [("requirements.txt", "sqlite"), (".py", "sqlite3")],
    "ChromaDB": [("requirements.txt", "chromadb")],
    "Elasticsearch": [("requirements.txt", "elasticsearch"), ("docker-compose", "elasticsearch")],

    # Infrastructure / DevOps
    "Docker": [("Dockerfile", None), ("docker-compose", None)],
    "Kubernetes": [(".yaml", "apiVersion"), ("kubernetes", None), ("helm", None)],
    "Terraform": [(".tf", None), ("terraform", None)],
    "GitHub Actions": [(".github/workflows", None)],
    "AWS": [("requirements.txt", "boto"), (".py", "boto3"), (".env", "AWS_")],
    "GCP": [("requirements.txt", "google-cloud"), (".py", "google.cloud")],
    "Azure": [("requirements.txt", "azure"), (".py", "azure")],

    # Testing
    "Pytest": [("requirements.txt", "pytest"), ("pyproject.toml", "pytest")],
    "Jest": [("package.json", "jest")],

    # Build tools
    "Webpack": [("package.json", "webpack"), ("webpack.config", None)],
    "Vite": [("package.json", "vite"), ("vite.config", None)],
}


def detect_technologies(
    file_paths: List[str],
    file_contents: Dict[str, str],
) -> List[TechInfo]:
    """
    Detect technologies from repository file paths and their contents.

    Args:
        file_paths: List of relative file paths.
        file_contents: Dict of relative_path → file content (sample).
    """
    detected: Dict[str, TechInfo] = {}

    for tech_name, rules in TECH_RULES.items():
        evidence: List[str] = []

        for file_pattern, content_pattern in rules:
            # Check file path match
            matching_files = [
                fp for fp in file_paths
                if file_pattern.lower() in fp.lower()
            ]

            for mf in matching_files[:3]:  # Limit evidence
                if content_pattern is None:
                    evidence.append(mf)
                else:
                    content = file_contents.get(mf, "")
                    if content_pattern.lower() in content.lower():
                        evidence.append(f"{mf} (contains '{content_pattern}')")

        if evidence:
            detected[tech_name] = TechInfo(
                name=tech_name,
                confidence="detected",
                evidence=evidence[:3],
            )

    return list(detected.values())
