# KỊCH BẢN DEMO HỆ THỐNG ĐẶT TÊN DỊCH VỤ PHÂN TÁN
## (SERVICE NAMING, DISCOVERY, LOAD BALANCING & FAULT TOLERANCE)
> *Mô phỏng kiến trúc Service Registry, Dynamic Discovery, Caching, Load Balancing & Fault Tolerance (Chương 6 - Naming)*

---

## 1. KIẾN TRÚC CỤM DỊCH VỤ DEMO

Hệ thống gồm 4 tiến trình độc lập chạy trên các cổng riêng biệt, tích hợp sẵn Giao diện Web (Live Dashboard) tương tác trực quan:

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

### Các thành phần:
1. **Naming Server (Port 4000):**
   - Đóng vai trò là **Service Registry & Name Resolution Server**.
   - API: `POST /api/register`, `POST /api/heartbeat`, `GET /api/lookup/{service_name}`, `POST /api/unbind`.
   - Giám sát nhịp tim định kỳ: nếu một node quá 6s không gửi Heartbeat sẽ tự động đổi trạng thái sang `TIMEOUT (DEAD)`.
   - Web Dashboard: `http://localhost:4000`.
2. **Service Node 1 (Port 5001):**
   - Instance 1 của dịch vụ xử lý đơn hàng (`order-service`).
   - Tự động đăng ký khi bật và gửi heartbeat mỗi 3 giây.
   - Có nút bấm trực quan để **Giả lập sập node / Ngừng heartbeat** và nút **Khởi động lại (Re-bind)**.
   - Web Dashboard: `http://localhost:5001`.
3. **Service Node 2 (Port 5002):**
   - Instance 2 của `order-service` chạy song song để minh họa phân phối tải và chịu lỗi.
   - Web Dashboard: `http://localhost:5002`.
4. **Client Dashboard (Port 3000):**
   - Ứng dụng tương tác người dùng: hỗ trợ so sánh gọi trực tiếp (Hardcoded IP) và qua Naming Service.
   - Tích hợp **Local Cache** (TTL 10 giây), tùy chọn thuật toán **Round-Robin** / **Random**, sơ đồ luồng 2 bước sáng đèn LED thời gian thực.
   - Web Dashboard: `http://localhost:3000`.

---

## 2. CHUẨN BỊ & KHỞI CHẠY HỆ THỐNG

Khởi động 4 server trong 4 cửa sổ Terminal riêng biệt:
- **Terminal 1:** `python naming_server.py --port 4000`
- **Terminal 2:** `python service_node.py --port 5001 --name order-service`
- **Terminal 3:** `python service_node.py --port 5002 --name order-service`
- **Terminal 4:** `python client_app.py --port 3000`

Sau đó mở 4 tab trình duyệt để sẵn sàng demo:
- `http://localhost:4000` (Naming Server Registry)
- `http://localhost:5001` (Service Node 1)
- `http://localhost:5002` (Service Node 2)
- `http://localhost:3000` (Client Application)

---

## 3. KỊCH BẢN CHI TIẾT 4 PHẦN DEMO

---

### DEMO 1 – ĐĂNG KÝ DỊCH VỤ & GIÁM SÁT SỨC KHỎE (SERVICE REGISTRATION & HEARTBEAT)

#### Thao tác trên màn hình:
1. Mở tab **Naming Server** (`http://localhost:4000`).
2. Quan sát bảng **Naming Table**:
   - Hai node `127.0.0.1:5001` và `127.0.0.1:5002` đã được tự động đăng ký dưới cùng Tên logic: `order-service`.
   - Cả 2 đều có huy hiệu xanh **HEALTHY**.
   - Cột **Nhịp tim cuối (Last Seen)** cập nhật liên tục: `0.4s trước`, `1.1s trước`... do các node gửi heartbeat đều đặn mỗi 3s.
3. Khung **Live Logs** ở dưới hiển thị các sự kiện `[REGISTER]` và `[HEARTBEAT]` theo thời gian thực.

