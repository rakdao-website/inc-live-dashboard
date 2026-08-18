import { RealtimeAgent, RealtimeSession, tool } from "@openai/agents/realtime";
import { z } from "zod";

// Points at your FastAPI backend's ephemeral-token endpoint
// (app/voice_agent/realtime_auth.py). Change if it runs elsewhere.
const BACKEND_BASE_URL = "http://127.0.0.1:8000";

const statusEl = document.getElementById("status");
const transcriptEl = document.getElementById("transcript");
const connectBtn = document.getElementById("connect-btn");
const muteBtn = document.getElementById("mute-btn");
const disconnectBtn = document.getElementById("disconnect-btn");

let session = null;
let muted = false;

// Set once lookup_visitor or register_visitor succeeds - later tools
// (create_booking, Step 4) will read this via closure, same as
// session["visitor_id"] does server-side in the text pipeline's
// _run_business_logic.
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

// response.done fires once the model finishes GENERATING a response, not
// once the audio has actually finished PLAYING through the speakers -
// those are two different moments, and the gap between them is why
// unmuting right on response.done comes in too early. Since WebRTC handles
// audio playback automatically (no direct "playback finished" event
// exposed), the best available fix is estimating spoken duration from the
// response's text length and delaying the unmute by that estimate.
function estimateSpeechDurationMs(text) {
  const FALLBACK_MS = 1500; // used if we can't extract any text at all
  if (!text) return FALLBACK_MS;
  const wordCount = text.trim().split(/\s+/).filter(Boolean).length;
  if (wordCount === 0) return FALLBACK_MS;
  const WORDS_PER_SECOND = 2.3; // rough average conversational TTS pace
  const SAFETY_BUFFER_MS = 500; // extra margin so we err toward unmuting late, not early
  const MIN_MS = 900;
  return Math.max(MIN_MS, (wordCount / WORDS_PER_SECOND) * 1000 + SAFETY_BUFFER_MS);
}

