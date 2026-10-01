import { api } from "../api.js"
import { isFirestarOrigin } from "../components/PwaInstallSection.js"

// The streamer viewer runs on its own origin (STREAM_PORT, default 8091),
// so it cannot share Galaxy's same-origin DOM/style injection used by the
// generic embed component. It is embedded in an iframe with a validated
// postMessage handshake instead.
const MESSAGE_SOURCE = "starpilot-ui-stream"
const READY_TIMEOUT_MS = 5000
// The UI publishes UiStreamState at 2 Hz, so readiness normally lands well
// inside this.
const START_POLL_MS = 300
const START_TIMEOUT_MS = 10000
// A viewer-reported failure re-requests the stream, because the streamer
// self-stops when the last viewer leaves (a backgrounded tab included). Bounded
// so an unreachable comma cannot turn into a request loop.
const VERIFY_COOLDOWN_MS = 5000
const MAX_AUTO_RESTARTS = 3
const GALAXY_PORT = 8082

const LOCAL_ONLY_NOTICE = "Can't connect to your comma's live UI. Connect this phone or computer to the same local network (LAN) as your comma, then try again. Live UI is available locally and is not carried through Galaxy remote access. If you're already on the same network, check that UI streaming is enabled and the comma is reachable."

// Cover the whole operation, including response-body parsing. Abort the fetch
// and reject independently so a stalled transport cannot strand the page.
async function timedRequest(operation, timeout = 3000) {
  const controller = new AbortController()
  let timer
  try {
    return await Promise.race([
      operation({ signal: controller.signal, cache: "no-store" }),
      new Promise((resolve, reject) => {
        timer = setTimeout(() => {
          controller.abort()
          reject(new Error("The comma request timed out. Try again."))
        }, Math.max(0, timeout))
      }),
    ])
  } finally {
    clearTimeout(timer)
  }
}

function hostLiteral(host) {
  const raw = String(host || "").trim()
  if (!raw || raw === "unknown") return ""
  return raw.includes(":") && !raw.startsWith("[") ? "[" + raw + "]" : raw
}

function buildViewerUrl(host, port, parentOrigin) {
  const literal = hostLiteral(host)
  if (!literal || !port) return ""
  const base = "http://" + literal + ":" + port + "/"
  return parentOrigin ? base + "?parentOrigin=" + parentOrigin : base
}

function buildGalaxyLocalUrl(host) {
  const literal = hostLiteral(host)
  if (!literal) return ""
  return "http://" + literal + ":" + GALAXY_PORT + "/#/ui-stream"
}

function originOf(url) {
  try {
    return new URL(url).origin
  } catch (e) {
    return ""
  }
}

