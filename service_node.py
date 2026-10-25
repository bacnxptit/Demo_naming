"""
SERVICE NODE TRONG CLUSTER - CUNG CẤP DỊCH VỤ THỰC TẾ
Cho phép truyền --port và --name qua dòng lệnh (vd: python service_node.py --port 5001 --name order-service)
"""

import sys
import time
import asyncio
import threading
from datetime import datetime
from typing import List, Optional
import requests
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# UTF-8 support on Windows
if sys.platform.startswith("win"):
    import io
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

# ==============================================================================
# GLOBAL NODE CONFIG & STATE
# ==============================================================================
NODE_PORT = 5001
SERVICE_NAME = "order-service"
NODE_HOST = "127.0.0.1"
REGISTRY_URL = "http://127.0.0.1:4000"

is_crashed = False
handled_requests_count = 0
last_heartbeat_time: Optional[float] = None
logs: List[dict] = []
MAX_LOGS = 100

def add_log(event_type: str, message: str, level: str = "INFO"):
    timestamp = datetime.now().strftime("%H:%M:%S")
    entry = {
        "timestamp": timestamp,
        "type": event_type,
        "message": message,
        "level": level,
        "time_raw": time.time()
    }
    logs.append(entry)
    if len(logs) > MAX_LOGS:
        logs.pop(0)
    print(f"[{timestamp}] [{event_type}] {message}")

# ==============================================================================
# FASTAPI APPLICATION
# ==============================================================================
app = FastAPI(title="Cluster Service Node", description="Actual service provider worker")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def register_with_naming_server():
    """Gửi yêu cầu đăng ký lên Naming Server (Port 4000)"""
    try:
        payload = {
            "service_name": SERVICE_NAME,
            "ip": NODE_HOST,
            "port": NODE_PORT
        }
        res = requests.post(f"{REGISTRY_URL}/api/register", json=payload, timeout=2.5)
        if res.status_code == 200:
            add_log("REGISTER", f"Đã đăng ký thành công với Naming Server ({REGISTRY_URL})", level="SUCCESS")
            return True
        else:
            add_log("REGISTER", f"Naming Server trả về lỗi: {res.status_code}", level="ERROR")
            return False
    except Exception as e:
        add_log("REGISTER", f"Không thể kết nối tới Naming Server ({REGISTRY_URL}): {e}", level="ERROR")
        return False

def heartbeat_worker_loop():
    """Luồng ngầm định kỳ mỗi 3 giây gửi Heartbeat nếu không bị giả lập sập"""
    global last_heartbeat_time
    # Đăng ký lần đầu khi worker khởi động
    time.sleep(1.0)
    register_with_naming_server()

    while True:
        try:
            time.sleep(3.0)
            if not is_crashed:
                payload = {
                    "service_name": SERVICE_NAME,
                    "ip": NODE_HOST,
                    "port": NODE_PORT
                }
                res = requests.post(f"{REGISTRY_URL}/api/heartbeat", json=payload, timeout=2.0)
                if res.status_code == 200:
                    last_heartbeat_time = time.time()
                    add_log("HEARTBEAT", f"Đã gửi Heartbeat định kỳ tới Naming Server ({REGISTRY_URL})", level="INFO")
                else:
                    add_log("HEARTBEAT", f"Lỗi phản hồi Heartbeat từ Naming Server: {res.status_code}", level="WARNING")
            else:
                # Nếu đang ở chế độ sập thì cố tình KHÔNG gửi heartbeat!
                pass
        except Exception as e:
            if not is_crashed:
                add_log("HEARTBEAT", f"Mất kết nối gửi Heartbeat tới Naming Server: {e}", level="WARNING")

@app.on_event("startup")
def startup_event():
    add_log("SYSTEM", f"Node [{SERVICE_NAME}] khởi động trên cổng {NODE_PORT}")
    # Bật background worker thread
    t = threading.Thread(target=heartbeat_worker_loop, daemon=True)
    t.start()

# ==============================================================================
# BUSINESS & CONTROL APIS
# ==============================================================================

