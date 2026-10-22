async def test_mutation_without_client_header_is_forbidden(client):
    r = await client.post("/api/setup", json={}, headers={"X-Megoo-Client": ""})
    assert r.status_code == 403


async def test_mutation_with_bearer_header_passes_csrf_guard(client):
    r = await client.post("/api/setup", json={}, headers={"X-Megoo-Client": "", "Authorization": "Bearer x"})
    assert r.status_code == 422  # reached validation, not blocked


async def test_get_without_client_header_is_allowed(client):
    r = await client.get("/api/health", headers={"X-Megoo-Client": ""})
    assert r.status_code == 200
