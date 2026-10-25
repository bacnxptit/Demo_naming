"""
NAMING SERVER (SERVICE REGISTRY & HEALTH CHECK) - PORT 4000
Hệ thống Đặt tên & Phân giải Dịch vụ Phân tán (Distributed Naming Service)
"""

import sys
import time
import asyncio
from datetime import datetime
from typing import Dict, List, Optional
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import requests
import uvicorn

# UTF-8 support on Windows
if sys.platform.startswith("win"):
    import io
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

app = FastAPI(title="Naming Server Registry", description="Distributed Service Registry and Health Checker")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==============================================================================
# IN-MEMORY REGISTRY & LOGS
# ==============================================================================

# Node structure:
# key: f"{ip}:{port}" -> {
#   "service_name": str,
#   "ip": str,
#   "port": int,
#   "registered_at": float,
#   "last_seen": float,
#   "status": "HEALTHY" | "TIMEOUT"
# }
registry: Dict[str, dict] = {}
timeout_seconds: float = 6.0
logs: List[dict] = []
MAX_LOGS = 150

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
# DATA MODELS
# ==============================================================================

class RegisterRequest(BaseModel):
    service_name: str
    ip: str
    port: int

class HeartbeatRequest(BaseModel):
    service_name: Optional[str] = "order-service"
    ip: str
    port: int

class UnbindRequest(BaseModel):
    ip: str
    port: int

class NodeActionRequest(BaseModel):
    ip: str
    port: int

class TimeoutConfigRequest(BaseModel):
    timeout_seconds: float

# ==============================================================================
# BACKGROUND TASK: HEALTH MONITOR & TIMEOUT DETECTION
# ==============================================================================

async def health_monitor_task():
    """Kiểm tra nhịp tim mỗi 1 giây. Nếu now - last_seen > timeout_seconds thì đánh dấu TIMEOUT/DEAD"""
    while True:
        try:
            await asyncio.sleep(1.0)
            now = time.time()
            for key, node in list(registry.items()):
                elapsed = now - node["last_seen"]
                if elapsed > timeout_seconds and node["status"] == "HEALTHY":
                    node["status"] = "TIMEOUT"
                    add_log(
                        "TIMEOUT",
                        f"Node {node['ip']}:{node['port']} ({node['service_name']}) quá hạn nhịp tim ({elapsed:.1f}s > {timeout_seconds}s) -> Đánh dấu TIMEOUT/DEAD",
                        level="WARNING"
                    )
        except Exception as e:
            print(f"Error in health monitor: {e}")

@app.on_event("startup")
async def startup_event():
    add_log("SYSTEM", "Naming Server khởi động thành công trên cổng 4000")
    asyncio.create_task(health_monitor_task())

# ==============================================================================
# BACKEND APIS
# ==============================================================================

@app.post("/api/register")
def register_service(req: RegisterRequest):
    """
    POST /api/register: Nhận { 'service_name': 'order-service', 'ip': '127.0.0.1', 'port': 5001 }.
    Lưu vào bộ nhớ và gán trạng thái HEALTHY.
    """
    key = f"{req.ip}:{req.port}"
    now = time.time()
    is_new = key not in registry

    registry[key] = {
        "service_name": req.service_name,
        "ip": req.ip,
        "port": req.port,
        "registered_at": now if is_new else registry[key]["registered_at"],
        "last_seen": now,
        "status": "HEALTHY"
    }

    action_text = "Đăng ký mới thành công" if is_new else "Đăng ký lại (Re-bind)"
    add_log("REGISTER", f"{action_text}: Node {req.ip}:{req.port} cho dịch vụ '{req.service_name}'", level="SUCCESS")

    return {
        "status": "SUCCESS",
        "message": f"{action_text} node {key}",
        "node": registry[key]
    }

