from pydantic import BaseModel


class CreateBatchRequest(BaseModel):
    mode: str  # "archive" | "folder"
    display_name: str | None = None


class CreateBatchResponse(BaseModel):
    batch_id: str
    chunk_size: int


class RegisterItemRequest(BaseModel):
    relative_path: str
    size: int


class RegisterItemResponse(BaseModel):
    item_id: str
    total_chunks: int
    chunk_size: int
    received_chunks: list[int]


class ItemStatusResponse(BaseModel):
    item_id: str
    status: str
    total_chunks: int
    received_chunks: list[int]


class CompleteItemResponse(BaseModel):
    item_id: str
    status: str


class CompleteBatchResponse(BaseModel):
    batch_id: str
    case_id: str
    job_id: str


class JobStepOut(BaseModel):
    kind: str
    name: str
    status: str
    num_events: int
    num_errors: int
    num_warnings: int
    duration: float | None

    class Config:
        from_attributes = True


class JobStatusResponse(BaseModel):
    job_id: str
    case_id: str
    status: str
    total_steps: int
    completed_steps: int
    error_message: str | None
    steps: list[JobStepOut]

    class Config:
        from_attributes = True


class CaseOut(BaseModel):
    id: str
    display_name: str
    status: str
    ios_version: str | None
    model: str | None
    serial_number: str | None
    created_at: str

    class Config:
        from_attributes = True
