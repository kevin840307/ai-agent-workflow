from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from fastapi import APIRouter

from app.services.validation_script_service import generate_validation_script, write_validation_script

router = APIRouter()


class GenerateValidationScriptRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    requirement: str
    expected_result: str | None = Field(default=None, alias="expectedResult")
    project_type: str | None = Field(default="python", alias="projectType")
    project_path: str | None = Field(default=None, alias="projectPath")
    filename: str = "validation.py"
    write: bool = False


@router.post("/api/validation-scripts/generate")
async def generate_validation_script_endpoint(body: GenerateValidationScriptRequest):
    script = generate_validation_script(body.requirement, body.expected_result, project_type=body.project_type or "python")
    result = {"script": script, "filename": body.filename, "project_type": body.project_type or "python"}
    if body.write:
        if not body.project_path:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="projectPath is required when write=true")
        result["written"] = write_validation_script(body.project_path, script, body.filename)
    return result