@app.post("/api/heartbeat")
def receive_heartbeat(req: HeartbeatRequest):
    """
    POST /api/heartbeat: Cập nhật last_seen = now() cho ip:port tương ứng.
    """
    key = f"{req.ip}:{req.port}"
    now = time.time()

    if key in registry:
        prev_status = registry[key]["status"]
        registry[key]["last_seen"] = now
        registry[key]["status"] = "HEALTHY"
        if prev_status == "TIMEOUT":
            add_log("HEARTBEAT", f"Node {key} đã phục hồi (HEALTHY trở lại) sau khi nhận nhịp tim", level="SUCCESS")
        else:
            add_log("HEARTBEAT", f"Nhận nhịp tim từ {key} ({registry[key]['service_name']})", level="INFO")
        return {"status": "SUCCESS", "message": "Heartbeat updated", "last_seen": now}
    else:
        # Tự động đăng ký nếu chưa có
        registry[key] = {
            "service_name": req.service_name or "order-service",
            "ip": req.ip,
            "port": req.port,
            "registered_at": now,
            "last_seen": now,
            "status": "HEALTHY"
        }
        add_log("REGISTER", f"Tự động đăng ký qua Heartbeat: {key}", level="SUCCESS")
        return {"status": "SUCCESS", "message": "Registered via heartbeat", "node": registry[key]}

@app.get("/api/lookup")
def lookup_service(name: str = Query(..., description="Tên dịch vụ cần tra cứu, ví dụ: order-service")):
    """
    GET /api/lookup?name=order-service: Trả về danh sách các node đang HEALTHY của dịch vụ đó.
    """
    now = time.time()
    healthy_nodes = []

    for node in registry.values():
        if node["service_name"] == name:
            elapsed = now - node["last_seen"]
            # Chỉ trả về node nếu status là HEALTHY và chưa quá hạn timeout
            if node["status"] == "HEALTHY" and elapsed <= timeout_seconds:
                healthy_nodes.append({
                    "service_name": node["service_name"],
                    "ip": node["ip"],
                    "port": node["port"],
                    "status": node["status"],
                    "last_seen_seconds_ago": round(elapsed, 1)
                })

    healthy_node_ips = [f"{n['ip']}:{n['port']}" for n in healthy_nodes]
    add_log("LOOKUP", f"Client tra cứu '{name}' -> Tìm thấy {len(healthy_nodes)} node HEALTHY: {healthy_node_ips}", level="INFO")
    return healthy_nodes

@app.post("/api/unbind")
def unbind_service(req: UnbindRequest):
    """
    Xóa thủ công một node khỏi danh bạ
    """
    key = f"{req.ip}:{req.port}"
    if key in registry:
        removed = registry.pop(key)
        add_log("UNBIND", f"Xóa thủ công (Unbind) Node {key} ({removed['service_name']})", level="WARNING")
        return {"status": "SUCCESS", "message": f"Unbound node {key}"}
    return {"status": "ERROR", "message": "Node not found"}

@app.post("/api/node/restart")
def restart_node_proxy(req: NodeActionRequest):
    """
    Gửi lệnh khởi động lại tới Service Node qua cổng của node đó
    """
    try:
        res = requests.post(f"http://{req.ip}:{req.port}/api/control/recover", timeout=3.0)
        if res.status_code == 200:
            add_log("RECOVER", f"Đã gửi lệnh bật lại Node {req.ip}:{req.port} thành công", level="SUCCESS")
            key = f"{req.ip}:{req.port}"
            if key in registry:
                registry[key]["status"] = "HEALTHY"
                registry[key]["last_seen"] = time.time()
            return {"status": "SUCCESS", "message": f"Node {req.ip}:{req.port} đã được khởi động lại thành công!"}
        else:
            add_log("RECOVER", f"Gửi lệnh bật Node {req.ip}:{req.port} nhưng nhận lỗi {res.status_code}", level="WARNING")
            return JSONResponse(status_code=502, content={"status": "ERROR", "message": f"Node trả về status {res.status_code}"})
    except Exception as e:
        add_log("RECOVER", f"Không thể kết nối tới Node {req.ip}:{req.port} để bật lại: {e}", level="ERROR")
        return JSONResponse(status_code=502, content={"status": "ERROR", "message": f"Không thể kết nối tới Node (tiến trình có thể chưa chạy): {e}"})

