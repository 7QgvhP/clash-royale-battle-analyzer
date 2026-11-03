// クラロワ対戦分析 — 画面共通の処理。
//
// すべての画面で同じものを使うため、テンプレートに直接書かず1つのファイルにまとめる。
// サーバーが無くても動くよう、ここでの処理はすべてブラウザ内で完結させる。
//
//   1. 共通ページで、どのプレイヤーから来たかを引き継ぐ
//   2. 表の並べ替え
//   3. 「○分前」の計算
//   4. テーマの切り替え
//   5. ヘッダ・ナビ・表の見出しを留める高さの計算
//   6. グラフの書体合わせ

// 呪文・カード性能・カード詳細は、絞り込みごとには作らず1ファイルしか書き出さない。
// そのためナビの行き先は既定のプレイヤー向けに固定されてしまう。どのプレイヤーの
// 画面から来たかは ?from=<組み合わせ> で受け取り、ここで行き先を直す。
(function () {
  var from = (location.search.match(/[?&]from=([^&]+)/) || [])[1];
  if (!from) return;
  from = decodeURIComponent(from);
  // 「プレイヤー_期間_モード_デッキ」の4つ組だけを受け付ける
  if (!/^[^_/]+_[^_/]+_[^_/]+_[^_/]+$/.test(from)) return;
  var player = from.split("_")[0];

  // 呪文の表のように、あとから作られるリンクもあるため、何度でも呼べるようにする。
  function apply() {
    document.querySelectorAll('a[href^="../"]').forEach(function (a) {
      var m = a.getAttribute("href").match(/^\.\.\/([^/]+)\/([^?]+)(\?.*)?$/);
      if (!m) return;
      if (/^[^_]+_[^_]+_[^_]+_[^_]+$/.test(m[1])) {
        // 絞り込みのページへ戻るリンク。来たときの組み合わせに差し替える。
        a.setAttribute("href", "../" + from + "/" + m[2]);
      } else if (m[1] === "card-list") {
        // カード育成はプレイヤーごとに1ページあるため、ファイル名ごと差し替える。
        a.setAttribute("href", "../card-list/" + player + ".html?from=" + from);
      } else if (m[1] === "spells" || m[1] === "card") {
        // 共通ページ同士のリンクでは、来たプレイヤーをそのまま引き継ぐ。
        a.setAttribute("href", "../" + m[1] + "/" + m[2] + "?from=" + from);
      }
    });
  }
  window.applyFromCombo = apply;
  apply();

  // プレイヤーの選択も、来たときの状態に合わせる。行き先は常にサマリーで、
  // 自デッキの絞り込みは持ち主が変わると意味を持たないため外す。
  var select = document.querySelector(".player-switch");
  if (select) {
    var parts = from.split("_");            // プレイヤー_期間_モード_デッキ
    var keep = parts[1] + "_" + parts[2] + "_all";
    [].forEach.call(select.options, function (o) {
      var m = o.value.match(/^\.\.\/([^_/]+)_[^/]*\/(.+)$/);
      if (!m) return;
      o.value = "../" + m[1] + "_" + keep + "/summary.html";
      o.selected = m[1] === player;
    });
  }
})();

// 表の並べ替え。見出しを押すと、その列で昇順・降順を切り替える。
// サーバーは関与しないため、静的サイトでもページを増やさずに動く。
// 対象は class="sortable" の表。見出しに data-nosort が付いた列は対象外。
(function () {
  // 並べ替えに使う値。セルに data-sort-value があればそれを、無ければ文字列を使う。
  // 「1,234」「67.7%」「+3.2」のような表記は数値として扱う。
  function cellValue(row, index) {
    var cell = row.cells[index];
    if (!cell) return "";
    var raw = cell.getAttribute("data-sort-value");
    return raw !== null ? raw : cell.textContent.trim();
  }

  function asNumber(text) {
    if (text === "" || text === "--" || text === "—") return null;
    var n = Number(String(text).replace(/[,%\s]/g, "").replace(/^\+/, ""));
    return isNaN(n) ? null : n;
  }

  function sortTable(table, index, descending) {
    var tbody = table.tBodies[0];
    var rows = [].slice.call(tbody.rows);
    var values = rows.map(function (r) { return cellValue(r, index); });
    // 空欄を除いてすべて数値なら数値として、そうでなければ文字列として比べる
    var filled = values.filter(function (v) { return asNumber(v) !== null; });
    var numeric = filled.length > 0 &&
      values.every(function (v) { return asNumber(v) !== null || v === "" || v === "--" || v === "—"; });

    rows.forEach(function (r, i) { r.$i = i; });
    rows.sort(function (a, b) {
      var x = cellValue(a, index), y = cellValue(b, index), diff;
      if (numeric) {
        var nx = asNumber(x), ny = asNumber(y);
        // 値の無い行は、昇順・降順のどちらでも最後に置く
        if (nx === null && ny === null) diff = 0;
        else if (nx === null) return 1;
        else if (ny === null) return -1;
        else diff = nx - ny;
      } else {
        diff = x.localeCompare(y, "ja");
      }
      if (descending) diff = -diff;
      return diff || a.$i - b.$i;   // 同じ値のときは元の並びを保つ
    });
    rows.forEach(function (r) { tbody.appendChild(r); });
  }

  function headers(table) {
    var row = table.tHead && table.tHead.rows[table.tHead.rows.length - 1];
    return row ? [].slice.call(row.cells) : [];
  }

  document.querySelectorAll("table.sortable").forEach(function (table) {
    var ths = headers(table);
    if (!table.tBodies.length) return;

    // 見出しが隠れる画面（自デッキ・カード育成）向けに、同じ内容のボタンを用意する。
    // 表示するかどうかはCSSに任せる。
    var chips = document.createElement("div");
    chips.className = "sort-chips";

    ths.forEach(function (th, index) {
      if (th.hasAttribute("data-nosort")) return;
      var label = (th.getAttribute("data-sort-label") || th.textContent).trim();
      if (!label) return;

      function activate() {
        // 同じ列を続けて押したときだけ向きを反転する。
        // 最初は、数値なら大きい順、文字なら小さい順にする。
        var current = th.getAttribute("aria-sort");
        var descending = current === "ascending" ? true
          : current === "descending" ? false
          : !th.classList.contains("sort-text");
        sortTable(table, index, descending);
        ths.forEach(function (other) { other.removeAttribute("aria-sort"); });
        th.setAttribute("aria-sort", descending ? "descending" : "ascending");
        [].forEach.call(chips.children, function (b) {
          b.classList.toggle("on", Number(b.dataset.index) === index);
          if (Number(b.dataset.index) === index) {
            b.dataset.dir = descending ? "descending" : "ascending";
          } else {
            delete b.dataset.dir;
          }
        });
      }

      th.classList.add("sort-head");
      th.tabIndex = 0;
      th.setAttribute("role", "button");
      // 押せることが分かるよう、説明も添える（スマートフォンでは出ないが害はない）
      th.title = label + "で並べ替え（もう一度押すと逆順）";
      th.addEventListener("click", activate);
      th.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); activate(); }
      });

      var chip = document.createElement("button");
      chip.type = "button";
      chip.className = "seg-link";
      chip.textContent = label;
      chip.dataset.index = index;
      chip.addEventListener("click", activate);
      chips.appendChild(chip);
    });

    if (chips.children.length) {
      var wrap = table.closest(".table-wrap") || table;
      wrap.parentNode.insertBefore(chips, wrap);
    }
  });
})();

