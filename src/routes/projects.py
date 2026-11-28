
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from models.ProjectModel import ProjectModel
from models.db_schemes import Project
from utils.auth import get_current_user

projects_router = APIRouter(
    prefix="/api/v1/projects",
    tags=["Projects"],
)


@projects_router.post("", status_code=status.HTTP_201_CREATED)
async def create_project(request: Request, user=Depends(get_current_user)):
    project_model = await ProjectModel.create_instance(
        db_client=request.app.db_client
    )

    project = await project_model.create_project(Project(owner_id=user.user_id))

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={
            "project_id": project.project_id,
            "project_uuid": str(project.project_uuid),
        },
    )