@app.post("/api/config/timeout")
def set_timeout_config(req: TimeoutConfigRequest):
    """
    Cập nhật thời gian timeout (giây)
    """
    global timeout_seconds
    if req.timeout_seconds < 1.0:
        raise HTTPException(status_code=400, detail="Timeout must be at least 1 second")
    old_timeout = timeout_seconds
    timeout_seconds = req.timeout_seconds
    add_log("CONFIG", f"Thay đổi cấu hình Timeout: {old_timeout}s -> {timeout_seconds}s", level="INFO")
    return {"status": "SUCCESS", "timeout_seconds": timeout_seconds}

@app.get("/api/status")
def get_status():
    """
    Trả về toàn bộ bảng registry, danh sách logs và cấu hình cho UI polling
    """
    now = time.time()
    nodes_list = []
    healthy_count = 0
    timeout_count = 0

    for node in registry.values():
        elapsed = now - node["last_seen"]
        is_healthy = node["status"] == "HEALTHY" and elapsed <= timeout_seconds
        current_status = "HEALTHY" if is_healthy else "TIMEOUT"
        
        if current_status == "HEALTHY":
            healthy_count += 1
        else:
            timeout_count += 1

        nodes_list.append({
            "service_name": node["service_name"],
            "ip": node["ip"],
            "port": node["port"],
            "last_seen_seconds_ago": round(elapsed, 1),
            "status": current_status,
            "registered_at": node["registered_at"]
        })

    # Sắp xếp theo tên dịch vụ rồi port
    nodes_list.sort(key=lambda x: (x["service_name"], x["port"]))

    return {
        "nodes": nodes_list,
        "timeout_seconds": timeout_seconds,
        "logs": logs[-40:],  # 40 logs gần nhất cho UI
        "stats": {
            "total_nodes": len(nodes_list),
            "healthy_nodes": healthy_count,
            "timeout_nodes": timeout_count
        }
    }

@app.post("/api/logs/clear")
def clear_logs():
    logs.clear()
    add_log("SYSTEM", "Đã xóa lịch sử log")
    return {"status": "SUCCESS"}

# ==============================================================================
# WEB DASHBOARD (http://localhost:4000)
# ==============================================================================

