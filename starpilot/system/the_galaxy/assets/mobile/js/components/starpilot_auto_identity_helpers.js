// Display logic for the Starpilot Auto identity panel (tested from pytest via node).

const STAGES = {
  resolving: "Getting the recommended version",
  downloading: "Downloading to the comma",
  checking_package: "Checking the download",
  unpacking: "Preparing the file",
  reading: "Reading the file",
  searching: "Searching the file",
  decrypting: "Parsing the file",
  verifying: "Verifying",
  installing: "Installing",
}

function megabytes(bytes) {
  return (Number(bytes || 0) / (1024 * 1024)).toFixed(bytes >= 10 * 1024 * 1024 ? 0 : 1)
}

export function describeIdentity(status) {
  if (!status) return { tone: "info", title: "Checking…", text: "" }
  if (status.installed) {
    const date = String(status.expires || "").slice(0, 10)
    const days = Number(status.days_left)
    if (status.warning) return { tone: "warn", title: `Expires in ${days} day${days === 1 ? "" : "s"}`, text: `Valid until ${date}. Renew it with a newer Starpilot Auto app below.` }
    return { tone: "ok", title: "Installed", text: `Valid until ${date}${days >= 0 ? ` (${days} days left)` : ""}.` }
  }
  if (status.expired) return { tone: "danger", title: "Expired", text: "Starpilot Auto will not connect until you renew the identity with a newer Starpilot Auto app below." }
  if (status.error) return { tone: "danger", title: "Unusable", text: status.error }
  return { tone: "info", title: "Not installed", text: "Install the recommended package below, or provide your own Starpilot Auto app file." }
}

const RESULT_SECONDS = 120  // a finished import's success stays on screen this long

export function describeJob(job, now = Infinity) {
  if (!job || job.state === "idle") return null
  if (job.state === "done" && job.finished && now - job.finished > RESULT_SECONDS) return null
  if (job.state === "running") {
    let text = STAGES[job.stage] || "Working"
    if (job.stage === "downloading" && job.downloaded) {
      text += ` · ${megabytes(job.downloaded)}${job.total ? ` of ${megabytes(job.total)}` : ""} MB`
    }
    return { tone: "info", running: true, text: text + "…" }
  }
  if (job.state === "done") return { tone: "ok", running: false, text: job.message || "Identity installed." }
  return { tone: "danger", running: false, text: job.error || "Import failed." }
}

export function uploadLabel(status) {
  return status && (status.installed || status.expired) ? "Replace from File" : "Install from File"
}

export function acceptsFile(name) {
  return /\.(apk|xapk|apkm)$/i.test(String(name || ""))
}
