// ---------------------------------------------------------------------------
// Custom confirm/prompt modals (replace native browser confirm()/prompt())
// ---------------------------------------------------------------------------
function showConfirm(message, okLabel = "Delete") {
  return new Promise((resolve) => {
    document.getElementById("confirm-message").textContent = message;
    const okBtn = document.getElementById("btn-confirm-ok");
    const cancelBtn = document.getElementById("btn-confirm-cancel");
    const closeBtn = document.getElementById("confirm-close");
    const overlay = document.getElementById("modal-confirm");
    okBtn.textContent = okLabel;

    const cleanup = (result) => {
      overlay.classList.remove("is-open");
      okBtn.removeEventListener("click", onOk);
      cancelBtn.removeEventListener("click", onCancel);
      closeBtn.removeEventListener("click", onCancel);
      overlay.removeEventListener("click", onBackdrop);
      resolve(result);
    };
    const onOk = () => cleanup(true);
    const onCancel = () => cleanup(false);
    const onBackdrop = (e) => { if (e.target === overlay) cleanup(false); };

    okBtn.addEventListener("click", onOk);
    cancelBtn.addEventListener("click", onCancel);
    closeBtn.addEventListener("click", onCancel);
    overlay.addEventListener("click", onBackdrop);
    overlay.classList.add("is-open");
  });
}

function showPrompt(title, fields) {
  return new Promise((resolve) => {
    document.getElementById("prompt-title").textContent = title;
    const container = document.getElementById("prompt-fields-container");
    container.innerHTML = fields
      .map(
        (f) => `
        <label class="field-label">${escapeHtml(f.label)}</label>
        <input type="text" class="input prompt-field" data-field-id="${f.id}" value="${escapeHtml(f.value || "")}">`
      )
      .join("");

    const overlay = document.getElementById("modal-prompt");
    const okBtn = document.getElementById("btn-prompt-ok");
    const closeBtn = document.getElementById("prompt-close");

    const cleanup = (result) => {
      overlay.classList.remove("is-open");
      okBtn.removeEventListener("click", onOk);
      closeBtn.removeEventListener("click", onCancel);
      overlay.removeEventListener("click", onBackdrop);
      container.removeEventListener("keydown", onKeydown);
      resolve(result);
    };
    const onOk = () => {
      const result = {};
      container.querySelectorAll(".prompt-field").forEach((inp) => {
        result[inp.dataset.fieldId] = inp.value.trim();
      });
      cleanup(result);
    };
    const onCancel = () => cleanup(null);
    const onBackdrop = (e) => { if (e.target === overlay) cleanup(null); };
    const onKeydown = (e) => { if (e.key === "Enter") onOk(); };

    okBtn.addEventListener("click", onOk);
    closeBtn.addEventListener("click", onCancel);
    overlay.addEventListener("click", onBackdrop);
    container.addEventListener("keydown", onKeydown);
    overlay.classList.add("is-open");
    container.querySelector(".prompt-field")?.focus();
  });
}

function wireDeleteSubjectButtons(container) {
  container.querySelectorAll("[data-delete-subject-id]").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const card = btn.closest(".subject-card");
      const subjName = card ? card.querySelector(".subject-card-name").textContent : "this subject";
      const ok = await showConfirm(`Delete "${subjName}" and everything inside it? This can't be undone.`, "Delete");
      if (!ok) return;
      await del(`/api/subjects/${btn.dataset.deleteSubjectId}`);
      const activeView = document.querySelector(".view.is-active").id;
      if (activeView === "view-dashboard") renderDashboard();
      else renderLearningList();
    });
  });
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
const state = {
  categories: [],
  subjects: [],
  currentSubjectId: null,
  currentSubjectDetail: null,
  currentLevel2ForModal: null,
};

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------
async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: "Request failed" }));
    throw new Error(err.error || "Request failed");
  }
  return res.json();
}
const get = (path) => api(path);
const post = (path, body) => api(path, { method: "POST", body: JSON.stringify(body || {}) });
const put = (path, body) => api(path, { method: "PUT", body: JSON.stringify(body || {}) });
const del = (path) => api(path, { method: "DELETE" });

// ---------------------------------------------------------------------------
// View routing
// ---------------------------------------------------------------------------
function showView(name) {
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("is-active"));
  document.getElementById(`view-${name}`).classList.add("is-active");
  document.querySelectorAll(".nav-item").forEach((n) => n.classList.remove("is-active"));
  const navBtn = document.querySelector(`.nav-item[data-view="${name}"]`);
  if (navBtn) navBtn.classList.add("is-active");
}

