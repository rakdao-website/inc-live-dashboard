import { RealtimeAgent, RealtimeSession, OpenAIRealtimeWebSocket, tool } from "@openai/agents/realtime";
import { z } from "zod";

// PCM16 sample rate used throughout - both capture and playback contexts
// are created at this rate to avoid needing to resample. NOTE: not
// explicitly confirmed in the docs provided that the Realtime API expects
// exactly 24kHz for pcm16 - if audio sounds pitched wrong, this is the
// first thing to check against OpenAI's actual API reference.
const PCM_SAMPLE_RATE = 24000;

// Points at your FastAPI backend's ephemeral-token endpoint
// (app/voice_agent/realtime_auth.py). Change if it runs elsewhere.
const BACKEND_BASE_URL = "http://127.0.0.1:8000";

const statusEl = document.getElementById("status");
const transcriptEl = document.getElementById("transcript");
const connectBtn = document.getElementById("connect-btn");
const muteBtn = document.getElementById("mute-btn");
const disconnectBtn = document.getElementById("disconnect-btn");
const simVisitorCheckbox = document.getElementById("sim-visitor");
const visitorFieldsEl = document.getElementById("visitor-fields");

simVisitorCheckbox.addEventListener("change", () => {
  visitorFieldsEl.style.display = simVisitorCheckbox.checked ? "block" : "none";
});

let session = null;
let muted = false;

// Set once lookup_visitor or register_visitor succeeds (or pre-populated
// at connect time when "Simulate already-logged-in visitor" is checked,
// mirroring the text pipeline's visitor_id pre-authentication shortcut in
// _prepare_session - skips the whole greeting/collection flow for a
// visitor we already know, saving a real round of tokens and turns).
// Tools read this via closure for create_booking etc.
let currentVisitor = null;

function setStatus(text) {
  statusEl.textContent = text;
}

updateVisitorStatus();

function appendTranscript(role, text) {
  const line = document.createElement("div");
  line.className = role === "user" ? "msg-user" : "msg-assistant";
  line.textContent = `${role === "user" ? "You" : "Assistant"}: ${text}`;
  transcriptEl.appendChild(line);
  transcriptEl.scrollTop = transcriptEl.scrollHeight;
}

function appendToolLog(text) {
  const line = document.createElement("div");
  line.style.color = "#8b94a7";
  line.style.fontStyle = "italic";
  line.textContent = `[tool] ${text}`;
  transcriptEl.appendChild(line);
  transcriptEl.scrollTop = transcriptEl.scrollHeight;
}

