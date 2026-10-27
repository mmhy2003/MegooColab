from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.audit import service as audit
from app.auth.deps import AdminUser, AuthedUser
from app.core.crypto import encrypt
from app.core.db import DbSession
from app.core.email import SmtpMailer
from app.org.models import ORG_SETTINGS_ID, OrgSettings
from app.workflow.models import FinishingOption

router = APIRouter(tags=["org"])


class OrgOut(BaseModel):
    name: str


class SmtpOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    host: str | None = None
    port: int | None = None
    user: str | None = None
    from_: str | None = Field(default=None, alias="from")
    tls: bool = True
    password_set: bool = False


class SmtpIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    user: str | None = None
    from_: str | None = Field(default=None, alias="from")
    tls: bool = True
    password: str | None = None


class Dreaming(BaseModel):
    enabled: bool = True
    hour_utc: int | None = Field(default=None, ge=0, le=23)  # null: the server's MEMORY_DREAM_HOUR_UTC


class ProjectDefaults(BaseModel):
    finishing_option: FinishingOption = FinishingOption.pull_request
    require_human_code_review: bool = False
    sprints_enabled: bool = True
    commit_docs_to_repo: bool = False


class AdminSettingsOut(BaseModel):
    name: str
    smtp: SmtpOut
    dreaming: Dreaming
    project_defaults: ProjectDefaults


class AdminSettingsIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    smtp: SmtpIn
    # absent: keep what is stored
    dreaming: Dreaming | None = None
    project_defaults: ProjectDefaults | None = None


class TestEmailIn(BaseModel):
    to: EmailStr


async def _org(db) -> OrgSettings:
    org = await db.get(OrgSettings, ORG_SETTINGS_ID)
    if org is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "setup_required")
    return org


def _settings_out(org: OrgSettings) -> AdminSettingsOut:
    return AdminSettingsOut(
        name=org.name,
        smtp=SmtpOut(
            host=org.smtp_host,
            port=org.smtp_port,
            user=org.smtp_user,
            from_=org.smtp_from,
            tls=org.smtp_tls,
            password_set=bool(org.smtp_password_enc),
        ),
        dreaming=Dreaming(enabled=org.dream_enabled, hour_utc=org.dream_hour_utc),
        project_defaults=ProjectDefaults(
            finishing_option=org.default_finishing_option,
            require_human_code_review=org.default_require_human_code_review,
            sprints_enabled=org.default_sprints_enabled,
            commit_docs_to_repo=org.default_commit_docs_to_repo,
        ),
    )


@router.get("/api/org")
async def get_org(user: AuthedUser, db: DbSession) -> OrgOut:
    return OrgOut(name=(await _org(db)).name)


@router.get("/api/admin/settings", response_model_by_alias=True)
async def get_settings(admin: AdminUser, db: DbSession) -> AdminSettingsOut:
    return _settings_out(await _org(db))


@router.put("/api/admin/settings", response_model_by_alias=True)
async def put_settings(body: AdminSettingsIn, admin: AdminUser, db: DbSession) -> AdminSettingsOut:
    org = await _org(db)
    org.name = body.name
    org.smtp_host = body.smtp.host or None
    org.smtp_port = body.smtp.port
    org.smtp_user = body.smtp.user or None
    org.smtp_from = body.smtp.from_ or None
    org.smtp_tls = body.smtp.tls
    if body.smtp.password:
        org.smtp_password_enc = encrypt(body.smtp.password)
    if body.dreaming is not None:
        org.dream_enabled, org.dream_hour_utc = body.dreaming.enabled, body.dreaming.hour_utc
    if body.project_defaults is not None:
        d = body.project_defaults
        org.default_finishing_option = d.finishing_option.value
        org.default_require_human_code_review = d.require_human_code_review
        org.default_sprints_enabled = d.sprints_enabled
        org.default_commit_docs_to_repo = d.commit_docs_to_repo
    await audit.record(db, "org.settings_changed", actor_id=admin.id)
    return _settings_out(org)


@router.post("/api/admin/settings/test-email", status_code=status.HTTP_204_NO_CONTENT)
async def test_email(body: TestEmailIn, admin: AdminUser, db: DbSession) -> None:
    org = await _org(db)
    if not org.smtp_host:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "smtp_not_configured")
    try:
        await SmtpMailer(org).send(
            body.to, "MegooColab test email", "If you can read this, MegooColab email works."
        )
    except Exception as exc:  # report any SMTP/network failure to the admin
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc) or exc.__class__.__name__)