document.querySelectorAll(".nav-item").forEach((btn) => {
  btn.addEventListener("click", () => {
    const view = btn.dataset.view;
    loadView(view);
  });
});

async function loadView(view) {
  showView(view === "subject" ? "subject" : view);
  if (view === "dashboard") await renderDashboard();
  if (view === "learning") await renderLearningList();
  if (view === "analytics") await renderAnalytics();
  if (view === "resources") await renderResources();
}

// ---------------------------------------------------------------------------
// Modal helpers
// ---------------------------------------------------------------------------
function openModal(id) { document.getElementById(id).classList.add("is-open"); }
function closeModal(id) { document.getElementById(id).classList.remove("is-open"); }

document.querySelectorAll("[data-close-modal]").forEach((btn) => {
  btn.addEventListener("click", () => btn.closest(".modal-overlay").classList.remove("is-open"));
});
document.querySelectorAll(".modal-overlay").forEach((overlay) => {
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) overlay.classList.remove("is-open");
  });
});

// ---------------------------------------------------------------------------
// Sidebar streak chip
// ---------------------------------------------------------------------------
async function refreshSidebarStreak() {
  try {
    const data = await get("/api/dashboard");
    document.getElementById("sidebar-streak-count").textContent = data.streaks.current_streak;
  } catch (e) { /* silent */ }
}

// ---------------------------------------------------------------------------
// DASHBOARD
// ---------------------------------------------------------------------------
async function renderDashboard() {
  const data = await get("/api/dashboard");

  const statGrid = document.getElementById("dashboard-stats");
  statGrid.innerHTML = `
    <div class="stat-card">
      <div class="stat-label">Total subjects</div>
      <div class="stat-value">${data.total_subjects}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Items completed</div>
      <div class="stat-value">${data.overall_progress.completed}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Overall progress</div>
      <div class="stat-value accent">${data.overall_progress.percent}%</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Current streak</div>
      <div class="stat-value ${data.streaks.current_streak === 0 ? "warn" : "accent"}">${data.streaks.current_streak}d</div>
    </div>
  `;

  const subjList = document.getElementById("dashboard-subjects");
  if (data.active_subjects.length === 0) {
    subjList.innerHTML = `<div class="empty-state"><p>No subjects yet. Head to My Learning to add one.</p></div>`;
  } else {
    subjList.innerHTML = data.active_subjects.map(subjectCardHTML).join("");
    subjList.querySelectorAll(".subject-card").forEach((card) => {
      card.addEventListener("click", () => openSubject(parseInt(card.dataset.id)));
    });
    wirePinButtons(subjList);
    wireDeleteSubjectButtons(subjList);
  }

  const continueCard = document.getElementById("continue-learning-card");
  if (data.continue_item) {
    const ci = data.continue_item;
    continueCard.style.display = "flex";
    continueCard.innerHTML = `
      <div>
        <div class="continue-card-label">Continue learning</div>
        <div class="continue-card-name">${escapeHtml(ci.level2_name)}</div>
        <div class="continue-card-path">${escapeHtml(ci.subject_name)} · ${escapeHtml(ci.level1_name)}</div>
      </div>
      <button class="btn btn-primary" id="btn-continue-go">Continue</button>
    `;
    document.getElementById("btn-continue-go").addEventListener("click", async () => {
      await openSubject(ci.subject_id);
      const block = document.querySelector(`.level1-block[data-l1-id="${ci.level1_id}"]`);
      if (block) {
        block.classList.add("is-open");
        block.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    });
  } else {
    continueCard.style.display = "none";
  }

  const flaggedList = document.getElementById("flagged-items");
  if (data.flagged_items.length === 0) {
    flaggedList.innerHTML = `<p class="field-hint">Nothing flagged. Star an item inside a subject to revisit it later.</p>`;
  } else {
    flaggedList.innerHTML = data.flagged_items
      .map(
        (f) => `
      <div class="badge-row" data-flagged-subject="${f.subject_id}" data-flagged-level1="${f.level1_id}" style="cursor:pointer;">
        <span class="badge-emoji">⭐</span>
        <div>
          <div class="badge-title">${escapeHtml(f.level2_name)}</div>
          <div class="badge-sub">${escapeHtml(f.subject_name)} · ${escapeHtml(f.level1_name)}</div>
        </div>
      </div>`
      )
      .join("");
    flaggedList.querySelectorAll("[data-flagged-subject]").forEach((row) => {
      row.addEventListener("click", async () => {
        await openSubject(parseInt(row.dataset.flaggedSubject));
        const block = document.querySelector(`.level1-block[data-l1-id="${row.dataset.flaggedLevel1}"]`);
        if (block) {
          block.classList.add("is-open");
          block.scrollIntoView({ behavior: "smooth", block: "center" });
        }
      });
    });
  }

  document.getElementById("streak-summary").textContent =
    `longest ${data.streaks.longest_streak}d`;
  renderActivityGrid(data.activity_calendar);

  const badgeList = document.getElementById("recent-badges");
  if (data.recent_badges.length === 0) {
    badgeList.innerHTML = `<p class="field-hint">No badges yet — finish a full section to earn one.</p>`;
  } else {
    badgeList.innerHTML = data.recent_badges
      .map(
        (b) => `
      <div class="badge-row">
        <span class="badge-emoji">🏆</span>
        <div>
          <div class="badge-title">${escapeHtml(b.level1_name)}</div>
          <div class="badge-sub">${escapeHtml(b.subject_name)}</div>
        </div>
        <span class="badge-date">${b.earned_date}</span>
      </div>`
      )
      .join("");
  }

  refreshSidebarStreak();
}

function subjectCardHTML(s) {
  const lastStudiedText = s.last_studied ? `Last studied ${s.last_studied}` : "Not started yet";
  return `
    <div class="subject-card" data-id="${s.id}">
      <div class="subject-card-top">
        <span class="subject-card-name">${escapeHtml(s.name)}</span>
        <div style="display:flex; align-items:center; gap:6px;">
          <span class="subject-card-pct">${s.progress.percent}%</span>
          <button class="pin-btn ${s.pinned ? "is-pinned" : ""}" data-pin-id="${s.id}" title="${s.pinned ? "Unpin" : "Pin to top"}">${s.pinned ? "★" : "☆"}</button>
          <button class="pin-btn" data-delete-subject-id="${s.id}" title="Delete subject">&#128465;</button>
        </div>
      </div>
      <span class="tag">${escapeHtml(s.category_name)}</span>
      <span class="tag">${escapeHtml(s.level2_label)}</span>
      <div class="progress-track"><div class="progress-fill" style="width:${s.progress.percent}%"></div></div>
      <div class="subject-card-meta">${s.progress.completed} / ${s.progress.total} ${escapeHtml(s.level2_label)}${s.progress.total === 1 ? "" : "s"} completed</div>
      <div class="last-studied">${lastStudiedText}</div>
    </div>`;
}

function wirePinButtons(container) {
  container.querySelectorAll("[data-pin-id]").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      await post(`/api/subjects/${btn.dataset.pinId}/pin`);
      const activeView = document.querySelector(".view.is-active").id;
      if (activeView === "view-dashboard") renderDashboard();
      else renderLearningList();
    });
  });
}

