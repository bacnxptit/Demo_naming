"""
CLIENT DASHBOARD APPLICATION - PORT 3000
Ứng dụng Người Dùng Cuối (Client-side Discovery, Caching, Load Balancing & Failover)
"""

import sys
import time
import random
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

app = FastAPI(title="Client Dashboard Application", description="Client Discovery, Caching and Invocations")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==============================================================================
# CLIENT STATE & CACHE
# ==============================================================================

NAMING_SERVER_URL = "http://127.0.0.1:4000"
HARDCODED_TARGET = "http://127.0.0.1:5001"

request_history: List[dict] = []
request_counter: int = 0
round_robin_counter: int = 0

client_cache = {
    "service_name": "order-service",
    "nodes": [],
    "cached_at": None,
    "expires_at": None,
    "ttl": 10.0,
    "enabled": True
}

class SendRequestPayload(BaseModel):
    mode: str = "naming"          # "hardcode" | "naming"
    cache_enabled: bool = True
    load_balancing: str = "round_robin"  # "round_robin" | "random"
    service_name: str = "order-service"

# ==============================================================================
# BACKEND CLIENT APIS
# ==============================================================================

@app.post("/api/client/send-request")
def execute_client_request(payload: SendRequestPayload):
    """
    Thực thi quy trình gọi dịch vụ:
    - Chế độ Hard-code: Gọi thẳng 127.0.0.1:5001 (bỏ qua Naming Server)
    - Chế độ Naming Service:
        Bước 1: Tra cứu (Hỏi Naming Server hoặc đọc Local Cache)
        Bước 2: Cân bằng tải & Gọi trực tiếp vào Service Node được chọn
    """
    global request_counter, round_robin_counter, client_cache
    request_counter += 1
    req_id = request_counter
    req_time = datetime.now().strftime("%H:%M:%S")

    start_total_time = time.time()

    # ==========================================
    # TRƯỜNG HỢP 1: HARD-CODED IP
    # ==========================================
    if payload.mode == "hardcode":
        step1_info = {
            "title": "Bước 1: Tra cứu Naming Server",
            "status": "SKIPPED",
            "source": "Hard-coded IP (Bỏ qua Naming Server)",
            "message": "Không hỏi Naming Server (Port 4000), gọi trực tiếp IP cứng 127.0.0.1:5001",
            "nodes_found": [{"ip": "127.0.0.1", "port": 5001}]
        }

        # Gọi thẳng 127.0.0.1:5001
        target_url = f"{HARDCODED_TARGET}/api/process"
        call_start = time.time()
        try:
            res = requests.get(target_url, timeout=2.5)
            call_latency = round((time.time() - call_start) * 1000)
            
            if res.status_code == 200:
                data = res.json()
                step2_info = {
                    "title": "Bước 2: Gọi trực tiếp Service Node",
                    "status": "SUCCESS",
                    "target": "127.0.0.1:5001",
                    "http_status": 200,
                    "response": data,
                    "latency_ms": call_latency,
                    "message": f"Thành công! Xử lý bởi: {data.get('handled_by', 'Node 5001')}"
                }
                success = True
            else:
                data = res.json() if res.headers.get("content-type") == "application/json" else {"message": res.text}
                step2_info = {
                    "title": "Bước 2: Gọi trực tiếp Service Node",
                    "status": "ERROR",
                    "target": "127.0.0.1:5001",
                    "http_status": res.status_code,
                    "response": data,
                    "latency_ms": call_latency,
                    "message": f"Lỗi HTTP {res.status_code} - Node đang sập hoặc từ chối xử lý!"
                }
                success = False

        except Exception as e:
            call_latency = round((time.time() - call_start) * 1000)
            step2_info = {
                "title": "Bước 2: Gọi trực tiếp Service Node",
                "status": "ERROR",
                "target": "127.0.0.1:5001",
                "http_status": 503,
                "response": {"error": str(e)},
                "latency_ms": call_latency,
                "message": f"Mất kết nối tới 127.0.0.1:5001 (Node đã chết hoặc cổng bị đóng)!"
            }
            success = False

        total_latency = round((time.time() - start_total_time) * 1000)
        history_item = {
            "id": req_id,
            "time": req_time,
            "mode": "Hard-code IP",
            "source": "Hard-code (Cố định)",
            "target": "127.0.0.1:5001",
            "http_status": step2_info["http_status"],
            "success": success,
            "latency_ms": total_latency,
            "detail": step2_info["message"]
        }
        request_history.insert(0, history_item)

        return {
            "request_id": req_id,
            "mode": "hardcode",
            "success": success,
            "step1": step1_info,
            "step2": step2_info,
            "total_latency_ms": total_latency
        }

    # ==========================================
    # TRƯỜNG HỢP 2: DÙNG NAMING SERVICE
    # ==========================================
    now = time.time()
    source_name = "Naming Server"
    healthy_nodes = []
    from_cache = False

    # Kiểm tra Local Cache nếu được bật
    client_cache["enabled"] = payload.cache_enabled
    if payload.cache_enabled and client_cache["nodes"] and client_cache["expires_at"] and now < client_cache["expires_at"]:
        healthy_nodes = client_cache["nodes"]
        source_name = "Client Cache"
        from_cache = True
        ttl_left = round(client_cache["expires_at"] - now, 1)
        step1_info = {
            "title": "Bước 1: Tra cứu (Lookup)",
            "status": "SUCCESS",
            "source": f"Client Cache (TTL còn {ttl_left}s)",
            "from_cache": True,
            "message": f"Cache HIT! Lấy từ bộ nhớ đệm ({len(healthy_nodes)} node)",
            "nodes_found": healthy_nodes
        }
    else:
        # Gọi Naming Server hỏi danh bạ
        try:
            lookup_url = f"{NAMING_SERVER_URL}/api/lookup?name={payload.service_name}"
            res = requests.get(lookup_url, timeout=2.5)
            if res.status_code == 200:
                healthy_nodes = res.json()
                source_name = "Naming Server"
                # Cập nhật Local Cache nếu cache_enabled
                if payload.cache_enabled:
                    client_cache["nodes"] = healthy_nodes
                    client_cache["cached_at"] = now
                    client_cache["expires_at"] = now + client_cache["ttl"]
                
                step1_info = {
                    "title": "Bước 1: Tra cứu (Lookup)",
                    "status": "SUCCESS",
                    "source": "Naming Server (Port 4000)",
                    "from_cache": False,
                    "message": f"Hỏi Naming Server thành công! Tìm thấy {len(healthy_nodes)} node HEALTHY",
                    "nodes_found": healthy_nodes
                }
            else:
                step1_info = {
                    "title": "Bước 1: Tra cứu (Lookup)",
                    "status": "ERROR",
                    "source": "Naming Server (Port 4000)",
                    "from_cache": False,
                    "message": f"Naming Server trả về mã lỗi: {res.status_code}",
                    "nodes_found": []
                }
        except Exception as e:
            step1_info = {
                "title": "Bước 1: Tra cứu (Lookup)",
                "status": "ERROR",
                "source": "Naming Server (Port 4000)",
                "from_cache": False,
                "message": f"Không thể kết nối Naming Server tại {NAMING_SERVER_URL}: {e}",
                "nodes_found": []
            }

    # Nếu không tìm thấy node nào sống
    if not healthy_nodes:
        total_latency = round((time.time() - start_total_time) * 1000)
        step2_info = {
            "title": "Bước 2: Gọi trực tiếp Service Node",
            "status": "ERROR",
            "target": "Không có node khả dụng",
            "http_status": 503,
            "response": {"error": "Không có node nào của dịch vụ đang HEALTHY trong danh bạ"},
            "latency_ms": 0,
            "message": "Không thể gọi dịch vụ vì toàn bộ các Node đều đã sập (DEAD/TIMEOUT)!"
        }
        history_item = {
            "id": req_id,
            "time": req_time,
            "mode": "Naming Service",
            "source": source_name,
            "target": "None",
            "http_status": 503,
            "success": False,
            "latency_ms": total_latency,
            "detail": "Không có Node HEALTHY nào trong danh bạ"
        }
        request_history.insert(0, history_item)

        return {
            "request_id": req_id,
            "mode": "naming",
            "success": False,
            "step1": step1_info,
            "step2": step2_info,
            "total_latency_ms": total_latency
        }

    # ==========================================
    # BƯỚC 2: CHỌN NODE & GỌI TRỰC TIẾP
    # ==========================================
    if payload.load_balancing == "random":
        chosen_node = random.choice(healthy_nodes)
        algo_text = "Random"
    else:
        # Round-Robin
        chosen_node = healthy_nodes[round_robin_counter % len(healthy_nodes)]
        round_robin_counter += 1
        algo_text = "Round-Robin"

    target_host_port = f"{chosen_node['ip']}:{chosen_node['port']}"
    node_url = f"http://{target_host_port}/api/process"

    call_start = time.time()
    try:
        res = requests.get(node_url, timeout=2.5)
        call_latency = round((time.time() - call_start) * 1000)
        
        if res.status_code == 200:
            data = res.json()
            step2_info = {
                "title": "Bước 2: Gọi trực tiếp Service Node",
                "status": "SUCCESS",
                "target": target_host_port,
                "http_status": 200,
                "algorithm": algo_text,
                "response": data,
                "latency_ms": call_latency,
                "message": f"Thành công! [{algo_text}] Xử lý bởi: {data.get('handled_by', target_host_port)}"
            }
            success = True
        else:
            data = res.json() if res.headers.get("content-type") == "application/json" else {"message": res.text}
            step2_info = {
                "title": "Bước 2: Gọi trực tiếp Service Node",
                "status": "ERROR",
                "target": target_host_port,
                "http_status": res.status_code,
                "algorithm": algo_text,
                "response": data,
                "latency_ms": call_latency,
                "message": f"Lỗi {res.status_code}: Node {target_host_port} từ chối phục vụ (đang sập)!"
            }
            success = False

    except Exception as e:
        call_latency = round((time.time() - call_start) * 1000)
        step2_info = {
            "title": "Bước 2: Gọi trực tiếp Service Node",
            "status": "ERROR",
            "target": target_host_port,
            "http_status": 503,
            "algorithm": algo_text,
            "response": {"error": str(e)},
            "latency_ms": call_latency,
            "message": f"Mất kết nối tới {target_host_port}: {e}"
        }
        success = False

    total_latency = round((time.time() - start_total_time) * 1000)
    history_item = {
        "id": req_id,
        "time": req_time,
        "mode": "Naming Service",
        "source": source_name,
        "target": target_host_port,
        "http_status": step2_info["http_status"],
        "success": success,
        "latency_ms": total_latency,
        "detail": step2_info["message"]
    }
    request_history.insert(0, history_item)
    if len(request_history) > 100:
        request_history.pop()

    return {
        "request_id": req_id,
        "mode": "naming",
        "success": success,
        "step1": step1_info,
        "step2": step2_info,
        "total_latency_ms": total_latency
    }

