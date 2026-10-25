# 🧭 HƯỚNG DẪN DEMO HỆ THỐNG ĐẶT TÊN DỊCH VỤ PHÂN TÁN
## (DISTRIBUTED NAMING SERVICE & SERVICE DISCOVERY CLUSTER)

---

### 1. CẤU TRÚC HỆ THỐNG THEO YÊU CẦU

Hệ thống được tổ chức gọn gàng thành **3 file Python chính**:

| Thành phần | File code | Cổng (Port) | Vai trò & Tính năng chính |
| :--- | :--- | :--- | :--- |
| **Đối tượng 1: Naming Server** | `naming_server.py` | `4000` | Lưu trữ danh bạ (`/api/register`), nhận nhịp tim (`/api/heartbeat`), phân giải (`/api/lookup`), kiểm tra timeout 6s (đổi màu badge đỏ TIMEOUT/DEAD), nút [🟢 Khởi động lại] node chết, Unbind thủ công, Live Logs. |
| **Đối tượng 2: Service Node 1** | `service_node.py` | `5001` | Đăng ký tự động, gửi Heartbeat mỗi 3s, xử lý nghiệp vụ (`/api/process`), nút [🛑 Tắt Node (Giả lập sập)] (HTTP 503), nút [🟢 Bật lại Node (Re-bind)], Counter số to nhảy số. |
| **Đối tượng 2: Service Node 2** | `service_node.py` | `5002` | Node thứ 2 chạy song song trong cụm (`--port 5002`) để demo cân bằng tải và chịu lỗi Failover. |
| **Đối tượng 3: Client Dashboard** | `client_app.py` | `3000` | Chọn chế độ (Hard-code vs Naming Service), Local Cache (TTL 10s), Chọn Round-Robin / Random, Sơ đồ luồng 2 bước sáng đèn LED, Bảng Lịch sử Request. |

---

### 2. CÁCH KHỞI CHẠY HỆ THỐNG

Mở 4 cửa sổ Terminal riêng biệt và chạy từng lệnh:
- **Terminal 1 (Naming Server):** `python naming_server.py --port 4000`
- **Terminal 2 (Service Node 1):** `python service_node.py --port 5001 --name order-service`
- **Terminal 3 (Service Node 2):** `python service_node.py --port 5002 --name order-service`
- **Terminal 4 (Client App):** `python client_app.py --port 3000`

Sau đó mở 4 tab trình duyệt:
- `http://localhost:4000` (Naming Server)
- `http://localhost:5001` (Service Node 1)
- `http://localhost:5002` (Service Node 2)
- `http://localhost:3000` (Client Dashboard)

---

### 3. KỊCH BẢN THUYẾT TRÌNH & DEMO CHI TIẾT TRÊN LỚP

#### 🟢 KỊCH BẢN 1: ĐĂNG KÝ DỊCH VỤ & GIÁM SÁT SỨC KHỎE (PORT 4000 & 5001, 5002)
1. **Quan sát tab `http://localhost:4000`:**
   - Cả 2 node `127.0.0.1:5001` và `127.0.0.1:5002` xuất hiện trong bảng **Naming Table** với badge xanh **HEALTHY**.
   - Cột **Nhịp tim cuối** nhảy liên tục `0.5s trước`, `1.2s trước`... do background thread của từng node gửi heartbeat mỗi 3 giây.
   - Khung **Live Logs** ở dưới hiển thị liên tục các bản tin `[REGISTER]` và `[HEARTBEAT]`.
2. **Lời thuyết trình:**
   > *"Kính thưa thầy cô và các bạn, đây là Naming Server hoạt động như một Service Registry. Các Service Node khi khởi động sẽ tự phát hiện và đăng ký địa chỉ IP:Port lên đây. Định kỳ 3 giây, các node gửi tín hiệu Heartbeat để khẳng định mình vẫn đang sống."*

---

#### 🟢 KỊCH BẢN 2: CÂN BẰNG TẢI LUÂN PHIÊN ROUND-ROBIN (PORT 3000)
1. **Chuyển sang tab `http://localhost:3000` (Client):**
   - Bấm nút **[🚀 GỬI 1 REQUEST]** lần 1:
     - Client tự động hỏi Naming Server -> Luân phiên gọi sang `127.0.0.1:5001`.
     - Bảng Lịch sử ghi nhận: Node đích `127.0.0.1:5001`, HTTP 200 OK.
     - Quan sát tab `http://localhost:5001`: Counter số to nhảy lên **1**.
   - Bấm nút **[🚀 GỬI 1 REQUEST]** lần 2:
     - Client tiếp tục luân phiên gọi sang `127.0.0.1:5002`.
     - Bảng Lịch sử ghi nhận: Node đích `127.0.0.1:5002`, HTTP 200 OK.
     - Quan sát tab `http://localhost:5002`: Counter số to nhảy lên **1**.
   - Bấm tiếp các lần sau để thấy các request được chia đều đặn 50% - 50% giữa 2 node.

---

#### 🔴 KỊCH BẢN 3: GIẢ LẬP SẬP SERVER & TỰ ĐỘNG CHỊU LỖI (FAILOVER)
1. **Bước 1 - Giả lập sập Node 1:**
   - Sang tab `http://localhost:5001`, bấm nút lớn màu đỏ **[🛑 NGỪNG GỬI HEARTBEAT / GIẢ LẬP SẬP NODE]**.
   - Viền của Node 5001 chuyển sang **Đỏ rực**, thông báo sập xuất hiện và node ngừng gửi nhịp tim.
2. **Bước 2 - Naming Server phát hiện Timeout sau 6s:**
   - Quan sát tab Naming Server (`:4000`): Sau đúng 6 giây mặc định không nhận được heartbeat từ Node 5001, Naming Server tự động đổi badge sang **ĐỎ: TIMEOUT (DEAD)** và ghi log cảnh báo.
3. **Bước 3 - Client tự động chuyển hướng chịu lỗi (Failover):**
   - Quay lại tab Client (`:3000`), bấm **[🚀 GỬI 1 REQUEST]**:
     - Client hỏi Naming Server. Naming Server chỉ trả về node đang sống là `[127.0.0.1:5002]`.
     - Client tự động định tuyến (Failover) gọi sang `Node 5002` -> **Thành công HTTP 200**!
     - Dịch vụ không hề bị gián đoạn đối với người dùng!
4. **Bước 4 - Phục hồi node (Re-bind):**
   - Sang tab Node 1 (`:5001`), bấm nút màu xanh **[🟢 BẬT LẠI NODE (RE-BIND)]** (hoặc nút **[Bật lại Node ngay]** trên thanh thông báo).
   - Node 1 hồi phục trạng thái xanh bình thường và tiếp tục gửi heartbeat.
   - Naming Server (`:4000`) lập tức nhận lại heartbeat và chuyển trạng thái Node 1 thành **HEALTHY**.
   - Client (`:3000`) tiếp tục luân phiên phân chia tải đều đặn cho cả 2 node bình thường!