#### Lời thoại thuyết trình (Speaker Notes):
> *"Kính thưa thầy cô và các bạn, đây là phần Demo 1 về Service Registration và Giám sát sức khỏe. Trong các hệ sinh thái phân tán hiện đại, các dịch vụ không còn gán địa chỉ IP tĩnh cứng nhắc. Khi Node 1 và Node 2 vừa khởi động, chúng lập tức tự động gửi yêu cầu đăng ký lên Naming Server với cùng một Tên logic (Logical Name) là `order-service`.
> 
> Ý nghĩa học thuật ở đây chính là nguyên lý **Tách biệt Định danh và Vị trí (Identifier-Location Split)** trong Chương 6. Client từ nay chỉ cần biết tên logic `order-service`, còn IP và cổng vật lý sẽ do Naming Server linh hoạt quản lý. Đồng thời, cơ chế Heartbeat định kỳ 3 giây giúp Naming Server luôn duy trì một danh bạ chính xác về các thực thể còn sống."*

---

### DEMO 2 – PHÂN GIẢI TÊN, TÍNH TRONG SUỐT VỊ TRÍ & LOCAL CACHING

#### Thao tác trên màn hình:
1. Mở tab **Client Dashboard** (`http://localhost:3000`).
2. Giữ nguyên chế độ mặc định: **Sử dụng Naming Service**, Caching: **Bật (TTL 10s)**.
3. Bấm nút **[🚀 GỬI 1 REQUEST]** lần thứ nhất:
   - **Sơ đồ 2 bước sáng đèn:**
     - **Bước 1 (Name Resolution):** Client gửi truy vấn `GET /api/lookup/order-service` tới Naming Server (`:4000`), nhận về danh sách `[127.0.0.1:5001, 127.0.0.1:5002]`.
     - **Bước 2 (Service Invocation):** Client kết nối trực tiếp tới Node được chọn và nhận mã phản hồi HTTP 200 kèm mã giao dịch `TXN-...`.
   - Khung **Trạng thái Cache** chuyển sang hiển thị: `Đang lưu 2 nodes`, đếm ngược TTL: `10s... 9s...`.
4. Bấm nút **[🚀 GỬI 1 REQUEST]** lần thứ hai (khi TTL còn hiệu lực):
   - Bước 1 lập tức báo **Cache HIT!** Client không cần tốn tài nguyên gửi gói tin mạng lên Naming Server nữa, mà lấy trực tiếp từ bộ nhớ cục bộ để gọi Node.

#### Lời thoại thuyết trình (Speaker Notes):
> *"Tại Demo 2, chúng ta thấy rõ thuộc tính **Location Transparency (Tính trong suốt về vị trí)**: Client hoàn toàn không bị gán cứng bất kỳ địa chỉ IP hay port nào trong mã nguồn. 
> 
> Để tối ưu hóa hiệu năng và tránh biến Naming Server thành điểm nghẽn cổ chai (Bottleneck) giống như cách hệ thống DNS phân cấp hoạt động, Client được trang bị cơ chế **Local Cache**. Với lần gọi thứ hai, Client nhận ra dữ liệu còn hạn TTL nên không cần hỏi lại Naming Server, giảm thiểu độ trễ mạng xuống mức tối đa."*

---

### DEMO 3 – CÂN BẰNG TẢI XOAY VÒNG & NGẪU NHIÊN (LOAD BALANCING)

#### Thao tác trên màn hình:
1. Tại tab Client (`:3000`), chọn thuật toán: **Round-Robin (Luân phiên)**.
2. Bật công tắc **[🔄 TỰ ĐỘNG GỬI (MỖI 2S)]** hoặc bấm liên tiếp 6 lần nút **[🚀 GỬI 1 REQUEST]**:
   - Quan sát bảng **Lịch sử Request**: Các yêu cầu được phân bổ xen kẽ hoàn hảo:
     - Request 1 ➔ `127.0.0.1:5001`
     - Request 2 ➔ `127.0.0.1:5002`
     - Request 3 ➔ `127.0.0.1:5001`
     - Request 4 ➔ `127.0.0.1:5002`...
   - Đồng thời chuyển mắt sang 2 tab của Node 1 (`:5001`) và Node 2 (`:5002`): **Bộ đếm số to (Requests Handled)** trên cả 2 màn hình cùng nhảy số tăng đều 50% - 50%.
3. Chuyển thuật toán sang **Random (Ngẫu nhiên)** để thấy cơ chế phân phối tải phân tán dựa trên xác suất.

#### Lời thoại thuyết trình (Speaker Notes):
> *"Demo 3 minh họa việc ánh xạ một Tên logic thành nhiều Điểm truy cập vật lý (1-to-N Mapping). Naming Service cùng cơ chế lựa chọn ở phía Client giúp phân phối đều tải công việc.
> 
> Điều này minh chứng cho 3 nguyên lý trụ cột: **Chia sẻ tài nguyên (Resource Sharing)**, **Xử lý đồng thời (Concurrency)** và **Khả năng mở rộng theo chiều ngang (Horizontal Scalability)**: Khi lượng người dùng tăng cao, ta chỉ cần bật thêm Node 3, Node 4 mà không phải sửa đổi dù chỉ 1 dòng code ở phía Client."*