@app.get("/api/client/cache")
def get_client_cache_status():
    """Lấy thông tin bộ nhớ đệm và thời gian đếm ngược TTL"""
    now = time.time()
    ttl_remaining = 0.0
    if client_cache["expires_at"] and now < client_cache["expires_at"]:
        ttl_remaining = round(client_cache["expires_at"] - now, 1)
    else:
        # Đã hết hạn hoặc chưa có
        client_cache["nodes"] = []
        client_cache["expires_at"] = None

    return {
        "enabled": client_cache["enabled"],
        "nodes": client_cache["nodes"],
        "ttl_remaining": ttl_remaining,
        "total_ttl": client_cache["ttl"]
    }

@app.post("/api/client/cache/clear")
def clear_client_cache():
    """Xóa bộ nhớ đệm tại client"""
    client_cache["nodes"] = []
    client_cache["cached_at"] = None
    client_cache["expires_at"] = None
    return {"status": "SUCCESS", "message": "Client Cache đã được xóa"}

@app.get("/api/client/history")
def get_history():
    """Lấy danh sách lịch sử gọi request"""
    return request_history[:40]

@app.post("/api/client/history/clear")
def clear_history():
    request_history.clear()
    return {"status": "SUCCESS"}

# ==============================================================================
# WEB DASHBOARD (http://localhost:3000)
# ==============================================================================