function float32ToInt16(float32Array) {
  const int16Array = new Int16Array(float32Array.length);
  for (let i = 0; i < float32Array.length; i++) {
    const s = Math.max(-1, Math.min(1, float32Array[i]));
    int16Array[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return int16Array;
}

function int16ToFloat32(int16Array) {
  const float32Array = new Float32Array(int16Array.length);
  for (let i = 0; i < int16Array.length; i++) {
    const s = int16Array[i];
    float32Array[i] = s < 0 ? s / 0x8000 : s / 0x7fff;
  }
  return float32Array;
}

// --- Mic capture (replaces WebRTC's automatic capture) ---------------
// micEnabled replaces session.mute(), which doesn't exist for the
// WebSocket transport at all - gates whether captured audio actually gets
// sent anywhere, without touching the underlying getUserMedia stream.
let micEnabled = false;
let micAudioContext = null;
let micStream = null;

async function setupMicCapture(activeSession) {
  micStream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  micAudioContext = new AudioContext({ sampleRate: PCM_SAMPLE_RATE });
  await micAudioContext.audioWorklet.addModule("/pcm-recorder-worklet.js");

  const micSource = micAudioContext.createMediaStreamSource(micStream);
  const workletNode = new AudioWorkletNode(micAudioContext, "pcm-recorder-processor");

  workletNode.port.onmessage = (event) => {
    if (!micEnabled) return; // muted - don't send anything anywhere
    const int16 = float32ToInt16(event.data);
    // NOTE: sendAudio's exact expected argument type (ArrayBuffer vs a
    // wrapped object) wasn't confirmed in the docs provided - this passes
    // the raw ArrayBuffer per the one example shown (`new ArrayBuffer(0)`).
    activeSession.sendAudio(int16.buffer);
  };

  // Deliberately NOT connecting workletNode to micAudioContext.destination -
  // we don't want to hear our own mic played back locally.
  micSource.connect(workletNode);
}

function teardownMicCapture() {
  if (micStream) {
    micStream.getTracks().forEach((t) => t.stop());
    micStream = null;
  }
  if (micAudioContext) {
    micAudioContext.close().catch(() => {});
    micAudioContext = null;
  }
}

// --- Playback (replaces WebRTC's automatic playback) ------------------
// Schedules each incoming PCM16 chunk back-to-back via the Web Audio API.
//
// Tracked PER RESPONSE (keyed by responseId, which every 'audio' event
// already carries) rather than with one shared counter - responses can
// overlap in practice (e.g. a tool-call follow-up response starting to
// generate/play before the previous response's trailing chunks have
// finished), and a single global counter has no way to tell those apart,
// which was causing the "finished" signal to fire against the wrong
// response's chunk count entirely.
let playbackAudioContext = null;
let nextPlayTime = 0;
const responseAudioState = new Map(); // responseId -> { pending: number, done: boolean }

function getResponseState(responseId) {
  const key = responseId ?? "__unknown__";
  if (!responseAudioState.has(key)) {
    responseAudioState.set(key, { pending: 0, done: false });
  }
  return responseAudioState.get(key);
}

// True only once every response we're currently tracking has both been
// marked done (response.done fired for it) AND finished playing all its
// chunks - this is what actually tells us it's safe to unmute, regardless
// of how many responses overlapped.
function allResponsesFinished() {
  for (const state of responseAudioState.values()) {
    if (!state.done || state.pending > 0) return false;
  }
  return true;
}

function setupPlayback() {
  playbackAudioContext = new AudioContext({ sampleRate: PCM_SAMPLE_RATE });
  nextPlayTime = playbackAudioContext.currentTime;
}

function playPCM16Chunk(arrayBuffer, responseId) {
  if (!playbackAudioContext) return;
  const int16 = new Int16Array(arrayBuffer);
  const float32 = int16ToFloat32(int16);

  const audioBuffer = playbackAudioContext.createBuffer(1, float32.length, PCM_SAMPLE_RATE);
  audioBuffer.copyToChannel(float32, 0);

  const source = playbackAudioContext.createBufferSource();
  source.buffer = audioBuffer;
  source.connect(playbackAudioContext.destination);

  const startAt = Math.max(nextPlayTime, playbackAudioContext.currentTime);
  source.start(startAt);
  nextPlayTime = startAt + audioBuffer.duration;

  const state = getResponseState(responseId);
  state.pending++;
  console.log(
    `[playback] scheduled chunk for ${responseId} - pending(this response)=${state.pending}, ` +
    `startAt=${startAt.toFixed(2)}, duration=${audioBuffer.duration.toFixed(2)}s, done=${state.done}`
  );
  source.onended = () => {
    state.pending = Math.max(0, state.pending - 1);
    console.log(`[playback] chunk ended for ${responseId} - pending(this response)=${state.pending}, done=${state.done}`);
    if (allResponsesFinished()) {
      onPlaybackFullyFinished();
    }
  };
}

// Set by the response.created/response.done handlers below - only treat
// "all scheduled chunks finished" as "the assistant is done talking" while
// we're actually expecting a response; avoids acting on stray leftover
// chunks finishing after a disconnect, etc.
let awaitingPlaybackFinish = false;

function onPlaybackFullyFinished() {
  if (!awaitingPlaybackFinish) return;
  awaitingPlaybackFinish = false;
  responseAudioState.clear(); // done with this exchange - start fresh for the next one
  micEnabled = true;
  muted = false;
  muteBtn.textContent = "Mute";
  setStatus("connected - your turn to talk");
}

function updateVisitorStatus() {
  const el = document.getElementById("visitor-status");
  if (!el) return;
  el.textContent = currentVisitor
    ? `Signed in as: ${currentVisitor.visitor_name} (visitor_id ${currentVisitor.visitor_id}, ${currentVisitor.visitor_type})`
    : "Not signed in yet";
}

async function fetchEphemeralKey() {
  const res = await fetch(`${BACKEND_BASE_URL}/voice-agent/realtime-session`, { method: "POST" });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`Failed to mint realtime session: ${res.status} - ${body}`);
  }
  const data = await res.json();
  // NOTE: realtime_auth.py's response shape (and the "raw" debug field) is
  // marked for verification against OpenAI's actual client_secrets response -
  // if this ever comes back empty, check that file first.
  if (!data.client_secret) {
    throw new Error("Backend didn't return a client_secret - check realtime_auth.py");
  }
  return data.client_secret;
}

