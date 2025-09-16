(async function () {
  const API_BASE = "https://gamepulse-news-service.onrender.com"; // ה-API שלך ב-Render

  async function fetchJSON(path) {
    const res = await fetch(API_BASE.replace(/\/$/,"") + path, {
      headers: { "accept": "application/json" }
    });
    if (!res.ok) throw new Error(`HTTP ${res.status} on ${path}`);
    return res.json();
  }

  // טרנדים
  const $tg = document.querySelector("#trending-grid");
  const $tErr = document.querySelector("#trending-error");
  try {
    const trending = await fetchJSON("/api/trending");
    $tg.innerHTML = (trending || []).map((g) => `
      <article class="card">
        <img src="${g.cover}" alt="${g.name}" />
        <div class="body">
          <p class="muted">דירוג: ${g.rating ?? "—"}</p>
          <h3 class="title">${g.name}</h3>
        </div>
      </article>
    `).join("");
  } catch (e) {
    console.error(e);
    $tErr.style.display = "block";
    $tErr.textContent = "נכשל להביא טרנדים מה-API";
  }

  // חדשות
  const $nl = document.querySelector("#news-list");
  const $nErr = document.querySelector("#news-error");
  try {
    const news = await fetchJSON("/api/news");
    $nl.innerHTML = (news || []).map((n) => `
      <article class="card row" style="align-items:center">
        <img src="${n.image}" alt="${n.title}" style="width:240px;max-width:45%;border-inline-end:1px solid #1f2937"/>
        <div class="body" style="flex:1">
          <a class="muted" href="${n.url}" target="_blank" rel="noopener">לכתבה</a>
          <h3 class="title">${n.title}</h3>
          <p class="muted">${n.excerpt ?? ""}</p>
        </div>
      </article>
    `).join("");
  } catch (e) {
    console.error(e);
    $nErr.style.display = "block";
    $nErr.textContent = "נכשל להביא חדשות מה-API";
  }
})();
