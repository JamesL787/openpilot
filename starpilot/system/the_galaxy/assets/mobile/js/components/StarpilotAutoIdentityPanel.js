import { api } from "../api.js?v=starpilot-auto-recommended-1"
import { usePolling } from "../composables.js"
import { GxNotice } from "./GxNotice.js"
import { acceptsFile, describeIdentity, describeJob, uploadLabel } from "./starpilot_auto_identity_helpers.js?v=starpilot-auto-recommended-1"

function uploadWithProgress(file, onProgress) {
  return new Promise((resolve, reject) => {
    const form = new FormData()
    form.append("apk", file, file.name)
    const xhr = new XMLHttpRequest()
    xhr.open("POST", "/api/starpilot_auto/identity/upload")
    xhr.upload.onprogress = (event) => { if (event.lengthComputable) onProgress(event.loaded / event.total) }
    xhr.onload = () => {
      let data = {}
      try { data = JSON.parse(xhr.responseText || "{}") } catch { data = {} }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data)
      else reject(new Error(data.error || `Upload failed (${xhr.status})`))
    }
    xhr.onerror = () => reject(new Error("Upload failed; check the connection to the comma"))
    xhr.send(form)
  })
}

export const StarpilotAutoIdentityPanel = {
  name: "StarpilotAutoIdentityPanel",
  components: { GxNotice },
  props: { updateNoticeTarget: { type: String, default: "" } },
  data() {
    return { status: null, error: "", busy: "", uploadProgress: 0, fileName: "" }
  },
  created() {
    let first = true
    this.poll = usePolling(() => {
      const checkUpdates = first
      first = false
      return this.refresh(checkUpdates)
    }, { interval: 2000 })
    this.poll.start()
  },
  beforeUnmount() { this.poll?.destroy() },
  computed: {
    identity() { return describeIdentity(this.status) },
    job() { return describeJob(this.status?.job, Date.now() / 1000) },
    running() { return !!this.job?.running || !!this.busy },
    fileLabel() { return uploadLabel(this.status) },
    updateAvailable() { return !!this.status?.recommendation?.updateAvailable },
  },
  methods: {
    async refresh(checkUpdates = false) {
      try {
        this.status = await api.getStarpilotAutoIdentity(checkUpdates === true)
      } catch (e) {
        this.error = e?.message || "Could not read the Starpilot Auto identity"
      }
    },
    chooseFile() { this.$refs.file?.click() },
    async installRecommended() {
      if (this.running) return
      this.error = ""
      this.busy = "recommended"
      try {
        await api.installRecommendedStarpilotAutoIdentity()
        await this.refresh()
      } catch (e) {
        this.error = e?.message || "Could not install the recommended version. Try again or install from a file."
      } finally {
        this.busy = ""
      }
    },
    async onFile(event) {
      const file = event.target.files?.[0]
      event.target.value = ""
      if (!file) return
      if (!acceptsFile(file.name)) {
        this.error = "Choose the Starpilot Auto .apk, .xapk or .apkm file."
        return
      }
      this.error = ""
      this.fileName = file.name
      this.busy = "upload"
      this.uploadProgress = 0
      try {
        await uploadWithProgress(file, (fraction) => { this.uploadProgress = fraction })
        await this.refresh()  // the upload's own reply is older than a poll that may have landed meanwhile
      } catch (e) {
        this.error = e?.message || "Upload failed"
      } finally {
        this.busy = ""
      }
    },
    async remove() {
      if (!window.confirm("Remove the Starpilot Auto identity from this comma? Starpilot Auto will stop working until you install it again.")) return
      this.busy = "remove"
      try {
        await api.removeStarpilotAutoIdentity()
        await this.refresh()
      } catch (e) {
        this.error = e?.message || "Could not remove the identity"
      } finally {
        this.busy = ""
      }
    },
  },
  template: `
    <div style="padding: var(--sp-3);">
      <GxNotice :tone="identity.tone === 'ok' ? 'info' : identity.tone"
                :icon="identity.tone === 'ok' ? 'bi-check-circle-fill' : 'bi-key-fill'"
                :title="identity.title" :text="identity.text" style="margin:0 0 var(--sp-2);" />
      <div v-if="status && status.installed && status.subject" class="gx-row__desc" style="margin:0 0 var(--sp-2); overflow-wrap:anywhere;">
        {{ status.subject }}<span v-if="status.imported"> · installed {{ String(status.imported).slice(0, 10) }}</span>
      </div>

      <GxNotice v-if="job" :tone="job.tone === 'ok' ? 'info' : job.tone"
                :icon="job.running ? 'bi-hourglass-split' : job.tone === 'ok' ? 'bi-check-circle-fill' : 'bi-x-octagon-fill'"
                :text="job.text" style="margin:0 0 var(--sp-2);" />
      <GxNotice v-if="error" tone="danger" :text="error" style="margin:0 0 var(--sp-2);" />
      <Teleport :to="updateNoticeTarget || 'body'" :disabled="!updateNoticeTarget">
        <div v-if="updateAvailable" style="margin:0 0 var(--sp-2);">
          <GxNotice tone="info" icon="bi-arrow-up-circle"
                    title="Update to Starpilot Auto certificate available"
                    :text="'Version ' + status.recommendation.version + ' is available. Installed version: ' + status.package_version + '.'" />
          <template v-if="updateNoticeTarget">
            <button type="button" class="gx-btn" :disabled="running" @click="installRecommended">{{ running ? 'Updating…' : 'Update certificate' }}</button>
            <p v-if="job?.text || error" role="status" class="gx-row__desc">{{ error || job.text }}</p>
          </template>
        </div>
      </Teleport>
      <p v-if="!updateAvailable && status?.recommendation?.version && status?.installed && !status?.package_version"
         class="gx-row__desc">Recommended version: {{ status.recommendation.version }}. Your manually installed version is unknown.</p>
      <p v-if="status?.recommendation?.error" class="gx-row__desc">{{ status.recommendation.error }}</p>

      <h4 style="margin:12px 0 8px;">{{ updateAvailable ? 'Update' : status && (status.installed || status.expired) ? 'Renew' : 'Install' }}</h4>
      <p class="gx-row__desc" style="margin:0 0 12px;">Download the recommended installer package directly on the comma.</p>
      <button type="button" class="gx-btn" :disabled="running || !status" @click="installRecommended" style="margin:0 0 12px;">
        <i class="bi bi-download"></i> {{ busy === 'recommended' ? 'Starting…' : updateAvailable ? 'Update Starpilot Auto' : 'Install recommended version' }}
      </button>
      <p class="gx-row__desc" style="margin:0 0 12px;">Requires internet on the comma. If installation fails, your current identity is kept.</p>

      <details style="margin:0 0 12px;">
      <summary style="cursor:pointer; color:var(--text-muted);">Manual installation</summary>
      <p class="gx-row__desc" style="margin:8px 0 12px;">On this phone or computer, upload the XAPK or APK from an APK mirror.
        Make sure it is the app itself, not a mirror's store installer.</p>

      <input ref="file" type="file" accept=".apk,.xapk,.apkm,application/vnd.android.package-archive" style="display:none;" @change="onFile" />
      <div style="display:flex; gap:8px; flex-wrap:wrap; margin:0 0 12px;">
        <button type="button" class="gx-btn" :disabled="running" @click="chooseFile">
          <i class="bi bi-upload"></i> {{ busy === 'upload' ? 'Uploading ' + Math.round(uploadProgress * 100) + '%' : fileLabel }}
        </button>
        <button type="button" class="gx-btn gx-btn--tonal" :disabled="!!busy" @click="refresh"><i class="bi bi-arrow-clockwise"></i> Refresh</button>
      </div>

      </details>

      <div v-if="status && (status.installed || status.expired || status.error)" style="display:flex; justify-content:flex-end;">
        <button type="button" class="gx-btn gx-btn--danger" :disabled="running" @click="remove"><i class="bi bi-trash"></i> Remove Identity</button>
      </div>
    </div>
  `,
}
