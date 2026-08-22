from pydantic import BaseModel, ConfigDict


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class MessageResponse(APIModel):
    message: str


class StatusResponse(APIModel):
    status: str


class HealthResponse(APIModel):
    status: str
    environment: str
    version: str