function renderActivityGrid(calendar) {
  const grid = document.getElementById("activity-grid");
  const days = [];
  const today = new Date();
  for (let i = 89; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(d.getDate() - i);
    const key = d.toISOString().slice(0, 10);
    days.push({ key, count: calendar[key] || 0 });
  }
  grid.innerHTML = days
    .map((d) => {
      let lvl = "";
      if (d.count >= 5) lvl = "lvl-4";
      else if (d.count >= 3) lvl = "lvl-3";
      else if (d.count >= 1) lvl = "lvl-2";
      return `<div class="activity-cell ${lvl}" title="${d.key}: ${d.count} completed"></div>`;
    })
    .join("");
}

// ---------------------------------------------------------------------------
// MY LEARNING — list
// ---------------------------------------------------------------------------
async function loadCategories() {
  state.categories = await get("/api/categories");
  const select = document.getElementById("select-category");
  select.innerHTML = state.categories.map((c) => `<option value="${c.id}">${escapeHtml(c.name)}</option>`).join("");
}

async function renderLearningList() {
  await loadCategories();
  state.subjects = await get("/api/subjects");

  const searchBox = document.getElementById("search-input");
  const resultsBox = document.getElementById("search-results");
  if (searchBox) searchBox.value = "";
  if (resultsBox) resultsBox.style.display = "none";

  const empty = document.getElementById("learning-empty");
  const groupsEl = document.getElementById("category-groups");
  groupsEl.style.display = "";

  if (state.subjects.length === 0) {
    empty.style.display = "block";
    groupsEl.innerHTML = "";
    return;
  }
  empty.style.display = "none";

  const byCategory = {};
  state.subjects.forEach((s) => {
    if (!byCategory[s.category_name]) byCategory[s.category_name] = [];
    byCategory[s.category_name].push(s);
  });

  groupsEl.innerHTML = Object.entries(byCategory)
    .map(
      ([catName, subs]) => `
      <div class="category-group">
        <div class="category-group-title">${escapeHtml(catName)}</div>
        <div class="subject-list">${subs.map(subjectCardHTML).join("")}</div>
      </div>`
    )
    .join("");

  groupsEl.querySelectorAll(".subject-card").forEach((card) => {
    card.addEventListener("click", () => openSubject(parseInt(card.dataset.id)));
  });
  wirePinButtons(groupsEl);
  wireDeleteSubjectButtons(groupsEl);
}

