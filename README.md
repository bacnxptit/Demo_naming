# HỆ THỐNG MÔ PHỎNG & DEMO ĐẶT TÊN TRONG HỆ THỐNG PHÂN TÁN
## (DISTRIBUTED NAMING SERVICE: REGISTRY, DISCOVERY, LOAD BALANCING & FAULT TOLERANCE)

Dự án được xây dựng dựa trên kiến thức **Chương 6: Naming** từ giáo trình quốc tế **Distributed Systems (4th Edition)** của Maarten van Steen & Andrew S. Tanenbaum.

Hệ thống mô phỏng thực tế kiến trúc **Service Registry, Dynamic Discovery, Client-side Caching & Failover** trong các hệ thống phân tán và vi dịch vụ (Microservices), bao gồm 4 tiến trình chạy độc lập có giao diện Dashboard Web tương tác trực quan:

```text
                         ┌─────────────────────────────────┐
                         │   Client Dashboard (Port 3000)  │
                         │    (Cache TTL, Sơ đồ 2 bước)    │
                         └────────────────┬────────────────┘
                                          │
                      1. /api/lookup      │  2. Gọi thực thi
                     ("order-service")    │     /api/process
                                          │
                                          ▼
                         ┌─────────────────────────────────┐
                         │   Naming Server (Port 4000)     │
                         │   - Service Registry            │
                         │   - Heartbeat Monitor (6s timeout)
                         │   - Live Logs & Node Management │
                         └────────────────┬────────────────┘
                                          │
                            ┌─────────────┴─────────────┐
             Heartbeat (3s) │                           │ Heartbeat (3s)
                            ▼                           ▼
            ┌───────────────────────────┐   ┌───────────────────────────┐
            │   Service Node 1 (:5001)  │   │   Service Node 2 (:5002)  │
            │   - Tên: order-service    │   │   - Tên: order-service    │
            │   - Nút [🛑 Giả lập Sập]   │   │   - Xử lý nghiệp vụ       │
            │   - Nút [🟢 Re-bind]       │   │   - Counter nhảy số live  │
            └───────────────────────────┘   └───────────────────────────┘
```

---

## 📂 DANH MỤC TÀI LIỆU & MÃ NGUỒN

| Tệp / Thư mục | Mô tả nội dung |
| :--- | :--- |
| **[KICH_BAN_DEMO.md](file:///d:/DistributeSystem_Naming/KICH_BAN_DEMO.md)** | Kịch bản demo chi tiết 4 phần (Đăng ký, Phân giải & Cache, Cân bằng tải, Chịu lỗi), lời thoại thuyết trình (Speaker Notes) |
| **[HUONG_DAN_SU_DUNG.md](file:///d:/DistributeSystem_Naming/HUONG_DAN_SU_DUNG.md)** | Hướng dẫn thao tác nhanh trên giao diện Web Dashboard của từng cổng |
| **[SLIDES_PRESENTATION.md](file:///d:/DistributeSystem_Naming/SLIDES_PRESENTATION.md)** | Dàn bài 19 Slide thuyết trình hoàn chỉnh (Lý thuyết Chương 6 + Kiến trúc Demo + Speaker Notes) |
| **[CHƯƠNG_6_TONG_HOP_KIEN_THUC.md](file:///d:/DistributeSystem_Naming/CH%C6%AF%C6%A0NG_6_TONG_HOP_KIEN_THUC.md)** | Tóm tắt học thuật chuyên sâu Mục 6.1 đến 6.6 từ giáo trình Tanenbaum |
| **`naming_server.py`** | Mã nguồn Naming Server (Port 4000: Registry, Heartbeat Monitor 6s, Web Dashboard) |
| **`service_node.py`** | Mã nguồn Service Worker (Port 5001, 5002: Tự động đăng ký, gửi Heartbeat mỗi 3s, nút giả lập sập / phục hồi) |
| **`client_app.py`** | Mã nguồn Client Application (Port 3000: Caching TTL 10s, Round-Robin/Random, Sơ đồ 2 bước sáng đèn, Failover) |
---

## 🚀 HƯỚNG DẪN CHẠY BÀI DEMO

Mở 4 cửa sổ Terminal riêng biệt tại thư mục dự án và chạy từng lệnh:
- **Terminal 1 (Naming Server):** `python naming_server.py --port 4000`
- **Terminal 2 (Service Node 1):** `python service_node.py --port 5001 --name order-service`
- **Terminal 3 (Service Node 2):** `python service_node.py --port 5002 --name order-service`
- **Terminal 4 (Client App):** `python client_app.py --port 3000`

Sau đó mở 4 tab trình duyệt sẵn sàng thuyết trình:
- **Naming Server:** `http://localhost:4000`
- **Service Node 1:** `http://localhost:5001`
- **Service Node 2:** `http://localhost:5002`
- **Client Dashboard:** `http://localhost:3000`

---

## 🎯 CÁC KỊCH BẢN THỰC NGHIỆM CHÍNH

1. **Demo 1 – Service Registration & Heartbeat Monitor (Port 4000, 5001, 5002):**
   - Node tự động đăng ký Tên logic `order-service`.
   - Giám sát nhịp tim thời gian thực mỗi 3 giây.
   - *Ý nghĩa:* Tách biệt Định danh và Vị trí (**Identifier-Location Split**).

2. **Demo 2 – Service Discovery & Local Caching (Port 3000):**
   - Client hỏi Naming Server ➔ nhận danh sách địa chỉ sống ➔ gọi trực tiếp.
   - Cơ chế Local Cache (TTL 10s) giảm tải tối đa cho Naming Server.
   - *Ý nghĩa:* Tính trong suốt về vị trí (**Location Transparency**).

3. **Demo 3 – Round-Robin & Random Load Balancing:**
   - Client phân phối tải xen kẽ giữa Node 5001 và Node 5002.
   - Counter nhảy số live trên cả 2 màn hình node.
   - *Ý nghĩa:* Khả năng mở rộng theo chiều ngang (**Horizontal Scalability**).

4. **Demo 4 – Giả lập Sập Node, Phát hiện Timeout, Tự động Chịu lỗi (Failover) & Phục hồi:**
   - So sánh nguy cơ khi Hardcode IP (gây lỗi 503 sụp đổ hệ thống).
   - Khi sập Node 5001, Naming Server phát hiện Timeout sau 6s. Client tự động chuyển hướng gọi Node 5002 sống sót.
   - Bấm Re-bind để phục hồi node và hệ thống tự động cân bằng tải trở lại.
   - *Ý nghĩa:* Khả năng chịu lỗi và tự chữa lành (**Fault Tolerance & Self-Healing**).