@app.get("/", response_class=HTMLResponse)
def index_html():
    return """<!DOCTYPE html>
<html lang="vi" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CLIENT APPLICATION</title>
    <!-- TailwindCSS CDN -->
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    colors: {
                        darkBg: '#090e1a',
                        cardBg: '#111827',
                        cardBorder: '#1f2937',
                    }
                }
            }
        }
    </script>
    <!-- Font Awesome -->
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <!-- Google Fonts -->
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        body {
            font-family: 'Inter', sans-serif;
        }
        .font-mono-code {
            font-family: 'JetBrains Mono', monospace;
        }
        .glow-active {
            box-shadow: 0 0 25px rgba(56, 189, 248, 0.45);
        }
        .glow-success {
            box-shadow: 0 0 25px rgba(52, 211, 153, 0.45);
        }
        .glow-error {
            box-shadow: 0 0 25px rgba(248, 113, 113, 0.55);
        }
        .pulse-dot {
            animation: pulseAnimation 1.5s cubic-bezier(0.4, 0, 0.6, 1) infinite;
        }
        @keyframes pulseAnimation {
            0%, 100% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.3; transform: scale(1.2); }
        }
        /* Flow line light effect */
        .flow-line {
            transition: all 0.4s ease;
        }
        .flow-line-active {
            filter: drop-shadow(0 0 8px #38bdf8);
        }
        ::-webkit-scrollbar {
            width: 8px;
            height: 8px;
        }
        ::-webkit-scrollbar-track {
            background: #0b0f19;
        }
        ::-webkit-scrollbar-thumb {
            background: #1f2937;
            border-radius: 4px;
        }
    </style>
</head>
<body class="bg-darkBg text-slate-100 min-h-screen flex flex-col antialiased">

    <!-- Top Navigation / Header -->
    <header class="border-b border-cardBorder bg-slate-900/90 backdrop-blur sticky top-0 z-50">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 flex flex-wrap items-center justify-between gap-4">
            <div class="flex items-center space-x-4">
                <div class="w-12 h-12 rounded-xl bg-blue-500/20 border border-blue-500/40 flex items-center justify-center text-blue-400 text-2xl shadow-lg shadow-blue-500/20">
                    💻
                </div>
                <div>
                    <h1 class="text-2xl sm:text-3xl font-extrabold tracking-tight text-white flex items-center gap-3">
                        CLIENT APPLICATION
                    </h1>
                    
                </div>
            </div>

            <div class="flex items-center gap-3">
                <div class="flex items-center gap-2 bg-slate-800/80 px-3 py-1.5 rounded-xl border border-slate-700">
                    <span class="text-xs text-slate-400">Dịch vụ mục tiêu:</span>
                    <span class="text-xs font-mono-code font-bold text-cyan-400 bg-cyan-950/60 px-2 py-0.5 rounded border border-cyan-800">
                        order-service
                    </span>
                </div>
            </div>
        </div>
    </header>

    <!-- Main Content -->
    <main class="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">



        <!-- NÚT BẤM GỬI 1 REQUEST -->
        <section class="bg-cardBg border border-cardBorder rounded-2xl p-6 shadow-xl flex flex-wrap items-center justify-between gap-4">
            <div>
                <h3 class="text-lg font-extrabold text-white flex items-center gap-2">
                    <span class="text-blue-400"><i class="fa-solid fa-paper-plane"></i></span>
                     GỬI YÊU CẦU DỊCH VỤ
                </h3>
                <p class="text-xs text-slate-400 mt-1">
                    Client gửi yêu cầu tới Naming Server (:4000) để phân giải tên &amp; gọi dịch vụ <strong class="text-cyan-400 font-mono-code">order-service</strong>
                </p>
            </div>

            <div>
                <!-- Nút duy nhất: Gửi 1 Request -->
                <button id="btn-single-req" onclick="sendRequestOnce()" 
                        class="px-8 py-3.5 rounded-xl font-extrabold text-white text-base bg-gradient-to-r from-blue-600 via-indigo-600 to-cyan-600 hover:from-blue-500 hover:to-cyan-500 active:scale-95 transition shadow-lg shadow-blue-900/40 flex items-center gap-2.5 border border-blue-400/30">
                    <i class="fa-solid fa-paper-plane"></i>
                    <span id="btn-single-req-label">🚀 GỬI 1 REQUEST</span>
                </button>
            </div>
        </section>

        <!-- BẢNG LỊCH SỬ REQUEST (REQUEST HISTORY TABLE) -->
        <section class="bg-cardBg border border-cardBorder rounded-2xl shadow-xl overflow-hidden">
            <div class="px-6 py-4 border-b border-cardBorder flex flex-wrap items-center justify-between gap-3 bg-slate-900/60">
                <div class="flex items-center space-x-3">
                    <span class="text-blue-400 text-lg"><i class="fa-solid fa-clock-rotate-left"></i></span>
                    <h3 class="text-base font-bold text-white tracking-wide">
                        KHUNG LỊCH SỬ REQUEST (REQUEST HISTORY TABLE)
                    </h3>
                    <span class="text-xs bg-slate-800 text-slate-300 px-2 py-0.5 rounded-full font-mono-code" id="history-count-badge">
                        0 lần gọi
                    </span>
                </div>
                <button onclick="clearHistory()" class="px-3 py-1 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition border border-slate-700 flex items-center gap-1.5">
                    <i class="fa-regular fa-trash-can"></i> Xóa Lịch Sử
                </button>
            </div>

            <!-- Table -->
            <div class="overflow-x-auto">
                <table class="w-full text-left border-collapse">
                    <thead>
                        <tr class="border-b border-slate-800 bg-slate-950/80 text-xs font-bold uppercase tracking-wider text-slate-400">
                            <th class="py-3 px-6">#ID</th>
                            <th class="py-3 px-6">Thời Gian</th>
                            
                            <th class="py-3 px-6">Nguồn IP (Discovery)</th>
                            <th class="py-3 px-6">Node Đích Đã Gọi</th>
                            <th class="py-3 px-6">Mã HTTP & Kết Quả</th>
                            <th class="py-3 px-6">Độ Trễ</th>
                        </tr>
                    </thead>
                    <tbody id="history-table-body" class="divide-y divide-slate-800 text-sm">
                        <tr>
                            <td colspan="7" class="py-8 text-center text-slate-500 font-medium">
                                Chưa có request nào được gửi. Hãy bấm <strong>[🚀 GỬI 1 REQUEST]</strong> ở trên.
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </section>

    </main>

    

    <!-- Logic Client Dashboard -->
    <script>
        let isSending = false;

        async function sendRequestOnce() {
            if (isSending) return;
            isSending = true;

            const btnLabel = document.getElementById('btn-single-req-label');
            const originalText = btnLabel ? btnLabel.innerText : "🚀 GỬI 1 REQUEST";
            if (btnLabel) btnLabel.innerText = "⏳ Đang gửi request...";

            try {
                const res = await fetch('/api/client/send-request', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        mode: 'naming',
                        cache_enabled: false,
                        load_balancing: 'round_robin',
                        service_name: 'order-service'
                    })
                });

                await res.json();
                await fetchHistory();
            } catch (err) {
                console.error("Lỗi khi gửi request:", err);
            } finally {
                isSending = false;
                if (btnLabel) btnLabel.innerText = originalText;
            }
        }

        async function fetchHistory() {
            try {
                const res = await fetch('/api/client/history');
                if (!res.ok) return;
                const list = await res.json();

                document.getElementById('history-count-badge').innerText = `${list.length} lần gọi`;
                const tbody = document.getElementById('history-table-body');

                if (!list || list.length === 0) {
                    tbody.innerHTML = `
                        <tr>
                            <td colspan="7" class="py-8 text-center text-slate-500 font-medium">
                                Chưa có request nào được gửi. Hãy bấm <strong>[🚀 GỬI 1 REQUEST]</strong> ở trên.
                            </td>
                        </tr>
                    `;
                    return;
                }

                let html = '';
                list.forEach(item => {
                    const statusBadge = item.success
                        ? `<span class="inline-flex items-center px-2.5 py-0.5 rounded text-xs font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/40">
                             <i class="fa-solid fa-check mr-1 text-[10px]"></i> HTTP ${item.http_status}
                           </span>`
                        : `<span class="inline-flex items-center px-2.5 py-0.5 rounded text-xs font-bold bg-rose-500/20 text-rose-400 border border-rose-500/40">
                             <i class="fa-solid fa-xmark mr-1 text-[10px]"></i> HTTP ${item.http_status} (LỖI)
                           </span>`;

                    const sourceBadge = item.source.includes('Cache')
                        ? `<span class="text-amber-400 font-semibold font-mono-code text-xs"><i class="fa-solid fa-bolt mr-1"></i>${item.source}</span>`
                        : (item.source.includes('Hard-code') 
                            ? `<span class="text-slate-400 font-mono-code text-xs">${item.source}</span>`
                            : `<span class="text-cyan-400 font-semibold font-mono-code text-xs"><i class="fa-solid fa-server mr-1"></i>${item.source}</span>`);

                    html += `
                        <tr class="hover:bg-slate-800/50 transition">
                            <td class="py-3 px-6 font-mono-code font-bold text-slate-400">#${item.id}</td>
                            <td class="py-3 px-6 text-slate-300 font-mono-code text-xs">${item.time}</td>
                            <td class="py-3 px-6 font-semibold text-xs text-slate-200">${item.mode}</td>
                            <td class="py-3 px-6">${sourceBadge}</td>
                            <td class="py-3 px-6 font-mono-code font-bold text-slate-100">${item.target}</td>
                            <td class="py-3 px-6">${statusBadge}</td>
                            <td class="py-3 px-6 font-mono-code text-xs text-slate-400">${item.latency_ms} ms</td>
                        </tr>
                    `;
                });
                tbody.innerHTML = html;

            } catch (e) {
                console.error(e);
            }
        }

        async function clearHistory() {
            await fetch('/api/client/history/clear', { method: 'POST' });
            fetchHistory();
        }

        // Init
        fetchHistory();
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Client Dashboard Application")
    parser.add_argument("--port", type=int, default=3000, help="Port to listen on (default 3000)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host interface (default 127.0.0.1)")
    args = parser.parse_args()

    print(f"🚀 Client Dashboard khởi động tại http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