---

### DEMO 4 – PHÁT HIỆN SỰ CỐ, TỰ ĐỘNG CHỊU LỖI (FAILOVER) & PHỤC HỒI (RE-BIND)

#### Thao tác trên màn hình:
1. **Bước 1 - Nguy cơ khi dùng IP cứng (Hard-coded IP):**
   - Tại Client (`:3000`), chọn chế độ **Gọi trực tiếp IP cứng (Hard-coded: 5001)**.
   - Sang tab Node 1 (`:5001`), bấm nút lớn màu đỏ: **[🛑 NGỪNG GỬI HEARTBEAT / GIẢ LẬP SẬP NODE]**.
   - Màn hình Node 1 chuyển sang viền đỏ rực báo động: `NODE ĐÃ SẬP!`.
   - Quay lại Client (`:3000`), bấm **[🚀 GỬI 1 REQUEST]**: Kết quả trả về ngay lập tức là **LỖI ĐỎ HTTP 503 (SERVICE UNAVAILABLE)**! Toàn bộ người dùng bị nghẽn tắc.
2. **Bước 2 - Sức mạnh tự phục hồi của Naming Service:**
   - Quan sát tab Naming Server (`:4000`): Sau đúng **6 giây** không thấy nhịp tim từ Node 5001, Naming Server kích hoạt cảnh báo, lập tức chuyển trạng thái Node 5001 sang **ĐỎ: TIMEOUT (DEAD)**.
   - Quay lại Client (`:3000`), chuyển lại chế độ **Sử dụng Naming Service**. Bấm nút **[Xóa Cache]** và bấm **[🚀 GỬI 1 REQUEST]**:
     - Client hỏi Naming Server. Naming Server đã loại bỏ Node 5001 chết và chỉ trả về Node 5002 sống.
     - Yêu cầu được tự động định tuyến (**Failover**) sang `127.0.0.1:5002` ➔ **THÀNH CÔNG HTTP 200**! Người dùng không hề hay biết một máy chủ vừa gặp sự cố.
3. **Bước 3 - Phục hồi thực thể (Self-healing & Re-bind):**
   - Sang tab Node 1 (`:5001`), bấm nút màu xanh: **[🟢 KHỞI ĐỘNG LẠI & ĐĂNG KÝ LẠI (RE-BIND)]**.
   - Node 1 hồi phục trạng thái xanh bình thường.
   - Tab Naming Server (`:4000`) nhận bản tin Re-bind, lập tức đưa Node 1 trở lại danh sách **HEALTHY**.
   - Client tiếp tục luân phiên chia tải cho cả 2 node bình thường.

#### Lời thoại thuyết trình (Speaker Notes):
> *"Đây là phần quan trọng nhất của bài báo cáo: Tính chịu lỗi và Tự phục hồi (Fault Tolerance & Self-Healing). 
> Khi một node gặp sự cố, kiến trúc cứng nhắc dùng IP tĩnh sẽ khiến cả hệ thống sụp đổ dây chuyền. Ngược lại, nhờ Naming Service liên tục theo dõi nhịp tim qua Heartbeat Timeout, node lỗi bị đào thải khỏi danh bạ chỉ sau vài giây. 
> 
> Quan trọng hơn hết, **Client không cần biết node nào hỏng hay vị trí thay đổi ra sao**. Tính trong suốt về vị trí và khả năng chuyển hướng dự phòng (Failover) bảo đảm hệ thống luôn đạt độ sẵn sàng cao nhất (High Availability)!"*

---

## 4. TỔNG KẾT BÀI BÁO CÁO (CHƯƠNG 6)

- **Định danh vs Địa chỉ:** Tách biệt Tên logic khỏi IP vật lý là nền tảng sống còn của mọi hệ thống phân tán (DNS, Consul, Eureka, Kubernetes CoreDNS).
- **Tính trong suốt:** Giúp che giấu sự phân tán, che giấu lỗi phần cứng và che giấu việc tái cấu trúc hạ tầng đối với người dùng cuối.
- **Tính sẵn sàng cao:** Kết hợp Health Check + Dynamic Discovery tạo ra cơ chế tự lành (Self-healing) linh hoạt và bền bỉ.