@app.get("/", response_class=HTMLResponse)
def index_html():
    return """<!DOCTYPE html>
<html lang="vi" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NAMING SERVER</title>
    <!-- TailwindCSS CDN -->
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    colors: {
                        darkBg: '#0b1120',
                        cardBg: '#1e293b',
                        cardBorder: '#334155',
                    }
                }
            }
        }
    </script>
    <!-- Font Awesome -->
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <!-- Google Fonts -->
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        body {
            font-family: 'Inter', sans-serif;
        }
        .font-mono-code {
            font-family: 'JetBrains Mono', monospace;
        }
        .glow-cyan {
            box-shadow: 0 0 25px -5px rgba(6, 182, 212, 0.35);
        }
        .pulse-dot {
            animation: pulseAnimation 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
        }
        @keyframes pulseAnimation {
            0%, 100% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.4; transform: scale(1.15); }
        }
        /* Tùy chỉnh thanh cuộn */
        ::-webkit-scrollbar {
            width: 8px;
            height: 8px;
        }
        ::-webkit-scrollbar-track {
            background: #0f172a;
        }
        ::-webkit-scrollbar-thumb {
            background: #334155;
            border-radius: 4px;
        }
        ::-webkit-scrollbar-thumb:hover {
            background: #475569;
        }
    </style>
</head>
<body class="bg-darkBg text-slate-100 min-h-screen flex flex-col antialiased">

    <!-- Top Navigation / Header -->
    <header class="border-b border-cardBorder bg-slate-900/90 backdrop-blur sticky top-0 z-50">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 flex flex-wrap items-center justify-between gap-4">
            <div class="flex items-center space-x-4">
                <div class="w-12 h-12 rounded-xl bg-cyan-500/20 border border-cyan-500/40 flex items-center justify-center text-cyan-400 text-2xl shadow-lg shadow-cyan-500/20">
                    🧭
                </div>
                <div>
                    <h1 class="text-2xl sm:text-3xl font-extrabold tracking-tight text-white flex items-center gap-3">
                        NAMING SERVER
                    </h1>
                   
                </div>
            </div>
            
            <div class="flex items-center gap-3">
                <span class="inline-flex items-center px-3 py-1.5 rounded-full text-xs font-semibold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                    <span class="w-2 h-2 rounded-full bg-emerald-400 mr-2 pulse-dot"></span>
                    HỆ THỐNG ĐANG HOẠT ĐỘNG
                </span>
                <span class="text-xs text-slate-400 bg-slate-800 px-3 py-1.5 rounded-lg border border-slate-700 font-mono-code" id="clock-display">
                    --:--:--
                </span>
            </div>
        </div>
    </header>

    <!-- Main Content Container -->
    <main class="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">

        <!-- Top Stat Cards (3 thẻ, mặc định timeout 6s) -->
        <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <!-- Card 1 -->
            <div class="bg-cardBg border border-cardBorder rounded-2xl p-4 flex items-center justify-between shadow-lg">
                <div>
                    <p class="text-xs font-medium text-slate-400 uppercase tracking-wider">Tổng số Node</p>
                    <p class="text-3xl font-extrabold text-white mt-1" id="stat-total">0</p>
                </div>
                <div class="w-12 h-12 rounded-xl bg-blue-500/10 text-blue-400 border border-blue-500/20 flex items-center justify-center text-xl">
                    <i class="fa-solid fa-server"></i>
                </div>
            </div>

            <!-- Card 2 -->
            <div class="bg-cardBg border border-cardBorder rounded-2xl p-4 flex items-center justify-between shadow-lg">
                <div>
                    <p class="text-xs font-medium text-emerald-400 uppercase tracking-wider">Node Đang Sống</p>
                    <p class="text-3xl font-extrabold text-emerald-400 mt-1" id="stat-healthy">0</p>
                </div>
                <div class="w-12 h-12 rounded-xl bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center justify-center text-xl">
                    <i class="fa-solid fa-heart-pulse"></i>
                </div>
            </div>

            <!-- Card 3 -->
            <div class="bg-cardBg border border-cardBorder rounded-2xl p-4 flex items-center justify-between shadow-lg">
                <div>
                    <p class="text-xs font-medium text-rose-400 uppercase tracking-wider">Node Quá Hạn (> 6s)</p>
                    <p class="text-3xl font-extrabold text-rose-400 mt-1" id="stat-timeout">0</p>
                </div>
                <div class="w-12 h-12 rounded-xl bg-rose-500/10 text-rose-400 border border-rose-500/20 flex items-center justify-center text-xl">
                    <i class="fa-solid fa-triangle-exclamation"></i>
                </div>
            </div>
        </div>

        <!-- Main Section: Bảng Naming Table -->
        <section class="bg-cardBg border border-cardBorder rounded-2xl shadow-xl overflow-hidden">
            <div class="px-6 py-4 border-b border-cardBorder flex flex-wrap items-center justify-between gap-3 bg-slate-800/40">
                <div class="flex items-center space-x-3">
                    <span class="text-cyan-400 text-lg"><i class="fa-solid fa-address-book"></i></span>
                    <h2 class="text-lg font-bold text-white tracking-wide">
                        BẢNG DANH BẠ DỊCH VỤ (NAMING TABLE)
                    </h2>
                    <span class="text-xs bg-slate-700 text-slate-300 px-2 py-0.5 rounded-full font-mono-code" id="table-count-badge">
                        0 node
                    </span>
                </div>
                <div class="flex items-center gap-2">
                    <span class="text-xs text-slate-400 flex items-center gap-1.5">
                        <span class="inline-block w-2 h-2 rounded-full bg-cyan-400 pulse-dot"></span>
                        Tự động làm mới mỗi 1s
                    </span>
                </div>
            </div>

            <!-- Table Container -->
            <div class="overflow-x-auto">
                <table class="w-full text-left border-collapse">
                    <thead>
                        <tr class="border-b border-slate-700 bg-slate-900/60 text-xs font-bold uppercase tracking-wider text-slate-400">
                            <th class="py-3.5 px-6">Tên Dịch Vụ (Service Name)</th>
                            <th class="py-3.5 px-6">Địa Chỉ Vật Lý (IP:Port)</th>
                            <th class="py-3.5 px-6">Link Mở Nhanh</th>
                            <th class="py-3.5 px-6">Nhịp Tim Cuối (Heartbeat)</th>
                            <th class="py-3.5 px-6">Trạng Thái</th>
                            <th class="py-3.5 px-6 text-center">Thao Tác</th>
                        </tr>
                    </thead>
                    <tbody id="nodes-table-body" class="divide-y divide-slate-800 text-sm">
                        <!-- Table rows will be rendered here dynamically -->
                        <tr>
                            <td colspan="6" class="py-8 text-center text-slate-500 font-medium">
                                <i class="fa-solid fa-circle-notch fa-spin text-2xl text-cyan-400 mb-2 block"></i>
                                Đang tải danh sách dịch vụ từ Naming Registry...
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </section>

        <!-- Live Logs Panel -->
        <section class="bg-cardBg border border-cardBorder rounded-2xl shadow-xl overflow-hidden flex flex-col">
            <div class="px-6 py-3.5 border-b border-cardBorder flex items-center justify-between bg-slate-800/40">
                <div class="flex items-center space-x-3">
                    <span class="text-emerald-400 text-base"><i class="fa-solid fa-terminal"></i></span>
                    <h3 class="text-base font-bold text-white tracking-wide">
                        KHUNG NHẬT KÝ THỜI GIAN THỰC (LIVE LOGS)
                    </h3>
                    <span class="text-xs text-slate-400 hidden sm:inline">([REGISTER], [HEARTBEAT], [LOOKUP], [TIMEOUT])</span>
                </div>
                <div class="flex items-center gap-2">
                    <button onclick="clearLogs()" class="px-3 py-1 text-xs font-medium bg-slate-700 hover:bg-slate-600 text-slate-200 rounded-lg transition border border-slate-600 flex items-center gap-1.5">
                        <i class="fa-regular fa-trash-can"></i> Xóa Logs
                    </button>
                    <label class="inline-flex items-center text-xs text-slate-300 cursor-pointer ml-2">
                        <input type="checkbox" id="auto-scroll" checked class="form-checkbox text-cyan-500 rounded bg-slate-700 border-slate-600">
                        <span class="ml-1.5">Cuộn tự động</span>
                    </label>
                </div>
            </div>

            <!-- Terminal log output -->
            <div id="logs-container" class="p-4 bg-slate-950 font-mono-code text-xs h-64 overflow-y-auto space-y-1.5 text-slate-300">
                <div class="text-slate-500 italic">Đang kết nối luồng sự kiện...</div>
            </div>
        </section>

    </main>

    

    <!-- Client-side Logic (Vanilla JS Polling) -->
    <script>
        let timeoutVal = 6;
        let isUpdatingTimeout = false;

        function updateClock() {
            const now = new Date();
            document.getElementById('clock-display').innerText = now.toLocaleTimeString();
        }
        setInterval(updateClock, 1000);
        updateClock();

        async function fetchStatus() {
            try {
                const res = await fetch('/api/status');
                if (!res.ok) return;
                const data = await res.json();
                
                // Cập nhật thống kê
                document.getElementById('stat-total').innerText = data.stats.total_nodes;
                document.getElementById('stat-healthy').innerText = data.stats.healthy_nodes;
                document.getElementById('stat-timeout').innerText = data.stats.timeout_nodes;
                document.getElementById('table-count-badge').innerText = `${data.stats.total_nodes} node`;
                
                timeoutVal = data.timeout_seconds || 6;

                // Cập nhật bảng Naming Table
                renderTable(data.nodes);

                // Cập nhật Logs
                renderLogs(data.logs);

            } catch (err) {
                console.error("Lỗi khi fetch status:", err);
            }
        }

        function renderTable(nodes) {
            const tbody = document.getElementById('nodes-table-body');
            if (!nodes || nodes.length === 0) {
                tbody.innerHTML = `
                    <tr>
                        <td colspan="6" class="py-10 text-center text-slate-400">
                            <div class="text-4xl mb-2 opacity-40">📭</div>
                            <p class="font-medium text-base">Chưa có Service Node nào đăng ký vào Danh bạ</p>
                            <p class="text-xs text-slate-500 mt-1">Hãy khởi động Service Node trên cổng 5001, 5002 bằng lệnh: <span class="font-mono-code text-cyan-400">python service_node.py --port 5001</span></p>
                        </td>
                    </tr>
                `;
                return;
            }

            let html = '';
            nodes.forEach(node => {
                const isHealthy = node.status === 'HEALTHY';
                const statusBadge = isHealthy
                    ? `<span class="inline-flex items-center px-3 py-1 rounded-full text-xs font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/40">
                         <span class="w-2 h-2 rounded-full bg-emerald-400 mr-2 pulse-dot"></span>
                         HEALTHY
                       </span>`
                    : `<span class="inline-flex items-center px-3 py-1 rounded-full text-xs font-bold bg-rose-500/20 text-rose-400 border border-rose-500/40">
                         <span class="w-2 h-2 rounded-full bg-rose-400 mr-2"></span>
                         TIMEOUT (DEAD)
                       </span>`;

                const elapsedText = isHealthy 
                    ? `<span class="text-emerald-400 font-bold font-mono-code">${node.last_seen_seconds_ago}s</span> trước`
                    : `<span class="text-rose-400 font-bold font-mono-code">${node.last_seen_seconds_ago}s</span> trước (> ${timeoutVal}s)`;

                const quickLink = `http://${node.ip}:${node.port}`;

                html += `
                    <tr class="hover:bg-slate-800/60 transition-colors">
                        <td class="py-3.5 px-6 font-semibold text-white">
                            <div class="flex items-center gap-2">
                                <span class="text-cyan-400"><i class="fa-solid fa-cube"></i></span>
                                <span>${node.service_name}</span>
                            </div>
                        </td>
                        <td class="py-3.5 px-6 font-mono-code font-bold text-slate-200">
                            ${node.ip}:${node.port}
                        </td>
                        <td class="py-3.5 px-6">
                            <a href="${quickLink}" target="_blank" 
                               class="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-lg bg-slate-700 hover:bg-cyan-600 text-cyan-300 hover:text-white transition">
                                <i class="fa-solid fa-arrow-up-right-from-square text-[10px]"></i>
                                <span>Mở Node UI</span>
                            </a>
                        </td>
                        <td class="py-3.5 px-6 text-sm">
                            ${elapsedText}
                        </td>
                        <td class="py-3.5 px-6">
                            ${statusBadge}
                        </td>
                        <td class="py-3.5 px-6 text-center">
                            <div class="inline-flex items-center gap-1.5 justify-center">
                                ${!isHealthy ? `
                                <button onclick="restartNode('${node.ip}', ${node.port})" 
                                        title="Bật lại node này và kích hoạt gửi lại heartbeat"
                                        class="px-2.5 py-1 text-xs font-bold bg-emerald-500/20 hover:bg-emerald-600 text-emerald-300 hover:text-white rounded-lg border border-emerald-500/40 transition shadow-sm inline-flex items-center gap-1 animate-pulse cursor-pointer">
                                    <i class="fa-solid fa-power-off"></i> Khởi động lại
                                </button>
                                ` : `
                                <button onclick="restartNode('${node.ip}', ${node.port})" 
                                        title="Khởi động lại / Tái đăng ký Node"
                                        class="px-2 py-1 text-xs font-medium bg-slate-700/60 hover:bg-emerald-700 text-slate-300 hover:text-white rounded-lg border border-slate-600 transition inline-flex items-center gap-1 cursor-pointer">
                                    <i class="fa-solid fa-rotate text-[10px]"></i> Re-bind
                                </button>
                                `}
                                <button onclick="unbindNode('${node.ip}', ${node.port})" 
                                        title="Xóa node khỏi danh bạ"
                                        class="px-2.5 py-1 text-xs font-semibold bg-rose-500/10 hover:bg-rose-500 text-rose-400 hover:text-white rounded-lg border border-rose-500/30 transition shadow-sm cursor-pointer">
                                    <i class="fa-solid fa-ban mr-1"></i> Xóa
                                </button>
                            </div>
                        </td>
                    </tr>
                `;
            });
            tbody.innerHTML = html;
        }

        function renderLogs(logs) {
            const container = document.getElementById('logs-container');
            if (!logs || logs.length === 0) return;

            let html = '';
            logs.forEach(log => {
                let badgeClass = 'text-slate-400 border-slate-700 bg-slate-800';
                let textClass = 'text-slate-300';

                if (log.type === 'REGISTER') {
                    badgeClass = 'text-cyan-300 border-cyan-800 bg-cyan-950/60';
                    textClass = 'text-cyan-200';
                } else if (log.type === 'HEARTBEAT') {
                    badgeClass = 'text-emerald-300 border-emerald-800 bg-emerald-950/60';
                    textClass = 'text-emerald-200/90';
                } else if (log.type === 'LOOKUP') {
                    badgeClass = 'text-amber-300 border-amber-800 bg-amber-950/60';
                    textClass = 'text-amber-200';
                } else if (log.type === 'TIMEOUT' || log.type === 'UNBIND') {
                    badgeClass = 'text-rose-300 border-rose-800 bg-rose-950/60';
                    textClass = 'text-rose-200';
                }

                html += `
                    <div class="leading-relaxed flex items-start gap-2 border-b border-slate-900/60 pb-1">
                        <span class="text-slate-500 select-none">[${log.timestamp}]</span>
                        <span class="px-1.5 py-0.2 rounded border text-[10px] font-bold ${badgeClass}">[${log.type}]</span>
                        <span class="${textClass} flex-1 break-all">${log.message}</span>
                    </div>
                `;
            });
            container.innerHTML = html;

            if (document.getElementById('auto-scroll').checked) {
                container.scrollTop = container.scrollHeight;
            }
        }

        async function restartNode(ip, port) {
            try {
                const res = await fetch('/api/node/restart', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ip, port })
                });
                const data = await res.json();
                if (res.ok) {
                    fetchStatus();
                } else {
                    alert("Lỗi khi khởi động lại node: " + (data.message || "Không thể kết nối"));
                }
            } catch (err) {
                alert("Lỗi kết nối tới Naming Server: " + err);
            }
        }

        async function unbindNode(ip, port) {
            if (!confirm(`Bạn có chắc muốn xóa Node ${ip}:${port} khỏi Naming Registry?`)) return;
            try {
                const res = await fetch('/api/unbind', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ip, port })
                });
                if (res.ok) {
                    fetchStatus();
                }
            } catch (err) {
                alert("Lỗi khi xóa node: " + err);
            }
        }

        async function onTimeoutChange(val) {
            isUpdatingTimeout = true;
            document.getElementById('stat-timeout-value').innerText = `${val}s`;
            try {
                await fetch('/api/config/timeout', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ timeout_seconds: parseFloat(val) })
                });
            } catch (e) {
                console.error(e);
            } finally {
                setTimeout(() => { isUpdatingTimeout = false; }, 500);
            }
        }

        async function clearLogs() {
            await fetch('/api/logs/clear', { method: 'POST' });
            fetchStatus();
        }

        // Khởi chạy polling đều đặn mỗi 1s
        fetchStatus();
        setInterval(fetchStatus, 1000);
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Distributed Naming Server")
    parser.add_argument("--port", type=int, default=4000, help="Port to listen on (default 4000)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host interface (default 127.0.0.1)")
    args = parser.parse_args()

    print(f"🚀 Naming Server khởi động tại http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