// ---------------------------------------------------------------------------
// SEARCH
// ---------------------------------------------------------------------------
let searchDebounce = null;
const searchInput = document.getElementById("search-input");
if (searchInput) {
  searchInput.addEventListener("input", () => {
    clearTimeout(searchDebounce);
    const q = searchInput.value.trim();
    const resultsBox = document.getElementById("search-results");
    const groupsEl = document.getElementById("category-groups");
    const emptyEl = document.getElementById("learning-empty");

    if (!q) {
      resultsBox.style.display = "none";
      groupsEl.style.display = "";
      if (state.subjects.length === 0) emptyEl.style.display = "block";
      return;
    }

    searchDebounce = setTimeout(async () => {
      const { results } = await get(`/api/search?q=${encodeURIComponent(q)}`);
      groupsEl.style.display = "none";
      emptyEl.style.display = "none";
      resultsBox.style.display = "block";

      if (results.length === 0) {
        resultsBox.innerHTML = `<div class="search-empty">No matches for "${escapeHtml(q)}".</div>`;
        return;
      }

      resultsBox.innerHTML = results
        .map((r) => {
          let pathLabel = "";
          if (r.type === "subject") pathLabel = escapeHtml(r.category_name);
          else if (r.type === "level1") pathLabel = `${escapeHtml(r.context_label)} in ${escapeHtml(r.subject_name)}`;
          else pathLabel = `${escapeHtml(r.context_label)} in ${escapeHtml(r.subject_name)}`;

          return `
            <div class="search-result-row" data-subject-id="${r.subject_id}" data-level1-id="${r.level1_id || ""}">
              <span>${r.type === "subject" ? "📘" : r.type === "level1" ? "📂" : "☑️"}</span>
              <div>
                <div class="search-result-label">${escapeHtml(r.label)}</div>
                <div class="search-result-path">${pathLabel}</div>
              </div>
            </div>`;
        })
        .join("");

      resultsBox.querySelectorAll(".search-result-row").forEach((row) => {
        row.addEventListener("click", async () => {
          const subjectId = parseInt(row.dataset.subjectId);
          await openSubject(subjectId);
          const l1Id = row.dataset.level1Id;
          if (l1Id) {
            const block = document.querySelector(`.level1-block[data-l1-id="${l1Id}"]`);
            if (block) {
              block.classList.add("is-open");
              block.scrollIntoView({ behavior: "smooth", block: "center" });
            }
          }
          searchInput.value = "";
          resultsBox.style.display = "none";
          groupsEl.style.display = "";
        });
      });
    }, 250);
  });
}

document.getElementById("btn-add-subject").addEventListener("click", () => openAddSubjectModal());
document.getElementById("btn-add-subject-empty").addEventListener("click", () => openAddSubjectModal());

async function openAddSubjectModal() {
  await loadCategories();
  document.getElementById("input-subject-name").value = "";
  document.getElementById("input-level1-label").value = "Milestone";
  document.getElementById("input-level2-label").value = "Module";
  document.getElementById("input-new-category").style.display = "none";
  document.getElementById("input-new-category").value = "";
  openModal("modal-add-subject");
}

document.getElementById("btn-new-category-toggle").addEventListener("click", () => {
  const input = document.getElementById("input-new-category");
  input.style.display = input.style.display === "none" ? "block" : "none";
});

document.getElementById("btn-submit-subject").addEventListener("click", async () => {
  const name = document.getElementById("input-subject-name").value.trim();
  const level1_label = document.getElementById("input-level1-label").value.trim() || "Milestone";
  const level2_label = document.getElementById("input-level2-label").value.trim() || "Module";
  const newCategoryName = document.getElementById("input-new-category").value.trim();

  if (!name) { alert("Please enter a subject name."); return; }

  let category_id;
  if (newCategoryName) {
    const cat = await post("/api/categories", { name: newCategoryName });
    category_id = cat.id;
  } else {
    category_id = parseInt(document.getElementById("select-category").value);
  }
  if (!category_id) { alert("Please choose or create a category."); return; }

  const subject = await post("/api/subjects", { name, category_id, level1_label, level2_label });
  closeModal("modal-add-subject");
  await openSubject(subject.id);
}); 