@app.get("/api/process")
def process_request():
    """
    API xử lý nghiệp vụ khi Client gọi tới.
    Nếu đang giả lập sập: Trả về lỗi 503 Service Unavailable.
    Nếu bình thường: Tăng counter và trả về kết quả thành công.
    """
    global handled_requests_count
    if is_crashed:
        add_log("REJECTED", f"Từ chối yêu cầu từ Client do Node đang ở trạng thái GIẢ LẬP SẬP (HTTP 503)", level="ERROR")
        return JSONResponse(
            status_code=503,
            content={
                "status": "ERROR",
                "message": f"Dịch vụ tại Node {NODE_HOST}:{NODE_PORT} đang sập hoặc tạm ngưng phục vụ (503 Service Unavailable)",
                "handled_by": f"Node {NODE_HOST}:{NODE_PORT}",
                "timestamp": datetime.now().isoformat()
            }
        )

    handled_requests_count += 1
    req_id = handled_requests_count
    add_log("INCOMING CALL", f"Đã xử lý request #{req_id} từ Client thành công", level="SUCCESS")
    
    return {
        "status": "SUCCESS",
        "handled_by": f"Node {NODE_HOST}:{NODE_PORT}",
        "service": SERVICE_NAME,
        "request_id": req_id,
        "timestamp": datetime.now().isoformat()
    }

@app.post("/api/control/crash")
def simulate_crash():
    """Giả lập sập node: ngừng gửi heartbeat và từ chối mọi incoming request"""
    global is_crashed
    is_crashed = True
    add_log("CRASH", "🛑 ĐÃ KÍCH HOẠT GIẢ LẬP SẬP NODE! Dừng gửi Heartbeat & từ chối nhận request", level="ERROR")
    return {"status": "SUCCESS", "is_crashed": is_crashed}

@app.post("/api/control/recover")
def simulate_recover():
    """Khởi động lại & đăng ký lại với Naming Server"""
    global is_crashed, last_heartbeat_time
    is_crashed = False
    last_heartbeat_time = time.time()
    add_log("RECOVER", "🟢 ĐÃ KHỞI ĐỘNG LẠI NODE! Đang kết nối và đăng ký lại với Naming Server...", level="SUCCESS")
    # Gửi đăng ký ngay lập tức
    success = register_with_naming_server()
    return {"status": "SUCCESS", "is_crashed": is_crashed, "registered": success}

@app.get("/api/node-status")
def get_node_status():
    """Trả về trạng thái hiện tại của node cho Web UI polling"""
    now = time.time()
    elapsed_hb = round(now - last_heartbeat_time, 1) if last_heartbeat_time else None
    return {
        "service_name": SERVICE_NAME,
        "host": NODE_HOST,
        "port": NODE_PORT,
        "is_crashed": is_crashed,
        "handled_requests_count": handled_requests_count,
        "last_heartbeat_seconds_ago": elapsed_hb,
        "registry_url": REGISTRY_URL,
        "logs": logs[-35:]
    }

# ==============================================================================
# WEB DASHBOARD (http://localhost:5001, 5002)
# ==============================================================================