// Mirrors normalize_phone_() in converse.py - the text pipeline always
// normalizes before calling these same endpoints; doing the same here in
// case the backend validates phone format strictly.
function normalizePhoneForBackend(phone) {
  const raw = (phone || "").trim();
  if (raw.startsWith("+")) return raw.replace(/[^\d+]/g, "");
  const cleaned = raw.replace(/[^\d]/g, "").replace(/^0+/, "");
  return `+971${cleaned}`;
}

// --- Identity tools --------------------------------------------------
// Thin wrappers around your existing REST endpoints - all the actual
// validation (duplicate phone numbers, etc.) already lives there and is
// reused as-is. These just give the model a way to call them.

const lookupVisitorTool = tool({
  name: "lookup_visitor",
  description:
    "Look up an existing customer by phone number to log them in. Only call this once " +
    "you have their phone number, and they've told you they're an existing customer.",
  parameters: z.object({
    full_name: z.string().describe("The visitor's full name, as given (used for context/logging only)"),
    mobile_number: z.string().describe("The visitor's phone number, as given"),
  }),
  async execute({ full_name, mobile_number }) {
    const normalizedPhone = normalizePhoneForBackend(mobile_number);
    appendToolLog(`lookup_visitor(${full_name}, ${mobile_number} -> ${normalizedPhone})`);
    try {
      // Phone-only lookup (see kiosk_flow_visitor_by_phone_snippet.py) -
      // deliberately NOT matching on name too, since a voice-transcribed
      // name is unreliable and shouldn't block a login when the phone
      // number is genuinely correct.
      const res = await fetch(
        `${BACKEND_BASE_URL}/api/kiosk/visitor-by-phone?mobile_number=${encodeURIComponent(normalizedPhone)}`
      );
      const body = await res.json().catch(() => ({}));
      if (res.ok && body?.data) {
        currentVisitor = body.data;
        updateVisitorStatus();
        appendToolLog(`found: ${body.data.visitor_name} (visitor_id ${body.data.visitor_id})`);
        return JSON.stringify({ found: true, visitor: body.data });
      }
      appendToolLog(`not found (status ${res.status}) - details: ${JSON.stringify(body?.details ?? body)}`);
      return JSON.stringify({
        found: false,
        message: "No profile found with that phone number - offer to register them instead.",
      });
    } catch (err) {
      appendToolLog(`error: ${err}`);
      return JSON.stringify({ found: false, error: String(err) });
    }
  },
});

