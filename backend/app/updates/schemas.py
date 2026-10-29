from pydantic import BaseModel


class AppUpdate(BaseModel):
    current: str
    latest: str
    url: str  # the release page


class RunnerRelease(BaseModel):
    latest: str
    url: str


class UpdatesOut(BaseModel):
    app: AppUpdate | None = None  # admins only, and only when the server is older than the latest release
    runner: RunnerRelease | None = None  # each agent's runner version is compared with it by the frontend