// ---------------------------------------------------------------------------
// SUBJECT DETAIL
// ---------------------------------------------------------------------------
async function openSubject(id) {
  state.currentSubjectId = id;
  showView("subject");
  document.querySelectorAll(".nav-item").forEach((n) => n.classList.remove("is-active"));
  document.querySelector('.nav-item[data-view="learning"]').classList.add("is-active");
  await renderSubjectDetail();
}

document.getElementById("btn-back-learning").addEventListener("click", () => loadView("learning"));

document.getElementById("btn-edit-subject").addEventListener("click", async () => {
  const s = state.currentSubjectDetail;
  const result = await showPrompt("Edit subject", [
    { id: "name", label: "Subject name", value: s.name },
    { id: "level1_label", label: "Level 1 label", value: s.level1_label },
    { id: "level2_label", label: "Level 2 label", value: s.level2_label },
  ]);
  if (!result) return;

  await put(`/api/subjects/${state.currentSubjectId}`, {
    name: result.name || s.name,
    level1_label: result.level1_label || s.level1_label,
    level2_label: result.level2_label || s.level2_label,
  });
  renderSubjectDetail();
});

async function renderSubjectDetail() {
  const s = await get(`/api/subjects/${state.currentSubjectId}`);
  state.currentSubjectDetail = s;

  document.getElementById("subject-detail-name").textContent = s.name;
  document.getElementById("subject-detail-sub").textContent = `${s.category_name} · ${s.level1_label} → ${s.level2_label}`;
  document.getElementById("level1-label-inline").textContent = s.level1_label;
  document.getElementById("subject-progress-fill").style.width = s.progress.percent + "%";
  document.getElementById("subject-progress-text").textContent =
    `${s.progress.completed} / ${s.progress.total} ${s.level2_label}${s.progress.total === 1 ? "" : "s"} · ${s.progress.percent}%`;

  const list = document.getElementById("level1-list");
  if (s.level1_items.length === 0) {
    list.innerHTML = `<div class="empty-state"><p>No ${s.level1_label.toLowerCase()}s yet. Add one manually or bulk import your syllabus.</p></div>`;
    return;
  }

  list.innerHTML = s.level1_items.map((l1) => level1BlockHTML(l1, s)).join("");
  wireSubjectDetailEvents(s);
}

function level1BlockHTML(l1, s) {
  return `
    <div class="level1-block" data-l1-id="${l1.id}">
      <div class="level1-head" data-toggle-l1="${l1.id}">
        <span class="level1-caret">&#9656;</span>
        <span class="level1-name">${escapeHtml(l1.name)}</span>
        <div class="level1-mini-track"><div class="level1-mini-fill" style="width:${l1.progress.percent}%"></div></div>
        <span class="level1-pct">${l1.progress.completed}/${l1.progress.total}</span>
        <div class="level1-actions">
          <button class="icon-btn" data-edit-l1="${l1.id}" title="Rename">&#9998;</button>
          <button class="icon-btn" data-delete-l1="${l1.id}" title="Delete">&#128465;</button>
        </div>
      </div>
      <div class="level2-list">
        ${l1.level2_items.map((l2) => level2RowHTML(l2, s)).join("")}
        <div class="add-level2-row">
          <button class="level1-footer-add" data-add-l2="${l1.id}">+ Add ${escapeHtml(s.level2_label.toLowerCase())}</button>
        </div>
      </div>
    </div>`;
}