// Defensive extraction - the exact response.done payload shape wasn't
// confirmed in the docs provided. Tries the standard OpenAI Realtime API
// response object shape (response.output[].content[].transcript/text);
// falls back to an empty string (triggering the flat fallback delay above)
// if this doesn't match what actually comes through.
function extractResponseText(event) {
  try {
    const outputs = event?.response?.output ?? [];
    return outputs
      .flatMap((item) => item?.content ?? [])
      .map((c) => c?.transcript || c?.text || "")
      .filter(Boolean)
      .join(" ");
  } catch {
    return "";
  }
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
function buildInstructions(knowledgeBase) {
  const today = new Date().toISOString().slice(0, 10);
  return `
You are a friendly voice assistant for Innovation City, a business hub in RAK. Your job is to
greet visitors, sign them in (log in an existing customer or register a new visitor), answer
questions, and help with bookings. Today's date is ${today}.

**Greeting.** Greet the visitor warmly, briefly mention what you can help with (logging in or
registering, answering questions about Innovation City, and booking a meeting room, podcast
studio, or TikTok studio), and ask for their full name, their email, and whether they're an
existing customer or not. Ask for these together rather than one at a time, but only ask again
for whatever's still missing if they only give you part of it.

**Questions can come at any time.** No matter what you're in the middle of - collecting their name/
email/phone, waiting on a phone number confirmation, or partway through a booking - if the visitor
asks a genuine question, answer it right away using the knowledge base below. Never say you'll get
to it later, and never ignore it to stay on script. Once you've answered, pick back up exactly where
you left off (don't restart the greeting or re-ask for information you already have).

**Phone numbers are easy to mishear.** After the visitor gives their phone number, read it back to
confirm before calling lookup_visitor or register_visitor with it. Read it back the same way they
said it - if they said it digit-by-digit ("zero-five-eight-one..."), read it back digit-by-digit
too, not reformatted into groups - reformatting can itself introduce mistakes. Only call the tool
once they've confirmed it's correct - if they say it's wrong, listen again and read the new version
back too before proceeding. Never guess or "clean up" a number you're not confident you heard
correctly - always confirm first.

**Signing them in, once you know if they're an existing customer:**
- Existing customer -> you just need their phone number (not their name - lookup works by phone
  alone). Once you have it, call lookup_visitor. If it comes back found, greet them by name and let
  them know they're logged in, then ask how you can help. If it comes back not found, apologize
  briefly and let them know you'll register them instead, then call register_visitor with
  visitor_type "visitor" (you'll need their full name too in that case).
- Not an existing customer -> you need their full name and phone number (email optional - use it if
  they already gave it). Once you have both, call register_visitor with visitor_type "visitor". If
  it comes back with a conflict (phone already registered), call lookup_visitor instead to log them in.

Never call lookup_visitor or register_visitor again with the same information you already tried -
wait for new information (a corrected name/phone, or a decision to register instead) before retrying.

**Booking a room or service.** Once the visitor is signed in, you can book a meeting room, podcast
studio, or TikTok studio using create_booking. You need:
- Which room/service. If they just say "a meeting room" without saying which one, ask - there are
  two (meeting_room_1 and meeting_room_2). If they ask for the podcast studio or TikTok studio,
  there's only one of each - use podcast_studio / tiktok_studio directly, don't ask which.
- The date and time they want it.
- How long they need it, in minutes.

Gather whatever's missing across as many turns as it takes - don't demand everything at once if
they only mentioned some of it. Once you have all four, call create_booking. The visitor must be
signed in first (see above) - if they ask to book before that, get them signed in, then come back
to the booking.

If they ask an unrelated question while in the middle of booking, just answer it normally - they
can pick the booking back up afterward, there's no need to force them to finish first.

**Knowledge base - use this, and only this, for general questions about Innovation City** (opening
hours, room availability, amenities, wifi, studios, company info, etc.). If something isn't covered
here, say you're not sure and suggest asking a reception associate, rather than guessing:

${knowledgeBase}

After signing someone in, completing a booking, or answering a question, ask if there's anything
else you can help with. If they clearly say they're finished, thank them warmly and say goodbye.

Be concise, warm, and professional.
`.trim();
}

connectBtn.addEventListener("click", async () => {
  connectBtn.disabled = true;
  setStatus("loading knowledge base…");

  try {
    const knowledgeBase = await fetchKnowledgeBase();

    setStatus("minting ephemeral token…");

    const agent = new RealtimeAgent({
      name: "Innovation City Assistant",
      instructions: buildInstructions(knowledgeBase),
      tools: [lookupVisitorTool, registerVisitorTool, createBookingTool],
    });

    // NOTE: not passing an explicit `transport` here - per the docs,
    // OpenAIRealtimeWebRTC is described as "the simplest browser path" and
    // the browser examples don't show it being constructed explicitly, so
    // it's assumed to be the default when RealtimeSession runs in a
    // browser context. If audio doesn't work, this is the first thing to
    // check - may need `transport: new OpenAIRealtimeWebRTC()` explicitly.
    session = new RealtimeSession(agent, {
      model: "gpt-realtime-2.1",
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
              createResponse: true,
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

    setStatus("connecting…");
    await session.connect({ apiKey: fetchEphemeralKey });

    setStatus("connected - greeting…");
    muteBtn.disabled = false;
    disconnectBtn.disabled = false;

    // Mute the mic right away, before the greeting is even requested, so
    // there's no gap where the visitor's speech (or background noise)
    // could be captured before the general per-response handler below
    // takes over.
    try {
      session.mute(true);
      muted = true;
      muteBtn.textContent = "Unmute";
    } catch (err) {
      console.error("Could not mute for greeting (transport may not support mute):", err);
    }

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
    session.transport.on("*", (event) => {
      if (event?.type === "response.created") {
        try {
          session.mute(true);
          muted = true;
          muteBtn.textContent = "Unmute";
          setStatus("assistant speaking…");
        } catch (err) {
          console.error("Could not mute for assistant response:", err);
        }
      } else if (event?.type === "response.done") {
        const text = extractResponseText(event);
        const delayMs = estimateSpeechDurationMs(text);
        appendToolLog(
          `response finished generating (${text ? text.split(/\s+/).length + " words" : "no text extracted"}) - ` +
          `unmuting in ~${Math.round(delayMs)}ms to let audio finish playing`
        );
        setTimeout(() => {
          try {
            session.mute(false);
            muted = false;
            muteBtn.textContent = "Mute";
            setStatus("connected - your turn to talk");
          } catch (err) {
            console.error("Could not unmute after assistant response:", err);
          }
        }, delayMs);
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
  try {
    // NOTE: per the docs, mute()/muted are only implemented for some
    // transports (not plain OpenAIRealtimeWebSocket) - if this throws on
    // whatever transport ends up active, that's expected per the docs,
    // not a bug in this file.
    session.mute(muted);
    muteBtn.textContent = muted ? "Unmute" : "Mute";
    setStatus(muted ? "muted" : "connected - just start talking");
  } catch (err) {
    console.error("Mute not supported on this transport:", err);
  }
});

disconnectBtn.addEventListener("click", () => {
  if (!session) return;
  // NOTE: exact disconnect method name wasn't confirmed in the docs
  // provided - trying the most likely candidates defensively.
  session.close?.() ?? session.disconnect?.();
  session = null;
  setStatus("disconnected");
  connectBtn.disabled = false;
  muteBtn.disabled = true;
  disconnectBtn.disabled = true;
});