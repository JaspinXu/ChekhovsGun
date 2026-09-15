/* Per-site knowledge, in one table.
 *
 * Adding a site means adding an entry here. Nothing else in the extension — and
 * nothing at all in the Python — needs to know the site exists: the server
 * canonicalises whatever URL arrives and names the source itself.
 *
 * Every field is optional. A recipe with no `title`/`body` probes still works,
 * because `readGeneric` below finds the article on its own; the probes exist to
 * beat the heuristic on sites where it is known to lose. That matters because a
 * wrong selector is worse than no selector — it silently captures a sidebar —
 * so this table only asserts selectors worth asserting, and lets the generic
 * reader handle the rest.
 *
 * Field reference:
 *   name        source id, must match chekhovsgun/sites.py
 *   label       what the user sees
 *   kind        "video" | "post"
 *   hosts       hostname suffixes this recipe claims
 *   isDetail    (url) => is this one item's own page? Feeds are never captured.
 *   title/author/body/tags/thumbnail   () => string, override the generic read
 *   saveButtons selectors for the site's own bookmark control; clicking one
 *               is what "只需要收藏" hangs on
 *   favorites   { isPage, item, link, title, folder } for the folder scan
 */
(() => {
  "use strict";

  const text = (selector, root = document) => {
    const node = root.querySelector(selector);
    return node ? (node.textContent || "").trim() : "";
  };
  const attr = (selector, name) =>
    document.querySelector(selector)?.getAttribute(name)?.trim() || "";
  const meta = (name) =>
    attr(`meta[property="${name}"]`, "content") || attr(`meta[name="${name}"]`, "content");
  const firstText = (...selectors) => {
    for (const selector of selectors) {
      const value = text(selector);
      if (value) return value;
    }
    return "";
  };

  // ------------------------------------------------------ generic extraction
  const SKIP = new Set([
    "SCRIPT", "STYLE", "NOSCRIPT", "SVG", "CANVAS", "IFRAME", "NAV", "HEADER",
    "FOOTER", "ASIDE", "FORM", "BUTTON", "SELECT", "TEXTAREA", "FIGURE",
    "VIDEO", "AUDIO", "TEMPLATE",
  ]);
  const GOOD = /article|content|post|entry|body|answer|richtext|rich_media|note-?text|markdown|question|story|main/i;
  const BAD = /comment|sidebar|footer|header|nav|menu|banner|promo|advert|\bads?\b|related|recommend|share|social|subscribe|popup|modal|toolbar|breadcrumb|pagination/i;

  // A CJK character carries about as much meaning as 2.5 latin ones; scoring
  // them equally makes every threshold reject Chinese articles. Mirrors
  // weighted_len() in chekhovsgun/extract.py.
  const CJK = /[぀-ヿ㐀-䶿一-鿿가-힯]/g;
  const weigh = (value) => {
    const cjk = (value.match(CJK) || []).length;
    return Math.round(value.length - cjk + cjk * 2.5);
  };

  function measure(node) {
    let total = 0;
    let links = 0;
    const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT, {
      acceptNode(textNode) {
        for (let el = textNode.parentElement; el && el !== node; el = el.parentElement) {
          if (SKIP.has(el.tagName)) return NodeFilter.FILTER_REJECT;
        }
        return textNode.nodeValue.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      },
    });
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const length = weigh(n.nodeValue.trim());
      total += length;
      if (n.parentElement && n.parentElement.closest("a")) links += length;
    }
    return { total, links };
  }

  /** The element holding the most text that is NOT inside links is the article.
   *  Navigation, sidebars and related-post rails are almost entirely anchors. */
  function readGeneric(root = document.body) {
    if (!root) return "";
    let best = null;
    let bestScore = 0;
    const candidates = root.querySelectorAll(
      "article, main, section, div, td, [class*=content], [class*=article], [id*=content]"
    );
    for (const node of candidates) {
      if (SKIP.has(node.tagName)) continue;
      const { total, links } = measure(node);
      if (total < 80) continue;
      let score = total - 2 * links;
      if (node.tagName === "ARTICLE" || node.tagName === "MAIN") score *= 1.6;
      const blob = `${node.className || ""} ${node.id || ""}`;
      if (GOOD.test(blob)) score *= 1.4;
      if (BAD.test(blob)) score *= 0.25;
      if (score > bestScore) {
        best = node;
        bestScore = score;
      }
    }
    if (!best) return "";
    return blockText(best);
  }

  /** Flatten an element to text, keeping one line per block so the server can
   *  split it back into paragraph-sized segments. */
  function blockText(node) {
    const lines = [];
    const walk = (el) => {
      for (const child of el.childNodes) {
        if (child.nodeType === Node.TEXT_NODE) {
          const value = child.nodeValue.replace(/\s+/g, " ").trim();
          if (value) lines[lines.length - 1] = `${lines[lines.length - 1] || ""} ${value}`.trim();
          continue;
        }
        if (child.nodeType !== Node.ELEMENT_NODE || SKIP.has(child.tagName)) continue;
        const block = /^(P|DIV|SECTION|ARTICLE|LI|TR|BR|HR|PRE|BLOCKQUOTE|H[1-6]|DD|DT|TD)$/.test(
          child.tagName
        );
        if (block) lines.push("");
        walk(child);
        if (block) lines.push("");
      }
    };
    lines.push("");
    walk(node);
    return lines.map((line) => line.trim()).filter((line) => line.length > 1).join("\n");
  }

  // ------------------------------------------------------------------ recipes
  const RECIPES = [
    {
      name: "youtube",
      label: "YouTube",
      kind: "video",
      hosts: ["youtube.com", "youtu.be"],
      isDetail: () =>
        location.pathname === "/watch" || location.pathname.startsWith("/shorts/"),
      title: () =>
        firstText(
          "#title h1 yt-formatted-string",
          "h1.ytd-watch-metadata",
          "ytd-reel-player-header-renderer h2"
        ) || meta("title") || document.title.replace(/ - YouTube$/, ""),
      author: () =>
        firstText(
          "#owner #channel-name a",
          "ytd-channel-name#channel-name a",
          "ytd-reel-player-header-renderer #channel-name"
        ) || attr('link[itemprop="name"]', "content"),
      body: () =>
        firstText("#description-inline-expander ytd-text-inline-expander",
                  "#description-inline-expander") || meta("description"),
      tags: () =>
        Array.from(document.querySelectorAll('meta[property="og:video:tag"]'))
          .map((node) => node.content)
          .filter(Boolean)
          .slice(0, 20),
      // "Save to playlist" lives behind a menu, so the reliable signal is the
      // dialog's own confirmation rather than the button that opened it.
      saveButtons: ["ytd-add-to-playlist-renderer tp-yt-paper-checkbox", "#flexible-item-buttons button[aria-label*='Save']"],
      favorites: {
        isPage: () => location.pathname === "/playlist",
        item: "ytd-playlist-video-renderer",
        link: "a#video-title",
        title: "a#video-title",
        folder: () => text("yt-dynamic-sizing-formatted-string h1") || "YouTube playlist",
      },
    },
    {
      name: "bilibili",
      label: "哔哩哔哩",
      kind: "video",
      hosts: ["bilibili.com"],
      isDetail: () => /\/(video|bangumi)\//.test(location.pathname),
      title: () =>
        firstText("h1.video-title", ".video-info-title-inner .video-title") ||
        attr("h1[title]", "title") ||
        document.title.replace(/_哔哩哔哩.*$/, ""),
      author: () => firstText(".up-info--right .up-name", ".up-name", ".username"),
      body: () =>
        firstText(".basic-desc-info", ".desc-info-text", "#v_desc .desc-info") ||
        meta("description"),
      tags: () =>
        Array.from(document.querySelectorAll(".tag-panel .tag-link, .video-tag-container .tag"))
          .map((node) => (node.textContent || "").trim())
          .filter(Boolean)
          .slice(0, 20),
      saveButtons: [".video-fav", ".collect", ".ops .collect", "[class*='collect']"],
      favorites: {
        isPage: () => location.hostname === "space.bilibili.com" && /favlist/.test(location.href),
        item: ".fav-video-list .small-item, .favorite-list-content .items__item",
        link: "a.title, a[href*='/video/']",
        title: "a.title",
        folder: () => text(".fav-header .name") || "B站收藏夹",
      },
    },
    {
      name: "zhihu",
      label: "知乎",
      kind: "post",
      hosts: ["zhihu.com"],
      isDetail: () =>
        /\/(question\/\d+\/answer|p)\/\d+/.test(location.pathname) ||
        /^\/question\/\d+$/.test(location.pathname),
      title: () =>
        firstText(".QuestionHeader-title", ".Post-Title", "h1.Post-Title") ||
        meta("og:title") ||
        document.title.replace(/ - 知乎$/, ""),
      author: () => firstText(".AuthorInfo-name .UserLink-link", ".AuthorInfo-name"),
      // Zhihu renders answers into .RichText blocks; taking them in order keeps
      // the accepted answer first, which is what the reader actually wants.
      body: () => {
        const blocks = Array.from(document.querySelectorAll(".RichText.ztext"))
          .slice(0, 3)
          .map(blockText)
          .filter(Boolean);
        return blocks.join("\n") || readGeneric();
      },
      saveButtons: ["button[aria-label*='收藏']", ".Button--withLabel[class*='Collect']"],
      favorites: {
        isPage: () => /\/collection\//.test(location.pathname),
        item: ".ContentItem",
        link: "a[href*='/answer/'], a[href*='/p/']",
        title: ".ContentItem-title",
        folder: () => text(".CollectionDetailPageHeader-title") || "知乎收藏夹",
      },
    },
    {
      name: "xiaohongshu",
      label: "小红书",
      kind: "post",
      hosts: ["xiaohongshu.com"],
      isDetail: () => /\/(explore|discovery\/item)\//.test(location.pathname),
      title: () => firstText("#detail-title", ".note-content .title") || meta("og:title"),
      author: () => firstText(".author-wrapper .username", ".author .name"),
      body: () => firstText("#detail-desc", ".note-content .desc") || readGeneric(),
      saveButtons: [".collect-wrapper", "[class*='collect']"],
      favorites: {
        isPage: () => /\/user\/profile\//.test(location.pathname),
        item: "section.note-item",
        link: "a.cover",
        title: ".title span",
        folder: () => "小红书收藏",
      },
    },
    {
      name: "wechat",
      label: "微信公众号",
      kind: "post",
      hosts: ["mp.weixin.qq.com"],
      isDetail: () => location.pathname.startsWith("/s"),
      title: () => firstText("#activity-name", "h1.rich_media_title") || meta("og:title"),
      author: () => firstText("#js_name", ".rich_media_meta_nickname"),
      body: () => {
        const node = document.querySelector("#js_content");
        return node ? blockText(node) : readGeneric();
      },
    },
    {
      name: "juejin",
      label: "掘金",
      kind: "post",
      hosts: ["juejin.cn"],
      isDetail: () => /^\/post\/\d+/.test(location.pathname),
      title: () => firstText("h1.article-title") || meta("og:title"),
      author: () => firstText(".author-name span", ".author-info-block .username"),
      body: () => {
        const node = document.querySelector(".markdown-body, #article-root");
        return node ? blockText(node) : readGeneric();
      },
      saveButtons: [".collect", "[class*='collect']"],
    },
    {
      name: "csdn",
      label: "CSDN",
      kind: "post",
      hosts: ["blog.csdn.net"],
      isDetail: () => /\/article\/details\//.test(location.pathname),
      title: () => firstText("h1.title-article") || meta("og:title"),
      author: () => firstText(".follow-nickName", ".user-info .name"),
      body: () => {
        const node = document.querySelector("#content_views, #article_content");
        return node ? blockText(node) : readGeneric();
      },
    },
    {
      name: "jianshu",
      label: "简书",
      kind: "post",
      hosts: ["jianshu.com"],
      isDetail: () => /^\/p\//.test(location.pathname),
      title: () => firstText("h1._1RuRku") || meta("og:title"),
      body: () => readGeneric(),
    },
    {
      name: "weibo",
      label: "微博",
      kind: "post",
      hosts: ["weibo.com", "m.weibo.cn"],
      isDetail: () => /\/(detail|status)\//.test(location.pathname) ||
                      /^\/\d+\/\w+$/.test(location.pathname),
      title: () => (firstText(".detail_wbtext_4CRf9", ".weibo-text") || document.title).slice(0, 120),
      author: () => firstText(".head_name_24eEB", ".username"),
      body: () => firstText(".detail_wbtext_4CRf9", ".weibo-text") || readGeneric(),
    },
    {
      name: "reddit",
      label: "Reddit",
      kind: "post",
      hosts: ["reddit.com"],
      isDetail: () => /\/comments\//.test(location.pathname),
      title: () => firstText("h1[slot=title]", "h1") || meta("og:title"),
      author: () => attr("shreddit-post", "author"),
      body: () => {
        const node = document.querySelector("div[slot=text-body], shreddit-post");
        return node ? blockText(node) : readGeneric();
      },
    },
    {
      name: "stackoverflow",
      label: "Stack Overflow",
      kind: "post",
      hosts: ["stackoverflow.com", "stackexchange.com", "superuser.com", "serverfault.com"],
      isDetail: () => /^\/questions\/\d+/.test(location.pathname),
      title: () => firstText("h1 a.question-hyperlink", "#question-header h1"),
      body: () => {
        const blocks = Array.from(document.querySelectorAll(".js-post-body"))
          .slice(0, 3)
          .map(blockText)
          .filter(Boolean);
        return blocks.join("\n") || readGeneric();
      },
    },
    {
      name: "x",
      label: "X / Twitter",
      kind: "post",
      hosts: ["twitter.com", "x.com"],
      isDetail: () => /\/status\/\d+/.test(location.pathname),
      title: () => (firstText("[data-testid=tweetText]") || document.title).slice(0, 120),
      body: () =>
        Array.from(document.querySelectorAll("[data-testid=tweetText]"))
          .slice(0, 5)
          .map((node) => (node.textContent || "").trim())
          .filter(Boolean)
          .join("\n"),
    },
    {
      name: "medium",
      label: "Medium",
      kind: "post",
      hosts: ["medium.com"],
      isDetail: () => /\/[^/]+-[0-9a-f]{8,}$/.test(location.pathname),
      title: () => firstText("h1") || meta("og:title"),
      body: () => {
        const node = document.querySelector("article");
        return node ? blockText(node) : readGeneric();
      },
    },
  ];

  /** The recipe for a hostname, or a generic post recipe if we have none. */
  function recipeFor(hostname = location.hostname) {
    const host = hostname.replace(/^www\./, "");
    for (const recipe of RECIPES) {
      if (recipe.hosts.some((h) => host === h || host.endsWith(`.${h}`))) return recipe;
    }
    return GENERIC;
  }

  const GENERIC = {
    name: "",
    label: "网页",
    kind: "post",
    hosts: [],
    // Any page the user deliberately asked to save counts as a detail page;
    // this recipe is only ever reached through the toolbar button.
    isDetail: () => true,
    title: () => meta("og:title") || document.title,
    author: () => meta("author") || meta("article:author"),
    body: () => readGeneric(),
  };

  /** Read the current page through a recipe, falling back field by field. */
  function readPage(recipe = recipeFor()) {
    const pick = (fn, fallback = "") => {
      try {
        return (fn ? fn() : "") || fallback;
      } catch (error) {
        return fallback;
      }
    };
    const body = pick(recipe.body, "") || readGeneric();
    return {
      url: location.href,
      source: recipe.name || "",
      media_kind: recipe.kind || "post",
      title: String(pick(recipe.title, document.title)).slice(0, 300),
      author: String(pick(recipe.author)).slice(0, 120),
      text: recipe.kind === "video" ? "" : String(body).slice(0, 60000),
      // For a video the description is metadata, not content; for a post the
      // body already carries the prose, so the excerpt is only a preview.
      excerpt: String(recipe.kind === "video" ? body : body.slice(0, 600)).slice(0, 4000),
      thumbnail: pick(recipe.thumbnail, meta("og:image")),
      tags: (() => {
        try {
          return recipe.tags ? recipe.tags() : [];
        } catch (error) {
          return [];
        }
      })(),
    };
  }

  self.ChekhovsGunRecipes = { RECIPES, GENERIC, recipeFor, readPage, readGeneric, blockText };
})();