function level2RowHTML(l2) {
  return `
    <div class="level2-row" data-l2-id="${l2.id}">
      <div class="checkbox ${l2.done ? "checked" : ""}" data-toggle-l2="${l2.id}"></div>
      <span class="level2-name ${l2.done ? "done" : ""}" data-open-l2="${l2.id}">${escapeHtml(l2.name)}</span>
      ${l2.notes ? `<span title="Has notes" class="level2-meta-btn" data-open-l2="${l2.id}">&#128221;</span>` : ""}
      ${l2.resources.length ? `<span title="${l2.resources.length} resource(s)" class="level2-meta-btn" data-open-l2="${l2.id}">&#128279;${l2.resources.length}</span>` : ""}
      <button class="flag-btn ${l2.flagged ? "is-flagged" : ""}" data-flag-l2="${l2.id}" title="${l2.flagged ? "Unflag" : "Flag for review"}">${l2.flagged ? "★" : "☆"}</button>
      <button class="icon-btn" data-delete-l2="${l2.id}" title="Delete">&#128465;</button>
    </div>`;
}

function wireSubjectDetailEvents(s) {
  document.querySelectorAll("[data-toggle-l1]").forEach((el) => {
    el.addEventListener("click", (e) => {
      if (e.target.closest(".level1-actions")) return;
      el.closest(".level1-block").classList.toggle("is-open");
    });
  });

  document.querySelectorAll("[data-toggle-l2]").forEach((el) => {
    el.addEventListener("click", async () => {
      const id = el.dataset.toggleL2;
      const result = await post(`/api/level2/${id}/toggle`);
      el.classList.toggle("checked", result.done);
      const nameEl = el.parentElement.querySelector(".level2-name");
      nameEl.classList.toggle("done", result.done);
      updateL1AndSubjectProgress(el, result);
      if (result.badge_earned) showBadgeToast(s);
    });
  });

  document.querySelectorAll("[data-open-l2]").forEach((el) => {
    el.addEventListener("click", () => openItemDetail(el.dataset.openL2));
  });

  document.querySelectorAll("[data-flag-l2]").forEach((el) => {
    el.addEventListener("click", async () => {
      const result = await post(`/api/level2/${el.dataset.flagL2}/flag`);
      el.classList.toggle("is-flagged", result.flagged);
      el.textContent = result.flagged ? "★" : "☆";
      el.title = result.flagged ? "Unflag" : "Flag for review";
    });
  });

  document.querySelectorAll("[data-delete-l2]").forEach((el) => {
    el.addEventListener("click", async () => {
      const ok = await showConfirm("Delete this item? This can't be undone.", "Delete");
      if (!ok) return;
      await del(`/api/level2/${el.dataset.deleteL2}`);
      renderSubjectDetail();
    });
  });

  document.querySelectorAll("[data-add-l2]").forEach((el) => {
    el.addEventListener("click", () => openAddLevel2Modal(el.dataset.addL2, s));
  });

  document.querySelectorAll("[data-edit-l1]").forEach((el) => {
    el.addEventListener("click", async (e) => {
      e.stopPropagation();
      const currentName = el.closest(".level1-block").querySelector(".level1-name").textContent;
      const result = await showPrompt(`Rename ${s.level1_label}`, [
        { id: "name", label: `${s.level1_label} name`, value: currentName },
      ]);
      if (!result || !result.name) return;
      await put(`/api/level1/${el.dataset.editL1}`, { name: result.name });
      renderSubjectDetail();
    });
  });

  document.querySelectorAll("[data-delete-l1]").forEach((el) => {
    el.addEventListener("click", async (e) => {
      e.stopPropagation();
      const ok = await showConfirm(
        `Delete this ${s.level1_label.toLowerCase()} and everything inside it? This can't be undone.`,
        "Delete"
      );
      if (!ok) return;
      await del(`/api/level1/${el.dataset.deleteL1}`);
      renderSubjectDetail();
    });
  });
}

function updateL1AndSubjectProgress(checkboxEl, result) {
  const block = checkboxEl.closest(".level1-block");
  block.querySelector(".level1-mini-fill").style.width = result.level1_progress.percent + "%";
  block.querySelector(".level1-pct").textContent = `${result.level1_progress.completed}/${result.level1_progress.total}`;

  document.getElementById("subject-progress-fill").style.width = result.subject_progress.percent + "%";
  const s = state.currentSubjectDetail;
  document.getElementById("subject-progress-text").textContent =
    `${result.subject_progress.completed} / ${result.subject_progress.total} ${s.level2_label}${result.subject_progress.total === 1 ? "" : "s"} · ${result.subject_progress.percent}%`;
}

function showBadgeToast(s) {
  const toast = document.getElementById("badge-toast");
  document.getElementById("toast-text").textContent = `${s.level1_label} complete — badge earned!`;
  toast.classList.add("is-shown");
  setTimeout(() => toast.classList.remove("is-shown"), 3200);
}

// ---- Add Level1 ----
document.getElementById("btn-add-level1").addEventListener("click", () => {
  const s = state.currentSubjectDetail;
  document.getElementById("modal-add-level1-title").textContent = `Add ${s.level1_label}`;
  document.getElementById("level1-name-label").textContent = `${s.level1_label} name`;
  document.getElementById("input-level1-name").value = "";
  document.getElementById("input-level1-name").placeholder = `e.g. ${s.level1_label} 1: Getting started`;
  openModal("modal-add-level1");
});

document.getElementById("btn-submit-level1").addEventListener("click", async () => {
  const name = document.getElementById("input-level1-name").value.trim();
  if (!name) return;
  await post("/api/level1", { subject_id: state.currentSubjectId, name });
  closeModal("modal-add-level1");
  renderSubjectDetail();
});