export const UiStream = {
  name: "UiStream",
  data() {
    return {
      loading: true,
      remote: isFirestarOrigin(),
      streamPort: null,
      lanIp: "",
      galaxyLocalUrl: "",
      viewerHost: "",
      viewerUrl: "",
      viewerOrigin: "",
      state: "idle",
      detail: "",
      iframeKey: 0,
      readyTimer: null,
      startTimer: null,
      starting: false,
      baseSequence: 0,
      autoRestarts: 0,
      lastVerify: 0,
      verifying: false,
      expanded: false,
      previousOverflow: null,
      notice: LOCAL_ONLY_NOTICE,
    }
  },
  computed: {
    isHttps() {
      return window.location.protocol === "https:"
    },
    canEmbed() {
      return !!this.viewerUrl && !this.isHttps && !this.remote
    },
    // The viewer page is served by the streamer, so hold the iframe back until
    // the UI process reports a bound listener.
    showFrame() {
      return this.canEmbed && !this.starting && this.state !== "starting"
    },
    stateLabel() {
      switch (this.state) {
        case "ready": return "Connected"
        case "paused": return "Screen asleep"
        case "error": return "Not connected"
        case "starting": return "Starting…"
        case "disabled": return "Streaming off"
        case "remote": return "Local only"
        default: return "Connecting…"
      }
    },
    stateStyle() {
      // Colour the chip per state; the base class stays gx-chip.
      switch (this.state) {
        case "ready": return "background:var(--success); color:var(--black);"
        case "paused": return "background:var(--warning, #b26a00); color:var(--black);"
        case "error": return "background:var(--danger, #b3261e); color:var(--white, #fff);"
        case "starting": return "background:var(--surface-variant, rgba(255,255,255,0.12)); color:var(--text-muted);"
        case "disabled": return "background:var(--surface-variant, rgba(255,255,255,0.12)); color:var(--text-muted);"
        default: return "background:var(--surface-variant, rgba(255,255,255,0.12)); color:var(--text-muted);"
      }
    },
  },
  async mounted() {
    window.addEventListener("message", this.onMessage)
    document.addEventListener("visibilitychange", this.onVisibility)
    await this.resolve()
  },
  beforeUnmount() {
    this.teardown()
  },
  methods: {
    async resolve() {
      this.loading = true
      let status = null
      try {
        status = await timedRequest((opts) => api.getDeviceStatus(opts))
      } catch (e) {
        status = null
      }
      this.lanIp = status?.lanIp || ""
      const port = Number(status?.streamPort)
      this.streamPort = Number.isFinite(port) && port > 0 ? port : null

      const localHost = this.remote ? this.lanIp : window.location.hostname
      this.viewerHost = localHost && localHost !== "unknown" ? localHost : ""
      this.galaxyLocalUrl = this.remote ? buildGalaxyLocalUrl(this.lanIp) : ""
      // parentOrigin lets the viewer target this exact Galaxy origin instead of "*".
      const parentOrigin = encodeURIComponent(window.location.origin)
      this.viewerUrl = buildViewerUrl(localHost, this.streamPort, parentOrigin)
      this.viewerOrigin = originOf(this.viewerUrl)

      if (this.remote) {
        this.state = "remote"
      } else if (!this.streamPort) {
        this.state = "disabled"
      } else if (!localHost) {
        this.state = "error"
      } else if (this.isHttps) {
        this.state = "error"
        this.detail = "This page is HTTPS, so the local HTTP viewer can't be embedded."
      } else {
        this.state = "starting"
      }
      this.loading = false
      if (this.canEmbed) await this.requestStart()
    },
    // Opening this page is the whole interaction: ask the comma to start its
    // streamer, wait until the UI process reports a bound listener, then let
    // the iframe connect. The viewer itself is served by the streamer, so the
    // iframe must not load before that listener exists.
    async requestStart() {
      this.setExpanded(false)
      this.clearStartPoll()
      this.state = "starting"
      this.detail = ""
      this.starting = true
      const deadline = Date.now() + START_TIMEOUT_MS
      let response = null
      try {
        response = await timedRequest((opts) => api.startUiStream(opts), Math.min(3000, deadline - Date.now()))
      } catch (e) {
        this.starting = false
        this.state = "error"
        this.detail = e?.message || "The comma did not accept the start request."
        return
      }
      // Baseline from the moment of the request, so a failure left over from an
      // earlier attempt is not mistaken for this one.
      this.baseSequence = Number(response?.streamSequence) || 0
      await this.waitForReady(deadline)
    },
    // The UI process publishes UiStreamState after it has bound the listener on
    // its render thread. Consuming UiStreamRequested only proves the request was
    // seen, so that is deliberately not what this waits for.
    async waitForReady(deadline = Date.now() + START_TIMEOUT_MS) {
      while (this.starting && Date.now() < deadline) {
        await new Promise((resolve) => {
          this.startTimer = setTimeout(resolve, Math.min(START_POLL_MS, Math.max(0, deadline - Date.now())))
        })
        if (!this.starting) return
        if (Date.now() >= deadline) break
        let status = null
        try {
          status = await timedRequest((opts) => api.getDeviceStatus(opts), Math.min(3000, deadline - Date.now()))
        } catch (e) {
          continue
        }
        if (!status) continue
        if (status.streamState === "running") {
          this.starting = false
          this.state = "connecting"
          // Reload the viewer now that something serves it; a refused load
          // earlier in this page's life must not be left on screen.
          this.iframeKey += 1
          this.$nextTick(() => this.armReadyTimer())
          return
        }
        const sequence = Number(status.streamSequence) || 0
        if (status.streamState === "error" && sequence > this.baseSequence) {
          this.starting = false
          this.state = "error"
          this.detail = status.streamDetail
            ? "The comma could not start its streamer: " + status.streamDetail
            : "The comma could not start its streamer."
          return
        }
      }
      if (!this.starting) return
      this.starting = false
      this.state = "error"
      this.detail = "The comma did not pick up the start request. Is the UI running?"
    },
    clearStartPoll() {
      this.starting = false
      if (this.startTimer) {
        clearTimeout(this.startTimer)
        this.startTimer = null
      }
    },
    // The streamer self-stops 60 s after its last viewer, and a backgrounded
    // tab drops the viewer, so coming back can find nothing listening. Check
    // the published state and start it again instead of making the user press
    // Retry. `bounded` limits the viewer-driven path to a few attempts.
    async verifyReady(bounded) {
      if (this.starting || this.verifying || !this.canEmbed) return
      const now = Date.now()
      if (bounded && (this.autoRestarts >= MAX_AUTO_RESTARTS || now - this.lastVerify < VERIFY_COOLDOWN_MS)) return
      this.lastVerify = now
      this.verifying = true
      let status = null
      try {
        status = await timedRequest((opts) => api.getDeviceStatus(opts))
      } catch (e) {
        status = null
      } finally {
        this.verifying = false
      }
      if (!status || this.starting) return
      // Still bound: the viewer reconnects on its own, so leave it alone.
      if (status.streamState === "running") return
      if (bounded) this.autoRestarts += 1
      this.requestStart()
    },
    onVisibility() {
      // Returning to the tab is a user action: not rate limited, and it hands
      // back the automatic attempts a previous failure used up.
      if (document.hidden) return
      this.autoRestarts = 0
      this.verifyReady(false)
    },
    armReadyTimer() {
      this.clearReadyTimer()
      this.readyTimer = setTimeout(() => {
        if (this.state === "connecting") {
          this.state = "error"
          this.detail = "The viewer did not respond in time."
        }
      }, READY_TIMEOUT_MS)
    },
    clearReadyTimer() {
      if (this.readyTimer) {
        clearTimeout(this.readyTimer)
        this.readyTimer = null
      }
    },
    onMessage(event) {
      const data = event?.data
      if (!data || data.source !== MESSAGE_SOURCE) return
      const frame = this.$refs.frame
      if (!frame || event.source !== frame.contentWindow) return
      if (this.viewerOrigin && event.origin !== this.viewerOrigin) return

      if (data.type === "fullscreen") {
        this.setExpanded(data.expanded === true)
        return
      }
      this.clearReadyTimer()
      if (data.type === "error") {
        this.state = "error"
        this.detail = data.message || "The stream reported an error."
        this.verifyReady(true)
      } else if (data.type === "status" || data.type === "ready") {
        if (data.state === "paused") this.state = "paused"
        else if (data.state === "ready") this.state = "ready"
        else if (data.state === "error") this.state = "error"
        else this.state = "connecting"
        this.detail = ""
        // A viewer that cannot reach the streamer reports "error", which is the
        // signal that it self-stopped while this tab was in the background.
        if (data.state === "error") this.verifyReady(true)
        else if (data.state === "ready") this.autoRestarts = 0
      }
    },
    retry() {
      this.clearReadyTimer()
      this.autoRestarts = 0
      if (!this.canEmbed) {
        this.resolve()
        return
      }
      // Re-ask: the streamer self-stops when idle, so a retry after a long
      // pause has to start it again rather than just reloading the iframe.
      this.requestStart()
    },
    setExpanded(value) {
      const dialog = this.$refs.viewerDialog
      if (value !== this.expanded && dialog) {
        dialog.close()
        if (value) {
          dialog.showModal()
          this.previousOverflow = document.body.style.overflow
          document.body.style.overflow = "hidden"
        } else {
          dialog.show()
        }
      }
      if (!value && this.previousOverflow !== null) {
        document.body.style.overflow = this.previousOverflow
        this.previousOverflow = null
      }
      this.expanded = value
      this.$refs.frame?.contentWindow?.postMessage({
        source: "starpilot-ui-stream-wrapper", type: "fullscreen", expanded: value,
      }, this.viewerOrigin)
    },
    teardown() {
      this.setExpanded(false)
      this.clearReadyTimer()
      this.clearStartPoll()
      window.removeEventListener("message", this.onMessage)
      document.removeEventListener("visibilitychange", this.onVisibility)
    },
  },
  template: `
    <div class="gx-view">
      <h2 style="margin-top:0;">Live UI</h2>

      <div v-if="loading" class="gx-loading">Checking stream status…</div>

      <template v-else>
        <section class="gx-card">
          <div style="padding:var(--sp-4); display:grid; gap:12px;">
            <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
              <span class="gx-chip" :style="stateStyle">{{ stateLabel }}</span>
              <span v-if="viewerHost" style="color:var(--text-muted); word-break:break-all;">{{ viewerHost }}</span>
            </div>

            <div v-if="state === 'remote'" class="gx-alert gx-alert--warn" style="border:none;margin:0;">
              <i class="bi bi-satellite gx-alert__icon"></i>
              <div class="gx-alert__body">
                <strong>Live UI is local only</strong>
                <span>{{ notice }}</span>
              </div>
            </div>

            <div v-else-if="state === 'disabled'" class="gx-alert gx-alert--warn" style="border:none;margin:0;">
              <i class="bi bi-broadcast gx-alert__icon"></i>
              <div class="gx-alert__body">
                <strong>Live UI is switched off</strong>
                <span>Live UI has been switched off on this comma with <code>STREAM=0</code>. Remove that from <code>launch_env.sh</code> and restart the UI to use it again.</span>
              </div>
            </div>

            <div v-else-if="state === 'paused'" class="gx-alert gx-alert--warn" style="border:none;margin:0;">
              <i class="bi bi-moon-stars gx-alert__icon"></i>
              <div class="gx-alert__body">
                <strong>Screen asleep</strong>
                <span>The comma display is off. Streaming keeps the panel dark, so this normally resumes on its own; if it does not, touch the comma screen to wake it.</span>
              </div>
            </div>

            <div v-else-if="state === 'error'" class="gx-alert gx-alert--warn" style="border:none;margin:0;">
              <i class="bi bi-wifi-off gx-alert__icon"></i>
              <div class="gx-alert__body">
                <strong>{{ detail || 'Not connected' }}</strong>
                <span v-if="!detail">{{ notice }}</span>
              </div>
            </div>

            <!-- Deliberately no "sandbox" attribute: sandboxing without
                 allow-same-origin puts the viewer in an opaque origin, so
                 event.origin becomes "null" and the validated handshake check
                 would reject every message. Do not add it as drive-by
                 hardening.
                 NOTE: this template is a JavaScript template literal. A
                 backtick anywhere in it ends the string and breaks module
                 parsing for all of Galaxy, so never use one here. -->
            <dialog
              v-if="showFrame"
              ref="viewerDialog"
              open
              aria-label="Live UI viewer"
              @cancel.prevent="setExpanded(false)"
              :style="expanded
                ? 'position:fixed; inset:0; margin:0; width:100vw; height:100dvh; max-width:none; max-height:none; padding:0; border:0; background:#000;'
                : 'position:static; margin:0; width:100%; height:clamp(420px,72svh,760px); max-width:none; max-height:none; padding:0; border:1px solid var(--border); border-radius:10px; background:#000;'"
            >
            <iframe
              :key="iframeKey"
              ref="frame"
              :src="viewerUrl"
              title="StarPilot Live UI"
              style="display:block; width:100%; height:100%; border:0; background:#000;"
              allow="fullscreen"
              allowfullscreen
            ></iframe>
            </dialog>

            <div style="display:flex; gap:10px; flex-wrap:wrap;">
              <button type="button" class="gx-btn gx-btn--tonal" @click="retry">
                <i class="bi bi-arrow-clockwise"></i> Retry
              </button>
              <a v-if="viewerUrl && !canEmbed" class="gx-btn gx-btn--tonal" :href="viewerUrl" target="_blank" rel="noopener">
                <i class="bi bi-box-arrow-up-right"></i> Open Viewer
              </a>
              <a v-if="galaxyLocalUrl" class="gx-btn gx-btn--tonal" :href="galaxyLocalUrl">
                <i class="bi bi-box-arrow-up-right"></i> Open Galaxy Locally
              </a>
            </div>
          </div>
        </section>

      </template>
    </div>
  `,
}
