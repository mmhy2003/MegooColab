from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(
        title="MegooColab",
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
    )

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