const registerVisitorTool = tool({
  name: "register_visitor",
  description:
    "Register a new visitor with their full name, phone number, visitor type, and " +
    "optionally email. Only call this once you have their full name and phone number, " +
    "and they've told you this is their first time / they're not an existing customer.",
  parameters: z.object({
    full_name: z.string(),
    mobile_number: z.string(),
    email: z.string().nullable().describe("Email address if they gave one, otherwise null"),
    visitor_type: z.enum(["visitor", "client"]).describe("Almost always 'visitor' for a new registration"),
  }),
  async execute({ full_name, mobile_number, email, visitor_type }) {
    const normalizedPhone = normalizePhoneForBackend(mobile_number);
    appendToolLog(`register_visitor(${full_name}, ${mobile_number} -> ${normalizedPhone})`);
    try {
      const res = await fetch(`${BACKEND_BASE_URL}/api/kiosk/profiles`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          full_name,
          mobile_number: normalizedPhone,
          email: email || null,
          visitor_type: visitor_type || "visitor",
        }),
      });
      const body = await res.json().catch(() => ({}));
      if (res.status === 201 && body?.data) {
        currentVisitor = body.data;
        updateVisitorStatus();
        appendToolLog(`registered: ${body.data.visitor_name} (visitor_id ${body.data.visitor_id})`);
        return JSON.stringify({ registered: true, visitor: body.data });
      }
      if (res.status === 409) {
        // Same fallback the text pipeline uses: a phone number that's
        // already registered means this is actually an existing customer -
        // the model should call lookup_visitor instead.
        appendToolLog("conflict: phone already registered - should call lookup_visitor instead");
        return JSON.stringify({
          registered: false,
          conflict: true,
          message: "A profile with this phone number already exists - call lookup_visitor instead to log them in.",
        });
      }
      if (res.status === 422) {
        appendToolLog(`validation error - details: ${JSON.stringify(body?.details ?? body)}`);
        return JSON.stringify({
          registered: false,
          message:
            "That phone number couldn't be validated - it was likely misheard (wrong number of " +
            "digits). Ask the visitor to repeat their phone number slowly, one digit at a time, " +
            "read it back to confirm, then try again. Do not retry with the same number.",
        });
      }
      appendToolLog(`registration failed: ${body?.message || res.status} - details: ${JSON.stringify(body?.details ?? body)}`);
      return JSON.stringify({ registered: false, message: body?.message || "Registration failed." });
    } catch (err) {
      appendToolLog(`error: ${err}`);
      return JSON.stringify({ registered: false, error: String(err) });
    }
  },
});

// Known room -> (service_type, zone_id) mapping, matching
// kiosk_flow_services.py's SERVICE_DEFAULTS and the two meeting room zone
// ids used elsewhere in this project (MR_1/MR_2). If your actual zone ids
// differ, update this map - it's the one place that would need to change.
const ROOM_MAP = {
  meeting_room_1: { service_type: "meeting_room", zone_id: "MR_1" },
  meeting_room_2: { service_type: "meeting_room", zone_id: "MR_2" },
  podcast_studio: { service_type: "podcast_studio", zone_id: "POD_1" },
  tiktok_studio: { service_type: "tiktok_studio", zone_id: "TTS_1" },
};