// ---- Add Level2 ----
let pendingLevel1IdForL2 = null;
function openAddLevel2Modal(level1Id, s) {
  pendingLevel1IdForL2 = level1Id;
  document.getElementById("modal-add-level2-title").textContent = `Add ${s.level2_label}`;
  document.getElementById("level2-name-label").textContent = `${s.level2_label} name`;
  document.getElementById("input-level2-name").value = "";
  document.getElementById("input-level2-name").placeholder = `e.g. Intro to ${s.name}`;
  openModal("modal-add-level2");
}

document.getElementById("btn-submit-level2").addEventListener("click", async () => {
  const name = document.getElementById("input-level2-name").value.trim();
  if (!name || !pendingLevel1IdForL2) return;
  await post("/api/level2", { level1_id: pendingLevel1IdForL2, name });
  closeModal("modal-add-level2");
  renderSubjectDetail();
});

// ---- Bulk import ----
document.getElementById("btn-bulk-import").addEventListener("click", () => {
  document.getElementById("bulk-text").value = "";
  document.getElementById("bulk-preview").innerHTML = "";
  document.getElementById("btn-bulk-confirm").style.display = "none";
  openModal("modal-bulk-import");
});

document.getElementById("btn-bulk-preview").addEventListener("click", async () => {
  const text = document.getElementById("bulk-text").value;
  const result = await post(`/api/subjects/${state.currentSubjectId}/bulk_preview`, { text });
  const preview = document.getElementById("bulk-preview");
  if (result.parsed.length === 0) {
    preview.innerHTML = `<p class="field-hint">Nothing parsed yet — check your formatting.</p>`;
    document.getElementById("btn-bulk-confirm").style.display = "none";
    return;
  }
  preview.innerHTML = result.parsed
    .map(
      (l1) => `
      <div class="bulk-preview-l1">${escapeHtml(l1.name)}</div>
      ${l1.level2_items.map((l2) => `<div class="bulk-preview-l2">${escapeHtml(l2)}</div>`).join("")}
    `
    )
    .join("");
  document.getElementById("btn-bulk-confirm").style.display = "block";
});

document.getElementById("btn-bulk-confirm").addEventListener("click", async () => {
  const text = document.getElementById("bulk-text").value;
  await post(`/api/subjects/${state.currentSubjectId}/bulk_import`, { text });
  closeModal("modal-bulk-import");
  renderSubjectDetail();
});

// ---- Item detail (notes + resources) ----
async function openItemDetail(level2Id) {
  state.currentLevel2ForModal = level2Id;
  const s = state.currentSubjectDetail;
  let item = null;
  for (const l1 of s.level1_items) {
    const found = l1.level2_items.find((l2) => String(l2.id) === String(level2Id));
    if (found) item = found;
  }
  if (!item) return;

  document.getElementById("item-detail-name").textContent = item.name;
  document.getElementById("item-notes").value = item.notes || "";
  renderItemResources(item.resources);
  openModal("modal-item-detail");
}

function renderItemResources(resources) {
  const list = document.getElementById("item-resources-list");
  if (!resources || resources.length === 0) {
    list.innerHTML = `<p class="field-hint">No resources yet.</p>`;
    return;
  }
  list.innerHTML = resources
    .map(
      (r) => `
      <div class="item-resource-row">
        <span class="resource-type-tag">${escapeHtml(r.type)}</span>
        <span style="flex:1; word-break:break-all;">${escapeHtml(r.value)}</span>
        <button class="icon-btn" data-delete-resource="${r.id}">&#128465;</button>
      </div>`
    )
    .join("");
  list.querySelectorAll("[data-delete-resource]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await del(`/api/resources/${btn.dataset.deleteResource}`);
      renderSubjectDetail().then(() => openItemDetail(state.currentLevel2ForModal));
    });
  });
}

document.getElementById("btn-save-notes").addEventListener("click", async () => {
  const notes = document.getElementById("item-notes").value;
  await put(`/api/level2/${state.currentLevel2ForModal}`, { notes });
  await renderSubjectDetail();
});

document.getElementById("btn-add-resource").addEventListener("click", async () => {
  const type = document.getElementById("resource-type").value;
  const value = document.getElementById("resource-value").value.trim();
  if (!value) return;
  await post(`/api/level2/${state.currentLevel2ForModal}/resources`, { type, value });
  document.getElementById("resource-value").value = "";
  await renderSubjectDetail();
  await openItemDetail(state.currentLevel2ForModal);
});