// 経過時間を表示時点で計算し直す。
// 静的サイトは書き出し時のHTMLがそのまま配信されるため、
// サーバー側で計算した「○分前」は開いた時刻と無関係な値になってしまう。
(function () {
  document.querySelectorAll(".ago[data-at]").forEach(function (el) {
    var at = new Date(el.getAttribute("data-at"));
    if (isNaN(at)) return;
    var min = Math.max(0, Math.floor((Date.now() - at) / 60000));
    var text;
    if (min < 1) text = "たった今";
    else if (min < 60) text = min + "分前";
    else if (min < 60 * 24) text = Math.floor(min / 60) + "時間前";
    else text = Math.floor(min / (60 * 24)) + "日前";
    el.textContent = text;
    // 正確な日時はマウスを乗せると分かるようにしておく
    el.title = at.toLocaleString();
  });
})();

// テーマ切替。端末設定に従う状態から、明示指定へ切り替える。
(function () {
  var root = document.documentElement;
  var btn = document.getElementById("theme-toggle");
  if (!btn) return;
  btn.addEventListener("click", function () {
    var current = root.getAttribute("data-theme");
    var isDark = current
      ? current === "dark"
      : window.matchMedia("(prefers-color-scheme: dark)").matches;
    var next = isDark ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try { localStorage.setItem("theme", next); } catch (e) {}
    document.dispatchEvent(new CustomEvent("themechange"));
  });
})();

// 表の見出しを、スクロールしても画面上部（ヘッダの直下）に残す。
// ただし横スクロールする箱の中では固定が効かないため、表が横幅に収まっている
// ときだけ箱のスクロールを外して固定する。はみ出す表は従来どおり横スクロールさせる。
(function () {
  var root = document.documentElement;
  var header = document.querySelector('.header');
  var nav = document.querySelector('.nav');

  function measure() {
    // --header-h はヘッダの高さ（ナビを留める位置）。
    // --stick-h はヘッダ＋ナビの高さ（表の見出しを留める位置）。
    var headerH = header ? header.offsetHeight : 0;
    root.style.setProperty('--header-h', headerH + 'px');
    root.style.setProperty('--stick-h', (headerH + (nav ? nav.offsetHeight : 0)) + 'px');
    document.querySelectorAll('.table-wrap').forEach(function (wrap) {
      var table = wrap.querySelector('table');
      if (!table) return;
      // 判定のあいだは一度スクロールできる状態に戻し、本来の幅で比べる
      wrap.classList.remove('fits');
      wrap.classList.toggle('fits', table.scrollWidth <= wrap.clientWidth + 1);
    });
  }

  measure();
  window.addEventListener('resize', measure);
  window.addEventListener('load', measure);
  // 呪文の画面のように、表の中身が後から入れ替わる場合にも判定し直す
  if (window.ResizeObserver) {
    var observer = new ResizeObserver(function () { measure(); });
    document.querySelectorAll('.table-wrap table').forEach(function (t) { observer.observe(t); });
  }
})();

// グラフの文字も本文と同じ書体にする。グラフは描いた時点の書体で固定されるため、
// フォントの読み込みが終わったら描き直す。
(function () {
  if (!window.Chart) return;
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(function () {
      Object.values(Chart.instances || {}).forEach(function (chart) { chart.update('none'); });
    });
  }
})();