const createBookingTool = tool({
  name: "create_booking",
  description:
    "Book a meeting room, podcast studio, or TikTok studio for the signed-in visitor. Only call " +
    "this once you know which room/service, the date, the time, and the duration, and the visitor " +
    "is already signed in (via lookup_visitor or register_visitor).",
  parameters: z.object({
    room: z
      .enum(["meeting_room_1", "meeting_room_2", "podcast_studio", "tiktok_studio"])
      .describe("Which room or service to book"),
    date: z.string().describe("The date, in YYYY-MM-DD format"),
    time: z.string().describe("The start time, 24-hour format, e.g. '14:00'"),
    duration_minutes: z.number().describe("How long the booking is for, in minutes"),
  }),
  needsApproval: true,
  async execute({ room, date, time, duration_minutes }) {
    if (!currentVisitor) {
      appendToolLog("create_booking refused: no visitor signed in yet");
      return JSON.stringify({
        booked: false,
        message: "No visitor is signed in yet - log them in or register them first.",
      });
    }

    const mapping = ROOM_MAP[room];
    appendToolLog(`create_booking(${room}, ${date} ${time}, ${duration_minutes}min)`);
    try {
      const res = await fetch(`${BACKEND_BASE_URL}/api/kiosk/bookings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          visitor_id: currentVisitor.visitor_id,
          service_type: mapping.service_type,
          zone_id: mapping.zone_id,
          booking_date: date,
          booking_time_start: time,
          duration_minutes,
        }),
      });
      const body = await res.json().catch(() => ({}));
      if (res.status === 201 && body?.data) {
        appendToolLog(
          `booked: ${body.data.room_name} ${body.data.booking_time_start}-${body.data.booking_time_end}`
        );
        return JSON.stringify({ booked: true, booking: body.data });
      }
      appendToolLog(`booking failed (status ${res.status}): ${JSON.stringify(body?.details ?? body?.message ?? body)}`);
      return JSON.stringify({
        booked: false,
        message: body?.message || "That didn't work - please tell the visitor and offer to try a different time.",
        details: body?.details,
      });
    } catch (err) {
      appendToolLog(`error: ${err}`);
      return JSON.stringify({ booked: false, error: String(err) });
    }
  },
});

async function fetchKnowledgeBase() {
  try {
    const res = await fetch(`${BACKEND_BASE_URL}/voice-agent/knowledge-base`);
    if (!res.ok) throw new Error(`status ${res.status}`);
    const data = await res.json();
    return data.knowledge_base || "";
  } catch (err) {
    console.error("Failed to fetch knowledge base, falling back to a minimal placeholder:", err);
    return "(Knowledge base unavailable right now - if asked something you don't know, say you're not sure and suggest asking a reception associate.)";
  }
}

// Step 3 instructions: now includes the login/register flow using the
// tools above. Still a placeholder for the real knowledge_base.md content
// and still no booking (Step 4).
function buildInstructions(knowledgeBase, knownVisitor) {
  const today = new Date().toISOString().slice(0, 10);

  const greetingSection = knownVisitor
    ? `**Greeting.** ${knownVisitor.visitor_name} is ALREADY signed in (${knownVisitor.visitor_type === "client" ? "existing customer" : "new visitor"}) - do NOT ask for their name, email, phone, or customer status, you already have all of it. Just greet them warmly by name and ask how you can help.`
    : `**Greeting.** Greet the visitor warmly, briefly mention what you can help with (logging in or
registering, answering questions about Innovation City, and booking a meeting room, podcast
studio, or TikTok studio), and ask for their full name, their email, and whether they're an
existing customer or not. Ask together, not one at a time - only re-ask whatever's still missing.`;

  const signInSection = knownVisitor
    ? "" // already signed in - nothing to collect, so this whole section is just omitted (saves tokens every turn)
    : `
**Phone numbers are easy to mishear.** Read the phone number back to confirm before calling
lookup_visitor or register_visitor - same format they gave it in (digit-by-digit if that's how they
said it, not reformatted). Only call the tool once confirmed; if wrong, re-listen and confirm again.

**Signing them in, once you know if they're an existing customer:**
- Existing customer -> just their phone number (lookup works by phone alone). Found -> greet by
  name, logged in. Not found -> apologize, register instead (visitor_type "visitor", need full name too).
- Not existing -> full name + phone (email optional). register_visitor with visitor_type "visitor".
  Conflict (phone already registered) -> call lookup_visitor instead.

Don't retry lookup_visitor/register_visitor with the same info - wait for something new first.
`;

  return `
You are a friendly voice assistant for Innovation City, a business hub in RAK. Your job is to
greet visitors, sign them in (log in an existing customer or register a new visitor), answer
questions, and help with bookings. Today's date is ${today}.

${greetingSection}

**Questions can come at any time.** No matter what you're in the middle of, answer a genuine
question right away using the knowledge base below - never defer it. Then pick back up exactly
where you left off (don't restart the greeting or re-ask for info you already have).
${signInSection}
**Booking a room or service.** Once signed in, book via create_booking. You need:
- Which room/service - if "a meeting room" without specifying, ask which (there are two:
  meeting_room_1/meeting_room_2). Podcast/TikTok studio: only one each, don't ask which.
- Date, time, and duration in minutes.

Gather whatever's missing across turns - don't demand everything at once. Call create_booking once
you have all four. Must be signed in first. An unrelated question mid-booking gets answered
normally - pick the booking back up after, no need to force them to finish first.

**Knowledge base - use this, and only this, for general questions** (hours, rooms, amenities, wifi,
studios, company info). If not covered here, say you're not sure and suggest reception:

${knowledgeBase}

After completing a real task (signing in, finishing a booking), ask if there's anything else. For a
plain question, just answer it - don't tack on "anything else?" every single time, that gets
repetitive. Only say goodbye when they clearly say they're finished, never on your own.

Be concise, warm, and professional. Keep answers short - a sentence or two, not a paragraph.
`.trim();
}

connectBtn.addEventListener("click", async () => {
  connectBtn.disabled = true;
  setStatus("loading knowledge base…");

  try {
    const knowledgeBase = await fetchKnowledgeBase();

    // Pre-authenticate, same as the text pipeline's visitor_id shortcut in
    // _prepare_session - if we already know who this is, skip the whole
    // greeting/collection flow (and its token cost) entirely.
    if (simVisitorCheckbox.checked) {
      const visitorId = parseInt(document.getElementById("visitor-id").value, 10);
      currentVisitor = {
        visitor_id: Number.isNaN(visitorId) ? null : visitorId,
        visitor_name: document.getElementById("visitor-name").value || "the visitor",
        visitor_type: document.getElementById("visitor-type").value || "visitor",
      };
      updateVisitorStatus();
    }

    setStatus("minting ephemeral token…");

    const agent = new RealtimeAgent({
      name: "Innovation City Assistant",
      instructions: buildInstructions(knowledgeBase, currentVisitor),
      tools: [lookupVisitorTool, registerVisitorTool, createBookingTool],
    });

    // Explicit WebSocket transport - we handle mic capture and audio
    // playback ourselves (see setupMicCapture/setupPlayback/playPCM16Chunk
    // above) instead of relying on WebRTC's automatic handling, which
    // wasn't giving us reliable control over interruptions/mute timing.
    // NOTE: passing `transport:` here as a constructor option wasn't
    // explicitly shown in the docs provided for this exact case - if this
    // errors, check the SDK's actual RealtimeSession constructor types.
    session = new RealtimeSession(agent, {
      model: "gpt-realtime-2.1",
      transport: new OpenAIRealtimeWebSocket(),
      config: {
        outputModalities: ["audio"],
        audio: {
          input: {
            format: "pcm16",
            turnDetection: {
              // server_vad (threshold-based) instead of semantic_vad -
              // semantic_vad is tuned to catch natural speech patterns,
              // which makes it more prone to false-triggering on ambient
              // noise. A plain threshold lets us directly dial in how
              // loud/clear something needs to be to count as real speech.
              type: "server_vad",
              threshold: 0.6, // 0-1; higher = less sensitive to background noise
              prefixPaddingMs: 300, // audio kept before detected speech start
              silenceDurationMs: 600, // how long silence must last to end a turn
              // false (not true): VAD still detects turns, but does NOT
              // automatically generate a response on its own anymore. This
              // was the actual cause of the model answering questions no
              // one asked and chaining into an unprompted goodbye - VAD
              // was auto-triggering new responses off ambiguous audio
              // (background noise, brief blips) with no real user turn
              // behind them. We now trigger response.create ourselves,
              // only on a genuine input_audio_buffer.speech_stopped event
              // (see below) - a real, controlled signal instead of an
              // ambient one.
              createResponse: false,
              // Background noise can no longer cut the assistant off at
              // all, even in the brief window between a response starting
              // and our own mute-on-response.created handler taking
              // effect (or if session.mute() ever silently fails on a
              // transport that doesn't support it) - this is the actual
              // fix for noise interrupting playback, with the mute-cycle
              // logic below as a second, redundant layer of protection.
              interruptResponse: false,
            },
          },
          output: { format: "pcm16" },
        },
      },
    });

    // Renders the live conversation transcript. Assistant text depends on
    // output_audio.transcript being available per the docs - it may lag
    // slightly behind the actual audio.
    //
    // Also detects and prunes a duplicate greeting: if more than one
    // assistant message shows up before the visitor has said anything at
    // all, that's two independent greetings firing (the manual trigger
    // above and the API's own automatic turn-detection response both
    // responding at session start) - keep only the first, and actually
    // remove the extra one(s) from the real session history via
    // updateHistory, not just from the on-screen transcript, so the model
    // doesn't treat the duplicate as real conversation context either.
    // NOTE: the exact field name for a history item's unique id wasn't
    // confirmed in the docs provided - tries itemId then id defensively.
    let prunedDuplicateGreeting = false;
    session.on("history_updated", (history) => {
      if (!prunedDuplicateGreeting) {
        const firstUserIndex = history.findIndex((item) => item.type === "message" && item.role === "user");
        const leadingAssistantMessages = history.filter(
          (item, idx) =>
            item.type === "message" &&
            item.role === "assistant" &&
            (firstUserIndex === -1 || idx < firstUserIndex)
        );
        if (leadingAssistantMessages.length > 1) {
          prunedDuplicateGreeting = true;
          const idsToRemove = new Set(leadingAssistantMessages.slice(1).map((item) => item.itemId ?? item.id));
          appendToolLog(
            `detected ${leadingAssistantMessages.length} greetings before any visitor input - pruning ${idsToRemove.size} duplicate(s)`
          );
          session.updateHistory((currentHistory) =>
            currentHistory.filter((item) => !idsToRemove.has(item.itemId ?? item.id))
          );
          return; // updateHistory triggers another history_updated with the pruned list
        }
      }

      transcriptEl.innerHTML = "";
      for (const item of history) {
        if (item.type !== "message") continue;
        const text = (item.content || [])
          .map((c) => c.transcript || c.text || "")
          .filter(Boolean)
          .join(" ");
        if (text) appendTranscript(item.role, text);
      }
    });

    session.on("audio_interrupted", () => {
      setStatus("interrupted - listening…");
    });

    // create_booking has needsApproval: true, so it won't execute until
    // something calls session.approve()/session.reject(). A native
    // confirm() dialog is a quick way to test this for real without
    // building custom UI - swap for a proper in-app confirmation screen
    // in the actual kiosk frontend later.
    // NOTE: the exact shape of `request`/`request.approvalItem` wasn't
    // confirmed in the docs provided - this tries the most likely field
    // paths defensively; check the SDK's TypeScript types if this errors.
    session.on("tool_approval_requested", (_context, _agent, request) => {
      const approvalItem = request?.approvalItem ?? request;
      const toolName = approvalItem?.rawItem?.name ?? approvalItem?.name ?? "this action";
      const args = approvalItem?.rawItem?.arguments ?? approvalItem?.arguments ?? {};
      appendToolLog(`approval requested for ${toolName}: ${JSON.stringify(args)}`);

      const approved = window.confirm(`Approve ${toolName}?\n\n${JSON.stringify(args, null, 2)}`);
      if (approved) {
        session.approve(approvalItem);
        appendToolLog("approved");
      } else {
        session.reject(approvalItem);
        appendToolLog("rejected");
      }
    });

    session.on("error", (err) => {
      console.error("Realtime session error:", err);
      setStatus("error - check browser console");
    });

    // Raw PCM16 chunks from the model - schedule them ourselves via Web
    // Audio instead of relying on WebRTC's automatic playback.
    // NOTE: the exact field holding the audio bytes on this event wasn't
    // confirmed in the docs provided (shown only as `TransportLayerAudio`)
    // - tries a few likely field names, and logs the raw event once so we
    // can see its real shape if none of them work.
    let loggedAudioEventShape = false;
    session.on("audio", (event) => {
      const chunk = event?.data ?? event?.audio ?? event?.buffer ?? event?.chunk ?? event;
      const usable = chunk instanceof ArrayBuffer || ArrayBuffer.isView(chunk);
      if (!loggedAudioEventShape) {
        loggedAudioEventShape = true;
        console.log("Raw 'audio' event shape (first one only):", event, "keys:", event && Object.keys(event));
        if (!usable) console.warn("None of the tried field names held a usable ArrayBuffer - check the logged shape above.");
      }
      if (usable) playPCM16Chunk(chunk instanceof ArrayBuffer ? chunk : chunk.buffer, event?.responseId);
    });

    setStatus("connecting…");
    await session.connect({ apiKey: fetchEphemeralKey });

    setStatus("setting up microphone…");
    setupPlayback();
    await setupMicCapture(session);

    setStatus("connected - greeting…");
    muteBtn.disabled = false;
    disconnectBtn.disabled = false;

    // Mute the mic right away, before the greeting is even requested, so
    // there's no gap where the visitor's speech (or background noise)
    // could be captured before the general per-response handler below
    // takes over.
    micEnabled = false;
    muted = true;
    muteBtn.textContent = "Unmute";

    // Automatically mute the mic whenever the assistant is speaking, and
    // unmute once it's done - for EVERY turn, not just the greeting. This
    // is what actually prevents background noise (or audio bleeding back
    // in from speakers if not on headphones) from being picked up as a
    // false "interruption" mid-response. Trades away true talk-over-the-
    // assistant barge-in for reliable, noise-proof turn-taking - the right
    // tradeoff here since the reported problem is unwanted interruptions,
    // not a desire to literally cut the assistant off mid-sentence.
    //
    // NOTE: "response.created" / "response.done" are standard OpenAI
    // Realtime API event names marking a response starting/finishing - not
    // explicitly confirmed in the docs provided. If muting doesn't kick in
    // right as the assistant starts talking, log event.type here to find
    // the actual name your account/model version uses.
    //
    // Responses can genuinely overlap (e.g. a tool-call follow-up response
    // starting before the previous response's trailing audio has finished
    // playing) - so state is tracked per responseId (see responseAudioState
    // above), not with one shared flag that a second response.created
    // would incorrectly reset out from under the first.
    session.transport.on("*", (event) => {
      if (event?.type === "response.created") {
        const responseId = event?.response?.id;
        micEnabled = false;
        muted = true;
        muteBtn.textContent = "Unmute";
        setStatus("assistant speaking…");
        awaitingPlaybackFinish = true;
        getResponseState(responseId); // registers it as in-flight (done: false) without touching any other response already in progress
      } else if (event?.type === "response.done") {
        const responseId = event?.response?.id;
        const state = getResponseState(responseId);
        state.done = true;

        // If every response we're tracking (this one and any others still
        // in flight) has already finished playing all its chunks, we can
        // unmute right now - the per-chunk onended handler catches the
        // rest as chunks continue to finish naturally.
        //
        // No fallback timer here anymore - it was removed after testing
        // showed it firing prematurely against overlapping/chained
        // responses (each response.done armed its own independent timer,
        // none of which re-checked the actual current state before
        // firing, so a stale timer could force-unmute while other
        // responses' audio was still genuinely playing). The precise
        // tracking above (allResponsesFinished, driven by each chunk's
        // real 'ended' event) has proven reliable on its own.
        appendToolLog(`response ${responseId} finished generating (${state.pending} chunk(s) still playing for it)`);
        if (allResponsesFinished()) {
          onPlaybackFullyFinished();
        }
      } else if (event?.type === "input_audio_buffer.speech_stopped") {
        // The genuine, controlled trigger replacing createResponse: true -
        // VAD detected the visitor actually stopped talking, so NOW we ask
        // for a response. This can only fire from real detected speech
        // (we only send audio at all while micEnabled is true, i.e. while
        // we're actually listening), not from ambient noise during a
        // muted window - eliminating the unprompted-response chaining.
        try {
          session.transport.sendEvent({ type: "response.create" });
        } catch (err) {
          console.error("Could not trigger response after speech_stopped:", err);
        }
      }
    });

    // The assistant should start the conversation, not wait for the
    // visitor to speak first - VAD only triggers a response once it hears
    // the visitor's voice, so without this the session would just sit
    // there silently until someone talks. This manually asks for a
    // response using the documented raw transport event, based on the
    // instructions alone (no fake "user" message needed/injected).
    //
    // NOTE: this can end up firing alongside the API's own automatic
    // turn-detection response at session start, producing two separate
    // greetings. Rather than remove this (and risk losing the proactive
    // greeting entirely, since it's unconfirmed whether automatic behavior
    // alone reliably greets without it), the history_updated handler below
    // detects and prunes an extra assistant turn that arrives before the
    // visitor has said anything.
    try {
      session.transport.sendEvent({ type: "response.create" });
    } catch (err) {
      console.error("Could not trigger initial greeting:", err);
    }
  } catch (err) {
    console.error(err);
    setStatus("failed to connect - check browser console");
    connectBtn.disabled = false;
  }
});

muteBtn.addEventListener("click", () => {
  if (!session) return;
  muted = !muted;
  micEnabled = !muted;
  muteBtn.textContent = muted ? "Unmute" : "Mute";
  setStatus(muted ? "muted" : "connected - just start talking");
});

disconnectBtn.addEventListener("click", () => {
  if (!session) return;
  // NOTE: exact disconnect method name wasn't confirmed in the docs
  // provided - trying the most likely candidates defensively.
  session.close?.() ?? session.disconnect?.();
  session = null;
  teardownMicCapture();
  if (playbackAudioContext) {
    playbackAudioContext.close().catch(() => {});
    playbackAudioContext = null;
  }
  awaitingPlaybackFinish = false;
  responseAudioState.clear();
  currentVisitor = null;
  updateVisitorStatus();
  setStatus("disconnected");
  connectBtn.disabled = false;
  muteBtn.disabled = true;
  disconnectBtn.disabled = true;
});