@app.get("/", response_class=HTMLResponse)
def index_html():
    return f"""<!DOCTYPE html>
<html lang="vi" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SERVICE NODE [{SERVICE_NAME}] - PORT {NODE_PORT}</title>
    <!-- TailwindCSS CDN -->
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {{
            darkMode: 'class',
            theme: {{
                extend: {{
                    colors: {{
                        darkBg: '#090d16',
                        cardBg: '#131b2e',
                        cardBorder: '#23324d',
                    }}
                }}
            }}
        }}
    </script>
    <!-- Font Awesome -->
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <!-- Google Fonts -->
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;600;700&display=swap" rel="stylesheet">
    <style>
        body {{
            font-family: 'Inter', sans-serif;
        }}
        .font-mono-code {{
            font-family: 'JetBrains Mono', monospace;
        }}
        .glow-emerald {{
            box-shadow: 0 0 35px -5px rgba(16, 185, 129, 0.4);
        }}
        .glow-rose {{
            box-shadow: 0 0 35px -5px rgba(244, 63, 94, 0.6);
            animation: pulseCrash 1.5s infinite alternate;
        }}
        @keyframes pulseCrash {{
            from {{ box-shadow: 0 0 20px -5px rgba(244, 63, 94, 0.5); }}
            to {{ box-shadow: 0 0 45px 5px rgba(244, 63, 94, 0.8); }}
        }}
        .pulse-dot {{
            animation: pulseAnimation 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
        }}
        @keyframes pulseAnimation {{
            0%, 100% {{ opacity: 1; transform: scale(1); }}
            50% {{ opacity: 0.3; transform: scale(1.2); }}
        }}
        /* Tùy chỉnh thanh cuộn */
        ::-webkit-scrollbar {{
            width: 8px;
            height: 8px;
        }}
        ::-webkit-scrollbar-track {{
            background: #090d16;
        }}
        ::-webkit-scrollbar-thumb {{
            background: #23324d;
            border-radius: 4px;
        }}
    </style>
</head>
<body class="bg-darkBg text-slate-100 min-h-screen flex flex-col antialiased">

    <!-- Top Navigation / Header với hiệu ứng viền đổi màu -->
    <header id="node-header" class="border-b-2 border-emerald-500/80 bg-slate-900/90 backdrop-blur sticky top-0 z-50 transition-all duration-500">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 flex flex-wrap items-center justify-between gap-4">
            <div class="flex items-center space-x-4">
                <div id="node-icon-box" class="w-12 h-12 rounded-xl bg-emerald-500/20 border border-emerald-500/50 flex items-center justify-center text-emerald-400 text-2xl shadow-lg transition-all">
                    ⚙️
                </div>
                <div>
                    <h1 class="text-2xl sm:text-3xl font-extrabold tracking-tight text-white flex items-center gap-3">
                         SERVICE NODE [{SERVICE_NAME}] - PORT {NODE_PORT}
                    </h1>
                    
                </div>
            </div>
            
            <div class="flex items-center gap-3">
                <span id="badge-status-top" class="inline-flex items-center px-4 py-1.5 rounded-full text-xs font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/40">
                    <span class="w-2.5 h-2.5 rounded-full bg-emerald-400 mr-2 pulse-dot"></span>
                    ONLINE & SẴN SÀNG
                </span>
            </div>
        </div>
    </header>

    <!-- Main Content -->
    <main class="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">

        <!-- Crash Alert Banner (Ẩn khi bình thường, Hiện khi sập) -->
        <div id="crash-alert-banner" class="hidden bg-rose-950/90 border-2 border-rose-500 rounded-2xl p-4 sm:p-5 text-rose-200 flex flex-wrap sm:flex-nowrap items-center justify-between gap-4 shadow-2xl glow-rose">
            <div class="flex items-center gap-4">
                <div class="w-12 h-12 rounded-xl bg-rose-500/30 border border-rose-500/60 flex items-center justify-center text-2xl text-rose-300 shrink-0 shadow-inner">
                    🚨
                </div>
                <div>
                    <h4 class="font-extrabold text-base text-rose-200 uppercase tracking-wider flex items-center gap-2">
                        <span>CẢNH BÁO: NODE ĐANG BỊ TẮT / GIẢ LẬP SẬP</span>
                        <span class="inline-block w-2.5 h-2.5 rounded-full bg-rose-500 animate-ping"></span>
                    </h4>
                    <p class="text-xs text-rose-300/80 mt-1">Node đã ngừng phát Heartbeat tới Naming Server (Port 4000) và từ chối xử lý (HTTP 503). Bấm nút bên cạnh để khôi phục ngay!</p>
                </div>
            </div>
            <button id="btn-banner-recover" onclick="recoverNode()" 
                    class="ml-auto w-full sm:w-auto px-5 py-3 rounded-xl font-black text-sm bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-400 hover:to-teal-500 active:scale-95 text-white shadow-lg shadow-emerald-950 transition-all border border-emerald-400/60 flex items-center justify-center gap-2.5 whitespace-nowrap cursor-pointer">
                <i class="fa-solid fa-power-off text-base"></i>
                <span>🟢 BẬT LẠI NODE NGAY</span>
            </button>
        </div>

        <!-- Status Cards -->
        <div class="grid grid-cols-1 md:grid-cols-3 gap-5">
            <!-- Card 1: Kết nối Naming Server -->
            <div class="bg-cardBg border border-cardBorder rounded-2xl p-5 shadow-xl relative overflow-hidden">
                <div class="flex items-center justify-between">
                    <p class="text-xs font-bold text-slate-400 uppercase tracking-wider">Kết Nối Naming Server</p>
                    <span id="registry-status-badge" class="px-2.5 py-0.5 rounded text-xs font-bold bg-cyan-500/20 text-cyan-300 border border-cyan-500/30">
                        ĐÃ ĐĂNG KÝ
                    </span>
                </div>
                <div class="mt-4 flex items-baseline gap-2">
                    <span class="text-lg font-bold text-white" id="registry-label">Đang phát nhịp tim</span>
                </div>
                <p class="text-xs text-slate-400 mt-2 flex items-center gap-1.5">
                    <i class="fa-regular fa-clock"></i> Nhịp tim gần nhất: <span id="last-hb-time" class="text-emerald-400 font-mono-code font-bold">--</span>
                </p>
            </div>

            <!-- Card 2: SỐ LƯỢNG REQUEST ĐÃ XỬ LÝ (GIANT COUNTER) -->
            <div class="bg-cardBg border border-cardBorder rounded-2xl p-5 shadow-xl relative overflow-hidden flex flex-col justify-between">
                <div class="flex items-center justify-between">
                    <p class="text-xs font-bold text-slate-400 uppercase tracking-wider">Số Lượng Request Đã Xử Lý</p>
                    <span class="w-8 h-8 rounded-lg bg-cyan-500/10 text-cyan-400 flex items-center justify-center text-sm">
                        <i class="fa-solid fa-bolt"></i>
                    </span>
                </div>
                <div class="my-2">
                    <!-- SỐ NHẢY TO -->
                    <span id="request-counter" class="text-5xl sm:text-6xl font-black tracking-tight text-cyan-400 drop-shadow-md">
                        0
                    </span>
                    <span class="text-slate-400 text-sm ml-1 font-semibold">requests</span>
                </div>
               
            </div>

            <!-- Card 3: Trạng thái Sức khỏe Node -->
            <div id="health-card" class="bg-cardBg border border-cardBorder rounded-2xl p-5 shadow-xl flex flex-col justify-between">
                <div class="flex items-center justify-between">
                    <p class="text-xs font-bold text-slate-400 uppercase tracking-wider">Trạng Thái Node</p>
                    <span id="health-state-dot" class="w-3 h-3 rounded-full bg-emerald-400 pulse-dot"></span>
                </div>
                <div class="my-2">
                    <span id="health-status-text" class="text-2xl font-black text-emerald-400 tracking-wide uppercase">
                        HEALTHY (ONLINE)
                    </span>
                </div>
                <p id="health-status-desc" class="text-xs text-slate-400">
                    Phát heartbeat mỗi 3 giây &bull; Sẵn sàng nhận tải
                </p>
            </div>
        </div>

        <!-- BẢNG ĐIỀU KHIỂN DEMO TRỰC QUAN -->
        <section class="bg-cardBg border border-cardBorder rounded-2xl p-6 shadow-xl space-y-4">
            <div class="border-b border-cardBorder pb-3 flex items-center justify-between flex-wrap gap-2">
                <div class="flex items-center gap-2">
                    <span class="text-amber-400 text-lg"><i class="fa-solid fa-gamepad"></i></span>
                    <h3 class="text-base font-bold text-white tracking-wide">
                        BẢNG ĐIỀU KHIỂN BẬT / TẮT & GIẢ LẬP SỰ CỐ (DEMO CONTROL PANEL)
                    </h3>
                </div>
                <span class="text-xs text-slate-400">Bấm các nút dưới đây để kiểm tra phản ứng của Naming Server & Client</span>
            </div>

            <div class="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2">
                <!-- NÚT 1: NGỪNG HEARTBEAT / TẮT NODE -->
                <button id="btn-crash" onclick="crashNode()" 
                        class="w-full py-4 px-6 rounded-2xl font-extrabold text-white text-sm sm:text-base bg-gradient-to-r from-rose-600 via-rose-700 to-red-800 hover:from-rose-500 hover:to-red-700 active:scale-[0.99] transition shadow-lg shadow-rose-900/40 flex items-center justify-center gap-3 border border-rose-500/40 cursor-pointer">
                    <i class="fa-solid fa-skull-crossbones text-xl"></i>
                    <span id="btn-crash-text">🛑 TẮT NODE (GIẢ LẬP SẬP)</span>
                </button>

                <!-- NÚT 2: KHỞI ĐỘNG LẠI / RE-BIND -->
                <button id="btn-recover" onclick="recoverNode()" 
                        class="w-full py-4 px-6 rounded-2xl font-extrabold text-white text-sm sm:text-base bg-gradient-to-r from-emerald-600 via-emerald-700 to-teal-800 hover:from-emerald-500 hover:to-teal-700 active:scale-[0.99] transition shadow-lg shadow-emerald-900/40 flex items-center justify-center gap-3 border border-emerald-500/40 cursor-pointer">
                    <i class="fa-solid fa-power-off text-xl"></i>
                    <span id="btn-recover-text">🟢 KHỞI ĐỘNG LẠI NODE (RE-BIND)</span>
                </button>
            </div>
        </section>

        <!-- Live Logs Panel -->
        <section class="bg-cardBg border border-cardBorder rounded-2xl shadow-xl overflow-hidden flex flex-col">
            <div class="px-6 py-3.5 border-b border-cardBorder flex items-center justify-between bg-slate-900/60">
                <div class="flex items-center space-x-3">
                    <span class="text-cyan-400 text-base"><i class="fa-solid fa-code"></i></span>
                    <h3 class="text-base font-bold text-white tracking-wide">
                        LIVE LOGS TẠI NODE {NODE_PORT}
                    </h3>
                    <span class="text-xs text-slate-400 hidden sm:inline">(Nhật ký xử lý Request & Nhịp tim Heartbeat)</span>
                </div>
                <div class="flex items-center gap-2">
                    <label class="inline-flex items-center text-xs text-slate-300 cursor-pointer">
                        <input type="checkbox" id="auto-scroll" checked class="form-checkbox text-emerald-500 rounded bg-slate-700 border-slate-600">
                        <span class="ml-1.5">Cuộn tự động</span>
                    </label>
                </div>
            </div>

            <!-- Terminal output -->
            <div id="logs-container" class="p-4 bg-slate-950 font-mono-code text-xs h-60 overflow-y-auto space-y-1.5 text-slate-300">
                <div class="text-slate-500 italic">Đang tải logs của node...</div>
            </div>
        </section>

    </main>

    <!-- Logic JS Polling -->
    <script>
        async function fetchNodeStatus() {{
            try {{
                const res = await fetch('/api/node-status');
                if (!res.ok) return;
                const data = await res.json();

                // Cập nhật Counter số to
                const counterEl = document.getElementById('request-counter');
                if (counterEl.innerText !== String(data.handled_requests_count)) {{
                    counterEl.innerText = data.handled_requests_count;
                    // Hiệu ứng nhảy số
                    counterEl.classList.add('scale-110');
                    setTimeout(() => counterEl.classList.remove('scale-110'), 250);
                }}

                // Cập nhật nhịp tim gần nhất
                if (data.last_heartbeat_seconds_ago !== null) {{
                    document.getElementById('last-hb-time').innerText = `${{data.last_heartbeat_seconds_ago}}s trước`;
                }} else {{
                    document.getElementById('last-hb-time').innerText = 'Chưa gửi';
                }}

                // Cập nhật UI theo trạng thái Sập / Sống
                updateUIForState(data.is_crashed);

                // Cập nhật Logs
                renderLogs(data.logs);

            }} catch (err) {{
                console.error("Lỗi fetch:", err);
            }}
        }}

        function updateUIForState(isCrashed) {{
            const header = document.getElementById('node-header');
            const iconBox = document.getElementById('node-icon-box');
            const topBadge = document.getElementById('badge-status-top');
            const banner = document.getElementById('crash-alert-banner');
            const healthText = document.getElementById('health-status-text');
            const healthDesc = document.getElementById('health-status-desc');
            const healthDot = document.getElementById('health-state-dot');
            const regBadge = document.getElementById('registry-status-badge');
            const regLabel = document.getElementById('registry-label');
            const btnCrash = document.getElementById('btn-crash');
            const btnCrashText = document.getElementById('btn-crash-text');
            const btnRecover = document.getElementById('btn-recover');
            const btnRecoverText = document.getElementById('btn-recover-text');

            if (isCrashed) {{
                // Giao diện SẬP: Viền đỏ rực
                header.className = "border-b-2 border-rose-500 bg-slate-900/90 backdrop-blur sticky top-0 z-50 transition-all duration-500 glow-rose";
                iconBox.className = "w-12 h-12 rounded-xl bg-rose-500/20 border border-rose-500/50 flex items-center justify-center text-rose-400 text-2xl shadow-lg";
                topBadge.className = "inline-flex items-center px-4 py-1.5 rounded-full text-xs font-bold bg-rose-500/20 text-rose-400 border border-rose-500/40";
                topBadge.innerHTML = `<span class="w-2.5 h-2.5 rounded-full bg-rose-400 mr-2 pulse-dot"></span> ĐANG GIẢ LẬP SẬP (CRASHED)`;

                banner.classList.remove('hidden');

                healthText.className = "text-2xl font-black text-rose-400 tracking-wide uppercase";
                healthText.innerText = "CRASHED / STOPPED";
                healthDesc.innerText = "Đã ngừng gửi Heartbeat & từ chối request (HTTP 503)";
                healthDot.className = "w-3 h-3 rounded-full bg-rose-500";

                regBadge.className = "px-2.5 py-0.5 rounded text-xs font-bold bg-rose-500/20 text-rose-300 border border-rose-500/30";
                regBadge.innerText = "ĐÃ NGỪNG GỬI";
                regLabel.innerText = "Đã ngắt Heartbeat";

                // Đổi trạng thái 2 nút điều khiển khi SẬP
                if (btnCrash) {{
                    btnCrash.className = "w-full py-4 px-6 rounded-2xl font-extrabold text-slate-400 text-sm sm:text-base bg-slate-800/80 border border-slate-700/60 opacity-60 cursor-not-allowed flex items-center justify-center gap-3 transition shadow-none";
                    if (btnCrashText) btnCrashText.innerText = "🛑 NODE ĐÃ TẮT (ĐANG SẬP)";
                }}
                if (btnRecover) {{
                    btnRecover.className = "w-full py-4 px-6 rounded-2xl font-extrabold text-white text-sm sm:text-base bg-gradient-to-r from-emerald-500 via-emerald-600 to-teal-600 hover:from-emerald-400 hover:to-teal-500 active:scale-[0.99] transition shadow-2xl shadow-emerald-500/40 flex items-center justify-center gap-3 border-2 border-emerald-400 ring-4 ring-emerald-500/30 animate-pulse cursor-pointer";
                    if (btnRecoverText) btnRecoverText.innerText = "🟢 BẬT LẠI NODE NGAY (RE-BIND)";
                }}
            }} else {{
                // Giao diện ONLINE: Viền xanh lá
                header.className = "border-b-2 border-emerald-500/80 bg-slate-900/90 backdrop-blur sticky top-0 z-50 transition-all duration-500";
                iconBox.className = "w-12 h-12 rounded-xl bg-emerald-500/20 border border-emerald-500/50 flex items-center justify-center text-emerald-400 text-2xl shadow-lg";
                topBadge.className = "inline-flex items-center px-4 py-1.5 rounded-full text-xs font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/40";
                topBadge.innerHTML = `<span class="w-2.5 h-2.5 rounded-full bg-emerald-400 mr-2 pulse-dot"></span> ONLINE & SẴN SÀNG`;

                banner.classList.add('hidden');

                healthText.className = "text-2xl font-black text-emerald-400 tracking-wide uppercase";
                healthText.innerText = "HEALTHY (ONLINE)";
                healthDesc.innerText = "Phát heartbeat mỗi 3 giây &bull; Sẵn sàng nhận tải";
                healthDot.className = "w-3 h-3 rounded-full bg-emerald-400 pulse-dot";

                regBadge.className = "px-2.5 py-0.5 rounded text-xs font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30";
                regBadge.innerText = "ĐÃ ĐĂNG KÝ";
                regLabel.innerText = "Đang phát nhịp tim (3s)";

                // Đổi trạng thái 2 nút điều khiển khi ONLINE
                if (btnCrash) {{
                    btnCrash.className = "w-full py-4 px-6 rounded-2xl font-extrabold text-white text-sm sm:text-base bg-gradient-to-r from-rose-600 via-rose-700 to-red-800 hover:from-rose-500 hover:to-red-700 active:scale-[0.99] transition shadow-lg shadow-rose-900/40 flex items-center justify-center gap-3 border border-rose-500/40 cursor-pointer";
                    if (btnCrashText) btnCrashText.innerText = "🛑 TẮT NODE (GIẢ LẬP SẬP)";
                }}
                if (btnRecover) {{
                    btnRecover.className = "w-full py-4 px-6 rounded-2xl font-extrabold text-emerald-300 text-sm sm:text-base bg-emerald-950/40 hover:bg-emerald-900/60 active:scale-[0.99] transition shadow-md border border-emerald-600/40 flex items-center justify-center gap-3 cursor-pointer";
                    if (btnRecoverText) btnRecoverText.innerText = "🟢 BẬT LẠI / TÁI ĐĂNG KÝ (RE-BIND)";
                }}
            }}
        }}

        function renderLogs(logs) {{
            const container = document.getElementById('logs-container');
            if (!logs || logs.length === 0) return;

            let html = '';
            logs.forEach(log => {{
                let badgeClass = 'text-slate-400 border-slate-700 bg-slate-800';
                let textClass = 'text-slate-300';

                if (log.type === 'INCOMING CALL') {{
                    badgeClass = 'text-emerald-300 border-emerald-800 bg-emerald-950/60 font-black';
                    textClass = 'text-emerald-300 font-semibold';
                }} else if (log.type === 'HEARTBEAT') {{
                    badgeClass = 'text-cyan-300 border-cyan-800 bg-cyan-950/60';
                    textClass = 'text-slate-300';
                }} else if (log.type === 'CRASH' || log.type === 'REJECTED') {{
                    badgeClass = 'text-rose-300 border-rose-800 bg-rose-950/60';
                    textClass = 'text-rose-300 font-bold';
                }} else if (log.type === 'RECOVER' || log.type === 'REGISTER') {{
                    badgeClass = 'text-amber-300 border-amber-800 bg-amber-950/60';
                    textClass = 'text-amber-200';
                }}

                html += `
                    <div class="leading-relaxed flex items-start gap-2 border-b border-slate-900/60 pb-1">
                        <span class="text-slate-500 select-none">[${{log.timestamp}}]</span>
                        <span class="px-1.5 py-0.2 rounded border text-[10px] font-bold ${{badgeClass}}">[${{log.type}}]</span>
                        <span class="${{textClass}} flex-1 break-all">${{log.message}}</span>
                    </div>
                `;
            }});
            container.innerHTML = html;

            if (document.getElementById('auto-scroll').checked) {{
                container.scrollTop = container.scrollHeight;
            }}
        }}

        async function crashNode() {{
            try {{
                const res = await fetch('/api/control/crash', {{ method: 'POST' }});
                if (res.ok) fetchNodeStatus();
            }} catch (e) {{
                alert("Lỗi: " + e);
            }}
        }}

        async function recoverNode() {{
            try {{
                const res = await fetch('/api/control/recover', {{ method: 'POST' }});
                if (res.ok) fetchNodeStatus();
            }} catch (e) {{
                alert("Lỗi: " + e);
            }}
        }}

        fetchNodeStatus();
        setInterval(fetchNodeStatus, 1000);
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Cluster Service Node")
    parser.add_argument("--port", type=int, default=5001, help="Port to listen on (default 5001)")
    parser.add_argument("--name", type=str, default="order-service", help="Service name (default order-service)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host IP (default 127.0.0.1)")
    parser.add_argument("--registry", type=str, default="http://127.0.0.1:4000", help="Naming Server URL")
    args = parser.parse_args()

    NODE_PORT = args.port
    SERVICE_NAME = args.name
    NODE_HOST = args.host
    REGISTRY_URL = args.registry

    print(f"🚀 Khởi chạy Service Node [{SERVICE_NAME}] tại http://{NODE_HOST}:{NODE_PORT}")
    print(f"📡 Naming Registry: {REGISTRY_URL}")
    uvicorn.run(app, host=NODE_HOST, port=NODE_PORT, log_level="warning")