// ---------------------------------------------------------------------------
// ANALYTICS
// ---------------------------------------------------------------------------
async function renderAnalytics() {
  const data = await get("/api/analytics");

  const chart = document.getElementById("daily-chart");
  const maxCount = Math.max(1, ...data.daily_completions.map((d) => d.count));
  // build full 30-day range so gaps show
  const days = [];
  const today = new Date();
  for (let i = 29; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(d.getDate() - i);
    const key = d.toISOString().slice(0, 10);
    const found = data.daily_completions.find((x) => x.date === key);
    days.push({ date: key, count: found ? found.count : 0 });
  }
  const max = Math.max(1, ...days.map((d) => d.count));
  chart.innerHTML = days
    .map((d) => {
      const h = Math.max(2, Math.round((d.count / max) * 110));
      return `<div class="bar ${d.count > 0 ? "has-data" : ""}" style="height:${h}px" title="${d.date}: ${d.count}"></div>`;
    })
    .join("");

  const subjBreak = document.getElementById("subject-breakdown");
  if (data.subject_breakdown.length === 0) {
    subjBreak.innerHTML = `<p class="field-hint">Add a subject to see its breakdown.</p>`;
  } else {
    subjBreak.innerHTML = data.subject_breakdown
      .map(
        (s) => `
        <div class="breakdown-row">
          <div class="breakdown-top">
            <span class="breakdown-name">${escapeHtml(s.name)}</span>
            <span class="breakdown-pct">${s.progress.percent}%</span>
          </div>
          <div class="progress-track"><div class="progress-fill" style="width:${s.progress.percent}%"></div></div>
        </div>`
      )
      .join("");
  }

  const catBreak = document.getElementById("category-breakdown");
  if (data.category_breakdown.length === 0) {
    catBreak.innerHTML = `<p class="field-hint">No categories yet.</p>`;
  } else {
    catBreak.innerHTML = data.category_breakdown
      .map(
        (c) => `
        <div class="breakdown-row">
          <div class="breakdown-top">
            <span class="breakdown-name">${escapeHtml(c.name)}</span>
            <span class="breakdown-pct">${c.progress.percent}%</span>
          </div>
          <div class="progress-track"><div class="progress-fill" style="width:${c.progress.percent}%"></div></div>
        </div>`
      )
      .join("");
  }
}

// ---------------------------------------------------------------------------
// RESOURCES (aggregate)
// ---------------------------------------------------------------------------
async function renderResources() {
  const subjects = await get("/api/subjects");
  const subjSelect = document.getElementById("resource-subject-select");
  if (subjects.length === 0) {
    subjSelect.innerHTML = `<option value="">No subjects yet — add one in My Learning first</option>`;
  } else {
    subjSelect.innerHTML = subjects.map((s) => `<option value="${s.id}">${escapeHtml(s.name)}</option>`).join("");
  }

  const resources = await get("/api/resources");
  const empty = document.getElementById("resources-empty");
  const list = document.getElementById("resources-list");

  if (resources.length === 0) {
    empty.style.display = "block";
    list.innerHTML = "";
    return;
  }
  empty.style.display = "none";
  list.innerHTML = resources
    .map((r) => {
      const context = r.level2_name
        ? `${escapeHtml(r.subject_name)} · ${escapeHtml(r.level2_name)}`
        : `${escapeHtml(r.subject_name)} · general`;
      return `
      <div class="resource-row">
        <span class="resource-type-tag">${escapeHtml(r.type)}</span>
        <span class="resource-value">${escapeHtml(r.value)}</span>
        <span class="resource-context">${context}</span>
        <button class="icon-btn" data-delete-resource-page="${r.id}">&#128465;</button>
      </div>`;
    })
    .join("");

  list.querySelectorAll("[data-delete-resource-page]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await del(`/api/resources/${btn.dataset.deleteResourcePage}`);
      renderResources();
    });
  });
}

document.getElementById("btn-add-resource-page").addEventListener("click", async () => {
  const subjectId = document.getElementById("resource-subject-select").value;
  const type = document.getElementById("resource-page-type").value;
  const value = document.getElementById("resource-page-value").value.trim();
  if (!subjectId) { alert("Add a subject first (in My Learning), then pick it here."); return; }
  if (!value) return;
  await post(`/api/subjects/${subjectId}/resources`, { type, value });
  document.getElementById("resource-page-value").value = "";
  await renderResources();
});

// ---------------------------------------------------------------------------
// Utils
// ---------------------------------------------------------------------------
function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
(async function init() {
  loadView("dashboard");
})();
