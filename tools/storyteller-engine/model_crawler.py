"""
model_crawler.py
~~~~~~~~~~~~~~~~
Sub-Agent 2: Crawls database models, schemas, and table relationships:
  - Prisma (schema.prisma: model User { ... })
  - SQLAlchemy / Python ORMs (class User(Base): __tablename__ = 'users')
  - Django ORM (class User(models.Model): ...)
  - TypeORM / Mongoose (class UserEntity, new Schema({ ... }))
  - Go GORM (type User struct { ... gorm:"..." })
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, List, Optional

from scan_filter import blank_comments, collect_files


@dataclass
class FieldSpec:
    name: str
    field_type: str
    is_primary_key: bool = False
    is_foreign_key: bool = False
    references: Optional[str] = None


@dataclass
class DBModel:
    name: str
    table_name: str
    file_path: str
    line_start: int
    line_end: int
    orm_type: str
    fields: List[FieldSpec] = field(default_factory=list)
    relationships: List[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "table_name": self.table_name,
            "file_path": self.file_path,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "orm_type": self.orm_type,
            "fields": [asdict(f) for f in self.fields],
            "relationships": self.relationships,
        }


class ModelCrawler:
    """Sub-agent responsible for discovering database models, columns, and relations."""

    EXTENSIONS = (".py", ".ts", ".js", ".go", ".prisma")

    def __init__(self, root_dir: str):
        self.root_dir = Path(root_dir).resolve()

    def crawl(self, target_files: Optional[List[str]] = None) -> List[DBModel]:
        models: List[DBModel] = []
        files = target_files or collect_files(self.root_dir, self.EXTENSIONS)

        for fpath in files:
            path_obj = Path(fpath)
            if not path_obj.is_file():
                continue
            ext = path_obj.suffix.lower()
            fname = path_obj.name.lower()
            try:
                content = path_obj.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            # Documentation examples are not schema definitions.
            content = blank_comments(content, ext)
            rel_path = str(path_obj.relative_to(self.root_dir)).replace("\\", "/")

            if fname.endswith(".prisma"):
                models.extend(self._crawl_prisma(content, rel_path))
            elif ext == ".py":
                models.extend(self._crawl_python_models(content, rel_path))
            elif ext in (".ts", ".js"):
                models.extend(self._crawl_ts_models(content, rel_path))
            elif ext == ".go":
                models.extend(self._crawl_go_models(content, rel_path))

        return models

    def _crawl_prisma(self, content: str, file_path: str) -> List[DBModel]:
        models = []
        # model User { id Int @id ... }
        model_blocks = re.finditer(r'model\s+([A-Za-z0-9_]+)\s*\{([^}]+)\}', content, re.MULTILINE)
        lines = content.splitlines()

        for match in model_blocks:
            name = match.group(1)
            body = match.group(2)
            start_pos = match.start()
            line_start = content.count("\n", 0, start_pos) + 1
            line_end = line_start + body.count("\n")

            fields: List[FieldSpec] = []
            relationships = []

            for field_line in body.splitlines():
                field_line = field_line.strip()
                if not field_line or field_line.startswith("//") or field_line.startswith("@@"):
                    continue
                parts = field_line.split()
                if len(parts) >= 2:
                    f_name, f_type = parts[0], parts[1]
                    is_pk = "@id" in field_line
                    is_fk = "@relation" in field_line
                    ref = None
                    if is_fk:
                        rel_match = re.search(r'references:\s*\[([^\]]+)\]', field_line)
                        if rel_match:
                            ref = rel_match.group(1).strip()
                            relationships.append(f"{name} -> {f_type}({ref})")
                    fields.append(FieldSpec(
                        name=f_name,
                        field_type=f_type,
                        is_primary_key=is_pk,
                        is_foreign_key=is_fk,
                        references=ref,
                    ))

            models.append(DBModel(
                name=name,
                table_name=name.lower() + "s",
                file_path=file_path,
                line_start=line_start,
                line_end=line_end,
                orm_type="Prisma",
                fields=fields,
                relationships=relationships,
            ))

        return models

    def _crawl_python_models(self, content: str, file_path: str) -> List[DBModel]:
        models = []
        lines = content.splitlines()

        # SQLAlchemy or Django: class User(Base): or class User(models.Model):
        class_pattern = re.compile(
            r'class\s+([A-Za-z0-9_]+)\s*\(\s*(?:Base|db\.Model|models\.Model|declarative_base\(\))\s*\):'
        )

        for i, line in enumerate(lines):
            match = class_pattern.search(line)
            if match:
                name = match.group(1)
                table_name = name.lower() + "s"
                fields: List[FieldSpec] = []
                relationships = []

                # Scan class body
                j = i + 1
                while j < len(lines) and (lines[j].startswith("    ") or lines[j].startswith("\t") or not lines[j].strip()):
                    cline = lines[j].strip()
                    if cline.startswith("__tablename__"):
                        t_match = re.search(r'__tablename__\s*=\s*["\']([^"\']+)["\']', cline)
                        if t_match:
                            table_name = t_match.group(1)
                    # Field definition: id = Column(Integer, primary_key=True)
                    field_match = re.match(r'([a-zA-Z_]\w*)\s*=\s*(?:Column|models\.\w+|db\.Column)\((.*)\)', cline)
                    if field_match:
                        fname = field_match.group(1)
                        fargs = field_match.group(2)
                        is_pk = "primary_key=True" in fargs
                        is_fk = "ForeignKey" in fargs
                        ftype = fargs.split(",")[0].strip() if fargs else "Unknown"
                        ref = None
                        if is_fk:
                            fk_match = re.search(r'ForeignKey\(["\']([^"\']+)["\']', fargs)
                            if fk_match:
                                ref = fk_match.group(1)
                                relationships.append(f"{name}.{fname} -> {ref}")
                        fields.append(FieldSpec(
                            name=fname,
                            field_type=ftype,
                            is_primary_key=is_pk,
                            is_foreign_key=is_fk,
                            references=ref,
                        ))
                    j += 1

                models.append(DBModel(
                    name=name,
                    table_name=table_name,
                    file_path=file_path,
                    line_start=i + 1,
                    line_end=j,
                    orm_type="SQLAlchemy/Django",
                    fields=fields,
                    relationships=relationships,
                ))

        return models

    def _crawl_ts_models(self, content: str, file_path: str) -> List[DBModel]:
        models = []
        lines = content.splitlines()

        # TypeORM @Entity() class User
        for i, line in enumerate(lines):
            if "@Entity" in line:
                for j in range(i + 1, min(i + 5, len(lines))):
                    c_match = re.search(r'class\s+([A-Za-z0-9_]+)', lines[j])
                    if c_match:
                        name = c_match.group(1)
                        models.append(DBModel(
                            name=name,
                            table_name=name.lower() + "s",
                            file_path=file_path,
                            line_start=i + 1,
                            line_end=j + 10,
                            orm_type="TypeORM",
                            fields=[],
                            relationships=[],
                        ))
                        break

        return models

    def _crawl_go_models(self, content: str, file_path: str) -> List[DBModel]:
        models = []
        # type User struct { gorm.Model ... }
        struct_pattern = re.finditer(r'type\s+([A-Za-z0-9_]+)\s+struct\s*\{([^}]+)\}', content, re.MULTILINE)
        for match in struct_pattern:
            name = match.group(1)
            body = match.group(2)
            if "gorm:" in body or "db:" in body or "sql:" in body:
                fields: List[FieldSpec] = []
                for fline in body.splitlines():
                    fline = fline.strip()
                    if not fline or fline.startswith("//"):
                        continue
                    parts = fline.split()
                    if len(parts) >= 2:
                        fname = parts[0]
                        ftype = parts[1]
                        is_pk = "primaryKey" in fline or fname == "ID"
                        fields.append(FieldSpec(
                            name=fname,
                            field_type=ftype,
                            is_primary_key=is_pk,
                        ))
                start_line = content.count("\n", 0, match.start()) + 1
                models.append(DBModel(
                    name=name,
                    table_name=name.lower() + "s",
                    file_path=file_path,
                    line_start=start_line,
                    line_end=start_line + body.count("\n"),
                    orm_type="GORM",
                    fields=fields,
                    relationships=[],
                ))

        return models
