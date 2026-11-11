"""rerank_config.api_key save-roundtrip verification (per-app rerank override).

Flow: create throwaway app with rerank api_key -> encrypted api_key_enc in DB,
masked (never plaintext) in API output; re-save without key keeps it;
clear_api_key=true removes it.
"""

import json
import subprocess
import uuid

import httpx

API = "http://127.0.0.1:8000"
FAKE_KEY = "sk-roundtrip-" + uuid.uuid4().hex[:16]
PSQL = ["docker", "compose", "exec", "-T", "postgres",
        "psql", "-U", "nexusrag", "-d", "nexusrag", "-At", "-c"]


CLIENT = httpx.Client(trust_env=False, timeout=30)  # 绕过系统代理直连本地


def api(method, path, token=None, **kw):
    headers = kw.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return CLIENT.request(method, API + path, headers=headers, **kw)


def db_scalar(sql):
    out = subprocess.run(PSQL + [sql], capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip())
    return out.stdout.strip()


def main():
    results = []

    def check(cid, name, ok, detail=""):
        results.append((cid, name, ok, detail))
        print(f"{'PASS' if ok else 'FAIL'} [{cid}] {name} :: {detail}")

    tok = api("POST", "/api/v1/auth/login",
              json={"email": "admin@nexusrag.local", "password": "admin123"}).json()["token"]

    rc = {
        "top_k": 5,
        "rerank_mode": "api",
        "rerank_config": {
            "api_base": "https://api.siliconflow.cn/v1",
            "model": "BAAI/bge-reranker-v2-m3",
            "api_key": FAKE_KEY,
        },
    }
    r = api("POST", "/api/v1/apps", tok, json={
        "name": "rerank-roundtrip-tmp", "kb_ids": [], "retrieval_config": rc})
    ok = r.status_code == 201
    check("R1", "create app with rerank api_key", ok, f"HTTP {r.status_code} {r.text[:120]}")
    app_id = r.json()["id"] if ok else None
    if not ok:
        return report(results)

    # R2 DB: ciphertext stored (AES-GCM base64, no plaintext)
    enc = db_scalar(
        f"SELECT retrieval_config->'rerank_config'->>'api_key_enc' FROM apps WHERE id='{app_id}'")
    check("R2", "DB stores api_key_enc ciphertext, plaintext absent",
          bool(enc) and len(enc) >= 40 and FAKE_KEY not in enc and enc != FAKE_KEY,
          f"enc_prefix={enc[:12]}... len={len(enc)}")

    # R3 API output: masked, no plaintext leak anywhere in payload
    r = api("GET", f"/api/v1/apps/{app_id}", tok)
    body = json.dumps(r.json(), ensure_ascii=False)
    rr = r.json().get("retrieval_config", {}).get("rerank_config", {})
    check("R3", "GET masks key (api_key_set + api_key_masked, no plaintext)",
          rr.get("api_key_set") is True and rr.get("api_key_masked", "").startswith("sk-****")
          and FAKE_KEY not in body and "api_key_enc" not in body,
          f"masked={rr.get('api_key_masked')}")

    # R4 merge-style re-save WITHOUT api_key -> key preserved
    r = api("PUT", f"/api/v1/apps/{app_id}", tok, json={
        "retrieval_config": {
            "top_k": 8,
            "rerank_mode": "api",
            "rerank_config": {"model": "BAAI/bge-reranker-v2-m3"},
        }})
    rr2 = (r.json().get("retrieval_config", {}).get("rerank_config", {})
           if r.status_code == 200 else {})
    enc2 = db_scalar(
        f"SELECT retrieval_config->'rerank_config'->>'api_key_enc' FROM apps WHERE id='{app_id}'")
    check("R4", "re-save w/o key keeps api_key_enc, merges other fields",
          r.status_code == 200 and enc2 == enc and rr2.get("api_key_set") is True
          and r.json()["retrieval_config"]["top_k"] == 8,
          f"enc_preserved={enc2 == enc} top_k={r.json()['retrieval_config'].get('top_k')}")

    # R5 clear_api_key -> removed from DB and output
    r = api("PUT", f"/api/v1/apps/{app_id}", tok, json={
        "retrieval_config": {
            "rerank_mode": "api",
            "rerank_config": {"clear_api_key": True},
        }})
    rr3 = (r.json().get("retrieval_config", {}).get("rerank_config", {})
           if r.status_code == 200 else {})
    enc3 = db_scalar(
        f"SELECT retrieval_config->'rerank_config'->>'api_key_enc' FROM apps WHERE id='{app_id}'")
    check("R5", "clear_api_key removes stored key",
          r.status_code == 200 and not enc3 and not rr3.get("api_key_set"),
          f"db_empty={not enc3} out_keys={sorted(rr3.keys())}")

    # R6 runtime decryption path: re-save real-format key, rerank service can decrypt
    r = api("PUT", f"/api/v1/apps/{app_id}", tok, json={
        "retrieval_config": {
            "rerank_mode": "api",
            "rerank_config": {"api_key": FAKE_KEY},
        }})
    check("R6a", "PUT re-save api_key succeeds (no 500)",
          r.status_code == 200 and r.json()["retrieval_config"]["rerank_config"].get("api_key_set"),
          f"HTTP {r.status_code} {r.text[:150]}")
    probe = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", "-c", "\n".join([
            "import sys, asyncio, json",
            f"app_id = '{app_id}'",
            "from sqlalchemy import select",
            "from app.db.session import session_scope",
            "from app.models.app import App",
            "from app.core.crypto import decrypt_secret",
            "",
            "",
            "async def main():",
            "    async with session_scope() as s:",
            "        a = (await s.execute(select(App).where(App.id == app_id))).scalar_one()",
            "        enc = a.retrieval_config['rerank_config']['api_key_enc']",
            "        print(json.dumps({'dec_ok': decrypt_secret(enc) == sys.argv[1]}))",
            "",
            "",
            "asyncio.run(main())",
        ]), FAKE_KEY],
        capture_output=True, text=True, timeout=60)
    dec_ok = '"dec_ok": true' in probe.stdout or '"dec_ok":true' in probe.stdout
    check("R6", "api container decrypts stored key back to plaintext",
          dec_ok, f"stdout={probe.stdout.strip()[:200]} stderr={probe.stderr.strip()[-400:]}")

    d = api("DELETE", f"/api/v1/apps/{app_id}", tok)
    check("R7", "cleanup throwaway app", d.status_code == 204, f"HTTP {d.status_code}")


def report(results):
    fails = [x for x in results if not x[2]]
    print(f"\n=== rerank roundtrip: {len(results) - len(fails)}/{len(results)} passed ===")
    if fails:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
