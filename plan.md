# just-agentic — Architecture Plan

## Context
- **Product**: SaaS — ขายให้หลายบริษัท (multi-tenant)
- **Scale target**: 1,000–5,000 concurrent users
- **Compliance**: audit log ต้องครบ, data ต้องอยู่ใน region (data residency)

---

## Phase 1 — Scalability
> FastAPI stateless + Redis + Worker Queue

**Goal:**
- Technical : API stateless, Worker pool รัน graph, SSE relay ผ่าน Redis pub/sub
- Business  : รองรับ 1,000+ concurrent users, deploy ได้โดยไม่ downtime, scale ตาม demand
- Metric    : 1,000 concurrent users, p95 latency < 3s, zero downtime rolling deploy, worker auto-scale ตาม queue depth

**ปัญหาที่แก้:** API process เดียว hold SSE connection + รัน graph → ไม่สามารถ scale horizontal ได้

**สิ่งที่ทำ:**
1. เพิ่ม Redis service ใน docker-compose
2. FastAPI enqueue task → Redis แทนรัน graph โดยตรง
3. Worker process (ARQ) consume queue → รัน LangGraph graph → publish SSE events → Redis pub/sub
4. FastAPI SSE endpoint relay จาก Redis pub/sub (stateless)
5. Client ไม่ต้องเปลี่ยนเลย

**ผลลัพธ์:**
- Scale API instance ได้ไม่จำกัด (stateless)
- Scale worker ได้ตาม load
- Instance ล่มไม่กระทบ session อื่น

---

## Phase 2 — Tool Execution Security
> แยก Tool Execution ออกจาก API/Worker process

**Goal:**
- Technical : Tool รันใน isolated container, network allowlist, resource limit ต่อ call
- Business  : ลูกค้า enterprise ต้องการ security guarantee ก่อน sign contract, ป้องกัน liability จาก malicious tool use
- Metric    : zero cross-tenant data access, tool timeout < 60s enforced, CPU/RAM capped ต่อ session, penetration test ผ่าน

**ปัญหาที่แก้:** `run_shell` / `execute_python` รันใน container เดียวกับ API — bypass blocklist ได้ → ทำลาย server, resource exhaustion, network leak

**สิ่งที่ทำ:**
1. **Option A (เริ่มต้น)** — Resource limits + ulimit + subprocess timeout ทุก tool call
2. **Option B (หลัก)** — Tool Execution Service แยก container
   - Worker → HTTP/gRPC → Tool Service
   - workspace mount: read/write
   - /app mount: read-only
   - network: none (หรือ allowlist เฉพาะ web_search)
   - CPU/RAM limit ต่อ call
   - timeout hard kill

**ผลลัพธ์:**
- Server code ไม่ถูกแตะได้
- Tool ล่มไม่กระทบ API/Worker
- Resource usage controllable

---

## Phase 3 — Multi-tenancy + Full Isolation
> Ephemeral Sandbox ต่อ session + Data Residency

**Goal:**
- Technical : Sandbox ต่อ session, data แยกต่อ tenant (schema/DB), deploy ได้ต่าง region, audit log ทุก action ครบถ้วน
- Business  : รองรับ enterprise ที่มี compliance requirement (PDPA, GDPR, SOC2), ขายได้ทั้ง บริษัทไทย/EU/US โดยไม่ผิดกฎหมาย data residency
- Metric    : zero cross-tenant data leak, audit log 100% coverage, deploy ได้ใน AWS/GCP region ที่ลูกค้าเลือก, รองรับ 5,000 concurrent users, RTO < 1 hr

**ปัญหาที่แก้:**
- /tmp shared ระหว่าง users → data leak
- Resource fairness — user เดียว block ทั้ง pool
- Workspace collision — หลาย user เขียน path เดียวกัน
- Data residency — ข้อมูลลูกค้าต้องไม่ข้าม region

**สิ่งที่ทำ:**
1. Spawn ephemeral sandbox container ต่อ session (Docker / Kubernetes Pod)
2. Mount workspace ของ user นั้นเท่านั้น, kill เมื่อ session จบ
3. Database per tenant (schema separation) หรือ separate DB per region
4. Priority queue per role (admin > manager > analyst > viewer)
5. Rate limiting per user_id + per tenant (Redis)
6. Region-aware deployment (Kubernetes multi-cluster)
7. Audit log pipeline → immutable storage (S3/GCS per region)

**ผลลัพธ์:**
- User A ไม่เห็นข้อมูล User B เลย
- Tenant A data ไม่ออกนอก region ที่กำหนด
- Audit log ครบ ตรวจสอบย้อนหลังได้
- Resource exhaustion กระทบแค่ session ตัวเอง

---

## Summary

| Phase | เรื่อง | Effort | Business Goal | Key Metric |
|---|---|---|---|---|
| 1 | Scalability | 1–2 สัปดาห์ | รองรับ 1,000+ users, no downtime deploy | p95 < 3s, 1,000 concurrent |
| 2 | Tool Security | 2–4 สัปดาห์ | ผ่าน enterprise security review | pentest pass, zero server breach |
| 3 | Multi-tenancy + Compliance | 2–3 เดือน | ขาย enterprise ได้, PDPA/GDPR ready | 5,000 concurrent, data residency |
