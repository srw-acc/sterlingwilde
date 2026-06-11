"""Generate a self-contained review HTML for a session.

The output is a single `outputs/review.html` file with embedded CSS, JS, and
base64-encoded frame thumbnails. It opens by double-click, can be emailed, and
hosts the human review workflow:

  - timeline-oriented moment list with screenshots and transcripts
  - inline editing (change kind/sentiment, edit summary, suppress, approve)
  - cluster and issue browsing
  - "Download corrections" button that bundles edits as overrides.json

The reviewer downloads `overrides.json`, drops it into the session's outputs
directory, and re-runs `ux-intel synthesize <session-dir> --apply-overrides`
to regenerate the synthesis with their corrections baked in.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from .schemas import (
    Cluster,
    FeedbackKind,
    IssueDraft,
    MomentSet,
    ObservationSet,
    Sentiment,
    SessionState,
    VideoMetadata,
)
from .session import Session


def generate(session: Session) -> Path:
    """Build review.html from the current session artifacts. Returns its path.

    Works at any stage of the pipeline:
      - after `align`: shows the transcript + screenshot timeline ("preview" mode)
      - after `synthesize`: adds observation cards, clusters, issues, and edit controls
    """
    state = session.state()
    moments = MomentSet.model_validate_json(session.moments_path.read_text()).moments

    observations = []
    if session.observations_path.exists():
        observations = ObservationSet.model_validate_json(
            session.observations_path.read_text()
        ).observations

    clusters: list[Cluster] = []
    issues: list[IssueDraft] = []
    if session.clusters_path.exists():
        raw = json.loads(session.clusters_path.read_text())
        clusters = [Cluster.model_validate(c) for c in raw.get("clusters", [])]
    if session.issues_path.exists():
        raw = json.loads(session.issues_path.read_text())
        issues = [IssueDraft.model_validate(i) for i in raw.get("issues", [])]

    metadata: VideoMetadata | None = None
    if session.metadata_path.exists():
        metadata = VideoMetadata.model_validate_json(session.metadata_path.read_text())

    frames_b64 = _embed_frames(session.root, observations, moments)

    payload = {
        "session": _session_payload(state, metadata, len(moments), len(observations)),
        "moments": [m.model_dump() for m in moments],
        "observations": [o.model_dump(mode="json") for o in observations],
        "clusters": [c.model_dump(mode="json") for c in clusters],
        "issues": [i.model_dump() for i in issues],
        "frames_b64": frames_b64,
        "kinds": [k.value for k in FeedbackKind],
        "sentiments": [s.value for s in Sentiment],
        "preview": len(observations) == 0,
    }

    html = _PAGE_TEMPLATE.format(
        title=f"UX Review — {state.session_id}",
        data_json=_safe_json(payload),
        styles=_STYLES,
        script=_SCRIPT,
    )
    session.review_html_path.write_text(html, encoding="utf-8")
    return session.review_html_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _session_payload(
    state: SessionState,
    metadata: VideoMetadata | None,
    n_moments: int,
    n_observations: int,
) -> dict:
    return {
        "id": state.session_id,
        "source_video": state.source_video,
        "created_at": state.created_at.isoformat(),
        "duration_s": metadata.duration_s if metadata else None,
        "resolution": f"{metadata.width}x{metadata.height}" if metadata else None,
        "n_moments": n_moments,
        "n_observations": n_observations,
    }


def _embed_frames(session_root: Path, observations, moments) -> dict[str, str]:
    """Inline only the frames referenced by observations or moments — keeps the page small."""
    referenced: set[str] = set()
    for obs in observations:
        referenced.add(obs.frame_ref)
    for m in moments:
        referenced.add(m.primary_frame)

    out: dict[str, str] = {}
    for rel in sorted(referenced):
        frame_path = session_root / rel
        if not frame_path.exists():
            continue
        encoded = base64.standard_b64encode(frame_path.read_bytes()).decode("ascii")
        ext = frame_path.suffix.lower().lstrip(".")
        media = "jpeg" if ext == "jpg" else ext
        out[rel] = f"data:image/{media};base64,{encoded}"
    return out


def _safe_json(payload: dict) -> str:
    """JSON-encode for embedding in <script type=application/json>.

    The `</` escape avoids HTML parsers terminating the script block early on
    any string that happens to contain `</script>`.
    """
    return json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------

_STYLES = r"""
:root {
  --bg: #fafaf7;
  --fg: #1a1a1a;
  --muted: #6b6b6b;
  --border: #e0ddd6;
  --card: #ffffff;
  --shadow: 0 1px 2px rgba(0,0,0,0.04), 0 1px 8px rgba(0,0,0,0.04);
  --accent: #2a4d3a;
  --accent-soft: #e8efe9;
  --warn: #b35900;
  --danger: #b00020;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  background: var(--bg);
  color: var(--fg);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  font-size: 14px;
  line-height: 1.5;
}
code, .mono { font-family: "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace; }
header {
  position: sticky; top: 0; z-index: 10;
  background: var(--bg);
  border-bottom: 1px solid var(--border);
  padding: 16px 24px 0;
}
header .row1 {
  display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap;
}
header h1 { font-size: 16px; margin: 0; font-weight: 600; }
header .meta { color: var(--muted); font-size: 12px; }
nav { display: flex; gap: 16px; padding: 12px 0 0; }
nav a {
  color: var(--fg); text-decoration: none; padding: 6px 0;
  font-size: 13px; border-bottom: 2px solid transparent;
}
nav a.active { border-color: var(--accent); }
.timeline {
  position: relative;
  height: 28px;
  margin-top: 12px;
  background: var(--card);
  border-radius: 4px;
  border: 1px solid var(--border);
}
.tl-tick {
  position: absolute; top: 4px; bottom: 4px;
  width: 3px; border-radius: 1px;
  background: var(--muted); opacity: 0.4;
  cursor: pointer;
}
.tl-tick:hover { opacity: 1; background: var(--accent); }
main { padding: 24px; max-width: 1100px; margin: 0 auto; }
section { margin-bottom: 56px; }
section > h2 {
  font-size: 13px; text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--muted); margin: 0 0 16px;
}
.moment {
  display: grid; grid-template-columns: 220px 1fr;
  gap: 20px;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 16px;
  box-shadow: var(--shadow);
  scroll-margin-top: 140px;
}
.moment.suppressed { opacity: 0.4; }
.moment.approved { border-left: 3px solid var(--accent); }
.moment .frame { width: 100%; height: 130px; object-fit: cover; border-radius: 4px; background: #ddd; cursor: zoom-in; }
.moment .id { color: var(--muted); }
.moment .tline { font-size: 12px; color: var(--muted); margin-bottom: 6px; }
.moment .transcript {
  background: #f5f3ee; padding: 10px 12px; border-radius: 4px;
  font-size: 13px; color: #333; margin: 8px 0;
  border-left: 2px solid var(--border);
}
.row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 6px 0; }
.chip {
  display: inline-flex; align-items: center;
  font-size: 11px; padding: 3px 8px; border-radius: 999px;
  font-weight: 500; letter-spacing: 0.02em;
  background: #eee; color: #333;
}
.chip.k-bug { background: #fde6e6; color: #a01818; }
.chip.k-ux_friction { background: #fdedd6; color: #8a4a00; }
.chip.k-visual_inconsistency { background: #f0e0f3; color: #6b178a; }
.chip.k-data_quality { background: #fbe1ee; color: #8a1359; }
.chip.k-workflow { background: #dde9f7; color: #14528a; }
.chip.k-feature_request { background: #dff0e0; color: #1c5c20; }
.chip.k-praise { background: #ddefe9; color: #115d4d; }
.chip.k-uncertain { background: #ececec; color: #555; }
.chip.s-confident { background: var(--accent-soft); color: var(--accent); }
.chip.s-uncertain { background: #ececec; color: #555; }
.chip.s-frustrated, .chip.s-confused { background: #fde6e6; color: #a01818; }
.chip.s-impressed { background: #ddefe9; color: #115d4d; }
.chip.s-exploratory { background: #dde9f7; color: #14528a; }
.chip.s-neutral { background: #ececec; color: #555; }
.conf {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 11px; color: var(--muted);
}
.conf-bar {
  display: inline-block; width: 60px; height: 6px;
  background: #eee; border-radius: 3px; overflow: hidden;
}
.conf-bar > span {
  display: block; height: 100%; background: var(--accent);
}
.summary {
  font-size: 14px; line-height: 1.5; margin: 8px 0;
  border: 1px solid transparent; border-radius: 4px; padding: 6px 8px; margin-left: -8px;
}
.summary[contenteditable="true"]:hover, .summary[contenteditable="true"]:focus {
  border-color: var(--border); background: #fbfbf8; outline: none;
}
.summary.edited { border-color: var(--warn); background: #fff5e8; }
.controls { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 10px; }
.controls button, .controls select {
  font-size: 12px; padding: 4px 10px; border-radius: 4px;
  border: 1px solid var(--border); background: var(--card); color: var(--fg);
  cursor: pointer; font-family: inherit;
}
.controls button:hover, .controls select:hover { background: #f0eee8; }
.controls button.active { background: var(--accent); color: #fff; border-color: var(--accent); }
.controls button.warn { color: var(--warn); }
.controls button.danger { color: var(--danger); }
.basis {
  font-size: 12px; color: var(--muted); margin-top: 6px;
  font-style: italic;
}
.cluster {
  background: var(--card); border: 1px solid var(--border); border-radius: 8px;
  padding: 16px; margin-bottom: 12px; box-shadow: var(--shadow);
}
.cluster .theme { font-size: 16px; font-weight: 600; margin: 0 0 4px; }
.cluster .obs-refs { margin-top: 8px; }
.cluster .sev-high { color: var(--danger); }
.cluster .sev-medium { color: var(--warn); }
.cluster .sev-low { color: var(--muted); }
.issue {
  background: var(--card); border: 1px solid var(--border); border-radius: 8px;
  padding: 16px; margin-bottom: 12px; box-shadow: var(--shadow);
}
.issue .title { font-size: 15px; font-weight: 600; margin: 0 0 8px; }
.issue pre {
  background: #f5f3ee; padding: 12px; border-radius: 4px;
  font-size: 12px; overflow-x: auto; white-space: pre-wrap;
}
footer {
  position: sticky; bottom: 0;
  background: var(--bg); border-top: 1px solid var(--border);
  padding: 12px 24px;
  display: flex; justify-content: space-between; align-items: center;
  font-size: 13px;
}
footer button {
  background: var(--accent); color: #fff;
  border: none; padding: 8px 16px; border-radius: 4px;
  cursor: pointer; font-size: 13px;
}
footer button:disabled { background: #aaa; cursor: not-allowed; }
.lightbox {
  position: fixed; inset: 0; background: rgba(0,0,0,0.85);
  display: none; align-items: center; justify-content: center; z-index: 100;
  cursor: zoom-out;
}
.lightbox.show { display: flex; }
.lightbox img { max-width: 95vw; max-height: 95vh; border-radius: 4px; }
a.cite {
  color: var(--accent); text-decoration: none; font-family: "SF Mono", monospace;
  background: var(--accent-soft); padding: 1px 6px; border-radius: 3px;
  font-size: 12px;
}
a.cite:hover { background: var(--accent); color: #fff; }
"""

_SCRIPT = r"""
const data = JSON.parse(document.getElementById("data").textContent);

// Reviewer overrides — keyed by observation_id, lazily populated as the user edits.
const overrides = new Map();

function fmtTime(s) {
  if (s == null) return "—";
  const m = Math.floor(s / 60);
  const sec = (s - m * 60).toFixed(1);
  return `${m}:${sec.padStart(4, "0")}`;
}

function fmtDuration(s) {
  if (s == null) return "—";
  const m = Math.floor(s / 60);
  const sec = Math.floor(s - m * 60);
  return `${m}m ${sec}s`;
}

function getOverride(id) {
  if (!overrides.has(id)) overrides.set(id, { observation_id: id });
  return overrides.get(id);
}

function isEdited(obs) {
  const ov = overrides.get(obs.id);
  if (!ov) return false;
  return ov.suppressed || ov.approved
    || ov.kind != null || ov.sentiment != null
    || ov.summary != null || ov.confidence != null
    || ov.implementation_hint != null
    || (ov.reviewer_note != null && ov.reviewer_note !== "");
}

function pendingCount() {
  let n = 0;
  for (const ov of overrides.values()) {
    if (ov.suppressed || ov.approved
        || ov.kind != null || ov.sentiment != null
        || ov.summary != null || ov.confidence != null
        || ov.implementation_hint != null
        || (ov.reviewer_note != null && ov.reviewer_note !== "")) {
      n++;
    }
  }
  return n;
}

function refreshFooter() {
  const btn = document.getElementById("download-overrides");
  const n = pendingCount();
  btn.textContent = `Download corrections (${n})`;
  btn.disabled = n === 0;
}

function renderHeader() {
  const sess = data.session;
  document.getElementById("session-id").textContent = sess.id;
  const parts = [
    sess.source_video,
    sess.resolution,
    fmtDuration(sess.duration_s),
    `${sess.n_moments} moments`,
  ];
  if (data.preview) {
    parts.push("preview (no AI yet)");
  } else {
    parts.push(`${sess.n_observations} observations`);
  }
  document.getElementById("session-meta").textContent = parts.filter(Boolean).join(" · ");

  if (data.preview) {
    document.getElementById("clusters-section").style.display = "none";
    document.getElementById("issues-section").style.display = "none";
    document.getElementById("preview-banner").style.display = "block";
    document.getElementById("download-overrides").style.display = "none";
  }
}

function renderTimeline() {
  const tl = document.getElementById("timeline");
  const dur = data.session.duration_s;
  if (!dur) return;
  for (const m of data.moments) {
    const tick = document.createElement("div");
    tick.className = "tl-tick";
    const left = (m.start / dur) * 100;
    const width = Math.max(0.5, ((m.end - m.start) / dur) * 100);
    tick.style.left = `${left}%`;
    tick.style.width = `${width}%`;
    tick.title = `${m.id} — ${fmtTime(m.start)}–${fmtTime(m.end)}`;
    tick.addEventListener("click", () => {
      document.getElementById(`moment-${m.id}`).scrollIntoView({ behavior: "smooth", block: "start" });
    });
    tl.appendChild(tick);
  }
}

function renderMoments() {
  const list = document.getElementById("moments-list");
  const obsByMoment = new Map();
  for (const o of data.observations) obsByMoment.set(o.moment_id, o);

  for (const m of data.moments) {
    const obs = obsByMoment.get(m.id);
    list.appendChild(renderMomentCard(m, obs));
  }
}

function renderMomentCard(moment, obs) {
  const card = document.createElement("div");
  card.className = "moment";
  card.id = `moment-${moment.id}`;

  // Frame thumbnail
  const left = document.createElement("div");
  const img = document.createElement("img");
  img.className = "frame";
  img.src = data.frames_b64[moment.primary_frame] || "";
  img.alt = `frame at ${fmtTime(moment.start)}`;
  img.addEventListener("click", () => showLightbox(img.src));
  left.appendChild(img);
  const idLine = document.createElement("div");
  idLine.className = "tline";
  idLine.innerHTML = `<span class="mono id">${moment.id}</span> · ${fmtTime(moment.start)}–${fmtTime(moment.end)}`;
  left.appendChild(idLine);
  card.appendChild(left);

  // Right side
  const right = document.createElement("div");

  const transcript = document.createElement("div");
  transcript.className = "transcript";
  transcript.textContent = moment.transcript;
  right.appendChild(transcript);

  if (!obs) {
    if (!data.preview) {
      const empty = document.createElement("div");
      empty.className = "basis";
      empty.textContent = "(no observation produced for this moment)";
      right.appendChild(empty);
    }
    card.appendChild(right);
    return card;
  }

  // Chips row: kind, sentiment, confidence
  const chips = document.createElement("div");
  chips.className = "row";

  const kindChip = document.createElement("span");
  kindChip.className = `chip k-${obs.kind}`;
  kindChip.textContent = obs.kind.replace(/_/g, " ");
  chips.appendChild(kindChip);

  const sentChip = document.createElement("span");
  sentChip.className = `chip s-${obs.sentiment}`;
  sentChip.textContent = obs.sentiment;
  chips.appendChild(sentChip);

  const conf = document.createElement("span");
  conf.className = "conf";
  const bar = document.createElement("span");
  bar.className = "conf-bar";
  const fill = document.createElement("span");
  fill.style.width = `${Math.round(obs.confidence * 100)}%`;
  bar.appendChild(fill);
  conf.appendChild(bar);
  conf.appendChild(document.createTextNode(`${Math.round(obs.confidence * 100)}%`));
  chips.appendChild(conf);

  right.appendChild(chips);

  // Editable summary
  const summary = document.createElement("div");
  summary.className = "summary";
  summary.contentEditable = "true";
  summary.spellcheck = false;
  summary.textContent = obs.summary;
  summary.addEventListener("input", () => {
    const edited = summary.textContent.trim();
    const ov = getOverride(obs.id);
    if (edited === obs.summary) {
      delete ov.summary;
      summary.classList.remove("edited");
    } else {
      ov.summary = edited;
      summary.classList.add("edited");
    }
    refreshFooter();
  });
  right.appendChild(summary);

  // Basis
  if (obs.interpretation_basis) {
    const basis = document.createElement("div");
    basis.className = "basis";
    basis.textContent = `Why: ${obs.interpretation_basis}`;
    right.appendChild(basis);
  }

  // Implementation hint
  if (obs.implementation_hint) {
    const hint = document.createElement("div");
    hint.className = "basis";
    hint.textContent = `Suggested: ${obs.implementation_hint}`;
    right.appendChild(hint);
  }

  // Controls
  const controls = document.createElement("div");
  controls.className = "controls";

  const kindSelect = document.createElement("select");
  for (const k of data.kinds) {
    const opt = document.createElement("option");
    opt.value = k; opt.textContent = `kind: ${k}`;
    if (k === obs.kind) opt.selected = true;
    kindSelect.appendChild(opt);
  }
  kindSelect.addEventListener("change", () => {
    const ov = getOverride(obs.id);
    if (kindSelect.value === obs.kind) delete ov.kind;
    else ov.kind = kindSelect.value;
    kindChip.className = `chip k-${kindSelect.value}`;
    kindChip.textContent = kindSelect.value.replace(/_/g, " ");
    refreshFooter();
  });
  controls.appendChild(kindSelect);

  const sentSelect = document.createElement("select");
  for (const s of data.sentiments) {
    const opt = document.createElement("option");
    opt.value = s; opt.textContent = `sentiment: ${s}`;
    if (s === obs.sentiment) opt.selected = true;
    sentSelect.appendChild(opt);
  }
  sentSelect.addEventListener("change", () => {
    const ov = getOverride(obs.id);
    if (sentSelect.value === obs.sentiment) delete ov.sentiment;
    else ov.sentiment = sentSelect.value;
    sentChip.className = `chip s-${sentSelect.value}`;
    sentChip.textContent = sentSelect.value;
    refreshFooter();
  });
  controls.appendChild(sentSelect);

  const approveBtn = document.createElement("button");
  approveBtn.textContent = "Approve";
  approveBtn.addEventListener("click", () => {
    const ov = getOverride(obs.id);
    ov.approved = !ov.approved;
    if (ov.suppressed) { ov.suppressed = false; suppressBtn.classList.remove("active"); card.classList.remove("suppressed"); }
    approveBtn.classList.toggle("active", !!ov.approved);
    card.classList.toggle("approved", !!ov.approved);
    refreshFooter();
  });
  controls.appendChild(approveBtn);

  const suppressBtn = document.createElement("button");
  suppressBtn.textContent = "Suppress";
  suppressBtn.className = "warn";
  suppressBtn.addEventListener("click", () => {
    const ov = getOverride(obs.id);
    ov.suppressed = !ov.suppressed;
    if (ov.approved) { ov.approved = false; approveBtn.classList.remove("active"); card.classList.remove("approved"); }
    suppressBtn.classList.toggle("active", !!ov.suppressed);
    card.classList.toggle("suppressed", !!ov.suppressed);
    refreshFooter();
  });
  controls.appendChild(suppressBtn);

  const resetBtn = document.createElement("button");
  resetBtn.textContent = "Reset";
  resetBtn.className = "danger";
  resetBtn.addEventListener("click", () => {
    overrides.delete(obs.id);
    summary.textContent = obs.summary;
    summary.classList.remove("edited");
    kindSelect.value = obs.kind;
    sentSelect.value = obs.sentiment;
    kindChip.className = `chip k-${obs.kind}`;
    kindChip.textContent = obs.kind.replace(/_/g, " ");
    sentChip.className = `chip s-${obs.sentiment}`;
    sentChip.textContent = obs.sentiment;
    approveBtn.classList.remove("active");
    suppressBtn.classList.remove("active");
    card.classList.remove("approved", "suppressed");
    refreshFooter();
  });
  controls.appendChild(resetBtn);

  right.appendChild(controls);
  card.appendChild(right);
  return card;
}

function renderClusters() {
  const list = document.getElementById("clusters-list");
  if (data.clusters.length === 0) {
    list.innerHTML = "<p style='color:var(--muted)'>No clusters yet — run synthesize.</p>";
    return;
  }
  for (const c of data.clusters) {
    const div = document.createElement("div");
    div.className = "cluster";
    const sevClass = `sev-${c.severity}`;
    div.innerHTML = `
      <div class="theme">${escapeHtml(c.theme)}</div>
      <div class="row">
        <span class="chip k-${c.kind}">${c.kind.replace(/_/g, " ")}</span>
        <span class="${sevClass}">severity: ${c.severity}</span>
        <span class="conf"><span class="conf-bar"><span style="width:${Math.round(c.confidence * 100)}%"></span></span>${Math.round(c.confidence * 100)}%</span>
      </div>
      <p>${escapeHtml(c.summary)}</p>
    `;
    const refs = document.createElement("div");
    refs.className = "obs-refs";
    refs.innerHTML = "Evidence: ";
    for (const oid of c.observation_ids) {
      const a = document.createElement("a");
      a.href = `#moment-${oid.replace("o", "m")}`;
      a.className = "cite";
      a.textContent = oid;
      a.addEventListener("click", (ev) => {
        ev.preventDefault();
        const obs = data.observations.find(o => o.id === oid);
        if (obs) document.getElementById(`moment-${obs.moment_id}`).scrollIntoView({ behavior: "smooth", block: "start" });
      });
      refs.appendChild(a);
      refs.appendChild(document.createTextNode(" "));
    }
    div.appendChild(refs);
    list.appendChild(div);
  }
}

function renderIssues() {
  const list = document.getElementById("issues-list");
  if (data.issues.length === 0) {
    list.innerHTML = "<p style='color:var(--muted)'>No issues yet — run synthesize.</p>";
    return;
  }
  for (const i of data.issues) {
    const div = document.createElement("div");
    div.className = "issue";
    div.innerHTML = `
      <div class="title">${escapeHtml(i.title)}</div>
      <div class="row">
        ${i.labels.map(l => `<span class="chip">${escapeHtml(l)}</span>`).join("")}
      </div>
      <pre></pre>
    `;
    div.querySelector("pre").textContent = i.body_markdown;
    list.appendChild(div);
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function showLightbox(src) {
  const lb = document.getElementById("lightbox");
  lb.querySelector("img").src = src;
  lb.classList.add("show");
}
function hideLightbox() {
  document.getElementById("lightbox").classList.remove("show");
}

function downloadOverrides() {
  const payload = {
    overrides: Array.from(overrides.values()).filter(ov =>
      ov.suppressed || ov.approved
      || ov.kind != null || ov.sentiment != null
      || ov.summary != null || ov.confidence != null
      || ov.implementation_hint != null
      || (ov.reviewer_note != null && ov.reviewer_note !== "")
    ),
    edited_at: new Date().toISOString(),
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = "overrides.json";
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(url);
}

document.addEventListener("DOMContentLoaded", () => {
  renderHeader();
  renderTimeline();
  renderMoments();
  renderClusters();
  renderIssues();
  refreshFooter();
  document.getElementById("download-overrides").addEventListener("click", downloadOverrides);
  document.getElementById("lightbox").addEventListener("click", hideLightbox);
});
"""


_PAGE_TEMPLATE = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>{styles}</style>
</head>
<body>
<header>
  <div class="row1">
    <h1 id="session-id">…</h1>
    <span class="meta" id="session-meta">…</span>
  </div>
  <nav>
    <a href="#moments">Moments</a>
    <a href="#clusters">Clusters</a>
    <a href="#issues">Issues</a>
  </nav>
  <div class="timeline" id="timeline"></div>
</header>
<main>
  <div id="preview-banner" style="display:none;background:#fff5e8;border:1px solid #f0d090;padding:12px 16px;border-radius:6px;margin-bottom:16px;font-size:13px;color:#7a4500;">
    <strong>Preview mode.</strong> No AI analysis has run yet. This view shows the raw
    transcript and screenshots captured from the recording. Run
    <code>ux-intel pack &lt;session&gt; --stage analyze</code> (no-API) or
    <code>ux-intel analyze &lt;session&gt;</code> (API) to add observations, clusters, and issue drafts.
  </div>
  <section id="moments">
    <h2>Moments</h2>
    <div id="moments-list"></div>
  </section>
  <section id="clusters-section">
    <h2>Clusters</h2>
    <div id="clusters-list"></div>
  </section>
  <section id="issues-section">
    <h2>Draft Issues</h2>
    <div id="issues-list"></div>
  </section>
</main>
<footer>
  <span class="meta">Edits stay in your browser. Click Download to bundle them as overrides.json, drop into the session's outputs/ dir, then run <code>ux-intel synthesize &lt;session&gt; --apply-overrides</code>.</span>
  <button id="download-overrides" disabled>Download corrections (0)</button>
</footer>
<div class="lightbox" id="lightbox"><img alt=""></div>
<script id="data" type="application/json">{data_json}</script>
<script>{script}</script>
</body>
</html>
"""
