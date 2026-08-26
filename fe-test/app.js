(() => {
  const $ = (id) => document.getElementById(id);

  const apiBaseInput = $("apiBase");
  const healthBadge = $("healthBadge");
  const logEl = $("log");
  const video = $("video");
  const canvas = $("canvas");
  const preview = $("preview");

  let stream = null;
  let lastAnswer = "";
  let lastImageBase64 = "";

  // Same-origin when served from FastAPI /fe-test/
  apiBaseInput.value = window.location.origin.includes("8000")
    ? window.location.origin
    : "http://127.0.0.1:8000";

  function apiBase() {
    return apiBaseInput.value.replace(/\/$/, "");
  }

  function log(msg, data) {
    const stamp = new Date().toLocaleTimeString();
    const line = data === undefined
      ? `[${stamp}] ${msg}`
      : `[${stamp}] ${msg}\n${typeof data === "string" ? data : JSON.stringify(data, null, 2)}`;
    logEl.textContent = `${line}\n\n${logEl.textContent}`.slice(0, 12000);
  }

  function show(el, data) {
    el.textContent = typeof data === "string" ? data : JSON.stringify(data, null, 2);
  }

  async function api(path, options = {}) {
    const url = `${apiBase()}${path}`;
    log(`→ ${options.method || "GET"} ${url}`);
    const res = await fetch(url, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });

    const contentType = res.headers.get("content-type") || "";
    if (contentType.includes("audio")) {
      const blob = await res.blob();
      log(`← ${res.status} audio/${blob.type} (${blob.size} bytes)`);
      return { ok: res.ok, status: res.status, blob };
    }

    const text = await res.text();
    let json = null;
    try {
      json = text ? JSON.parse(text) : null;
    } catch {
      json = { raw: text };
    }
    log(`← ${res.status}`, json);
    return { ok: res.ok, status: res.status, json };
  }

  // ---------- Health ----------
  $("btnHealth").onclick = async () => {
    try {
      const a = await api("/health");
      const b = await api("/health/db");
      const ok = a.ok && b.ok;
      healthBadge.textContent = ok ? "ok" : "fail";
      healthBadge.className = `badge ${ok ? "ok" : "bad"}`;
      show($("dashOut"), { health: a.json, db: b.json });
    } catch (err) {
      healthBadge.textContent = "fail";
      healthBadge.className = "badge bad";
      log("Health failed", String(err));
    }
  };

  // ---------- Camera ----------
  $("btnCamOn").onclick = async () => {
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } },
        audio: false,
      });
      video.srcObject = stream;
      log("Camera opened");
    } catch (err) {
      log("Camera failed", String(err));
      alert("Could not open camera. Allow camera permission and use HTTPS or localhost.");
    }
  };

  $("btnCamOff").onclick = () => {
    if (stream) {
      stream.getTracks().forEach((t) => t.stop());
      stream = null;
    }
    video.srcObject = null;
    log("Camera stopped");
  };

  function snapBase64() {
    if (!stream) throw new Error("Open the camera first.");
    const w = video.videoWidth || 640;
    const h = video.videoHeight || 480;
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(video, 0, 0, w, h);
    const dataUrl = canvas.toDataURL("image/jpeg", 0.92);
    preview.src = dataUrl;
    preview.hidden = false;
    lastImageBase64 = dataUrl;
    return dataUrl;
  }

  $("btnSnap").onclick = async () => {
    try {
      const image_base64 = snapBase64();
      const body = {
        image_base64,
        run_web_search: $("runWebSearch").checked,
      };
      const { json } = await api("/api/face/detect", {
        method: "POST",
        body: JSON.stringify(body),
      });
      show($("faceOut"), json);

      const data = json?.data;
      if (data?.visitor_id) {
        $("visitorId").value = data.visitor_id;
      }
      if (data?.capture?.capture_id) {
        $("captureId").value = data.capture.capture_id;
        show($("captureOut"), data.capture);
      }
    } catch (err) {
      show($("faceOut"), String(err));
      log("Detect failed", String(err));
    }
  };

  // ---------- Captures ----------
  $("btnListCaptures").onclick = async () => {
    const { json } = await api("/api/face/captures?limit=20");
    show($("captureOut"), json);
  };

  $("btnGetCapture").onclick = async () => {
    const id = $("captureId").value;
    if (!id) return alert("Enter capture_id");
    const { json } = await api(`/api/face/captures/${id}`);
    show($("captureOut"), json);
  };

  $("btnRerunWeb").onclick = async () => {
    const id = $("captureId").value;
    if (!id) return alert("Enter capture_id");
    const { json } = await api(`/api/face/captures/${id}/web-search`, { method: "POST" });
    show($("captureOut"), json);
  };

  $("btnDismiss").onclick = async () => {
    const id = $("captureId").value;
    if (!id) return alert("Enter capture_id");
    const { json } = await api(`/api/face/captures/${id}/dismiss`, { method: "POST" });
    show($("captureOut"), json);
  };

  $("btnLink").onclick = async () => {
    const id = $("captureId").value;
    if (!id) return alert("Enter capture_id");
    const body = {
      enroll_face: true,
    };
    if ($("linkVisitorId").value) body.visitor_id = Number($("linkVisitorId").value);
    if ($("linkName").value) body.full_name = $("linkName").value;
    if ($("linkPhone").value) body.mobile_number = $("linkPhone").value;
    const { json } = await api(`/api/face/captures/${id}/link`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    show($("captureOut"), json);
    if (json?.data?.visitor_id) $("visitorId").value = json.data.visitor_id;
  };

  // ---------- Voice ----------
  document.querySelectorAll(".quick button").forEach((btn) => {
    btn.onclick = () => {
      $("voiceQuestion").value = btn.dataset.q;
    };
  });

  $("btnListen").onclick = () => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      alert("Speech recognition not supported in this browser. Use Chrome, or type the question.");
      return;
    }
    const rec = new SpeechRecognition();
    rec.lang = "en-US";
    rec.interimResults = false;
    rec.onresult = (e) => {
      $("voiceQuestion").value = e.results[0][0].transcript;
      log("Heard", $("voiceQuestion").value);
    };
    rec.onerror = (e) => log("Listen error", e.error);
    rec.start();
    log("Listening...");
  };

  $("btnAsk").onclick = async () => {
    const question = $("voiceQuestion").value.trim();
    if (!question) return alert("Enter or speak a question");
    const { json } = await api("/api/kiosk/room-question", {
      method: "POST",
      body: JSON.stringify({ question }),
    });
    show($("voiceOut"), json);
    lastAnswer = json?.data?.answer || "";
  };

  $("btnSpeak").onclick = async () => {
    const text = lastAnswer || $("voiceQuestion").value.trim();
    if (!text) return alert("Ask a question first, or type text to speak");

    // Try server TTS first
    try {
      const result = await api("/api/kiosk/speak", {
        method: "POST",
        body: JSON.stringify({ text }),
      });
      if (result.ok && result.blob) {
        const url = URL.createObjectURL(result.blob);
        const audio = new Audio(url);
        await audio.play();
        log("Playing server TTS");
        return;
      }
      log("Server TTS unavailable, falling back to browser speechSynthesis");
    } catch (err) {
      log("Server TTS error, using browser", String(err));
    }

    if (!window.speechSynthesis) {
      alert("No TTS available");
      return;
    }
    const utter = new SpeechSynthesisUtterance(text);
    utter.lang = "en-US";
    window.speechSynthesis.speak(utter);
  };

  // ---------- Lookup / visit / book ----------
  $("btnLookup").onclick = async () => {
    const { json } = await api("/api/kiosk/profile-lookup", {
      method: "POST",
      body: JSON.stringify({
        full_name: $("fullName").value,
        mobile_number: $("mobile").value,
      }),
    });
    show($("kioskOut"), json);
    if (json?.data?.visitor_id) $("visitorId").value = json.data.visitor_id;
  };

  $("btnVisit").onclick = async () => {
    const visitor_id = Number($("visitorId").value);
    if (!visitor_id) return alert("visitor_id required");
    const { json } = await api("/api/kiosk/visit-sessions", {
      method: "POST",
      body: JSON.stringify({
        visitor_id,
        recognition_method: "face",
        current_selected_service: $("serviceType").value,
      }),
    });
    show($("kioskOut"), json);
  };

  $("btnBook").onclick = async () => {
    const visitor_id = Number($("visitorId").value);
    if (!visitor_id) return alert("visitor_id required");
    const today = new Date();
    const yyyy = today.getFullYear();
    const mm = String(today.getMonth() + 1).padStart(2, "0");
    const dd = String(today.getDate()).padStart(2, "0");
    const { json } = await api("/api/kiosk/bookings", {
      method: "POST",
      body: JSON.stringify({
        visitor_id,
        service_type: $("serviceType").value,
        zone_id: $("zoneId").value || undefined,
        booking_date: `${yyyy}-${mm}-${dd}`,
        booking_time_start: `${$("bookTime").value}:00`,
        duration_minutes: 60,
      }),
    });
    show($("kioskOut"), json);
  };

  // ---------- Dashboard ----------
  $("btnZones").onclick = async () => show($("dashOut"), (await api("/api/zones")).json);
  $("btnBookings").onclick = async () => show($("dashOut"), (await api("/api/bookings")).json);
  $("btnEvents").onclick = async () => show($("dashOut"), (await api("/api/events")).json);
  $("btnHeader").onclick = async () => show($("dashOut"), (await api("/api/header")).json);
  $("btnFeed").onclick = async () => show($("dashOut"), (await api("/api/activity-feed")).json);

  window.addEventListener("beforeunload", () => {
    if (stream) stream.getTracks().forEach((t) => t.stop());
  });
})();
