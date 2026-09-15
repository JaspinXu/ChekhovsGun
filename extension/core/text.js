/**
 * Tokenisation and normalisation that behave sensibly for Chinese *and* English.
 *
 * A direct port of `chekhovsgun/rag/text.py`. Chinese has no spaces, so a
 * whitespace tokenizer collapses a whole sentence into one token and destroys
 * lexical matching. We therefore emit CJK character bigrams (the standard cheap
 * stand-in for a word segmenter) alongside ordinary latin/number word tokens.
 * The same function feeds both the hashed embedder and the BM25 index, so dense
 * and lexical retrieval see the same view of the text.
 *
 * Parity with the Python original is enforced by `test/text.test.js`, which
 * replays fixtures captured from the Python implementation. If you change
 * anything here, regenerate those fixtures or the port has silently drifted.
 */

const CJK_RANGES = [
  [0x3400, 0x4dbf],
  [0x4e00, 0x9fff],
  [0xf900, 0xfaff],
  [0x20000, 0x2a6df],
  [0x3040, 0x30ff], // kana, close enough to share the bigram treatment
  [0xac00, 0xd7af], // hangul
];

const LATIN_TOKEN = /[a-z0-9][a-z0-9'_+#.\-]*/iy;
const SPLITTABLE = /[-_.]+/;
const WS = /\s+/g;

// English function words: no retrieval signal, present in every other title.
const STOPWORDS = new Set([
  "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are",
  "it", "this", "that", "with", "as", "at", "by", "be", "from", "you", "your",
  "we", "i", "how", "what", "why", "was", "were", "will", "can", "do", "does",
  "my", "me", "our", "they", "them", "he", "she", "its", "but", "so", "if",
  "not", "no", "yes", "up", "out", "about", "into", "than", "then", "there",
  "here", "when", "where", "which", "who", "all", "any", "some", "just",
  "very", "more", "most", "one", "two", "get", "got", "make", "made", "let",
]);

// Chinese has no spaces, so its function words have to be handled a character
// at a time. Any *bigram* built from two of these — 还是, 就是, 这个, 怎么 — is
// a function word too, and must not count as topical evidence. Without this, a
// query about cooking "matches" a database talk because both contain 还是.
const CJK_FUNCTION_CHARS = new Set(
  "的了是在和就都而及与也很到我你他她它们这那个可以什么怎样还有要会能说去来做" +
  "得着过被把让给对从向为于不没无上下中里外前后之其此但因所然则又再才只更最太" +
  "些种时候用好大小多少等吧呢吗啊呀哦嗯如果或者且并虽且比如及至由该们哪谁咱您"
);
for (const ch of CJK_FUNCTION_CHARS) STOPWORDS.add(ch);

// Video-title genre words. These are not function words — they are perfectly
// good nouns — but on Chinese video platforms they appear in a large fraction
// of every title regardless of subject, so they behave like boilerplate. IDF
// would eventually learn this on a large library; excluding them explicitly
// means a freshly seeded index does not rank "Redis 持久化原理" against a query
// about vector search purely because both say 原理.
for (const word of [
  "原理", "详解", "讲解", "精讲", "精读", "解析", "教程", "入门", "实战", "实测",
  "笔记", "分享", "总结", "干货", "科普", "揭秘", "指南", "手册", "系列", "合集",
  "全集", "完整", "版本", "最新", "推荐", "盘点", "对比", "测评", "体验", "记录",
  "过程", "全程", "手把手", "保姆级", "从零", "零基础", "一文", "看懂", "学会",
  // Generic nouns that carry no subject on their own.
  "做法", "方法", "方式", "情况", "东西", "地方", "内容", "问题", "区别", "意思",
]) STOPWORDS.add(word);

export function isCjk(ch) {
  const code = ch.codePointAt(0);
  for (const [lo, hi] of CJK_RANGES) if (code >= lo && code <= hi) return true;
  return false;
}

/** True for tokens that carry no topical signal in either language. */
export function isFunctionToken(token) {
  if (STOPWORDS.has(token)) return true;
  return (
    token.length === 2 &&
    [...token].every((ch) => isCjk(ch) && CJK_FUNCTION_CHARS.has(ch))
  );
}

/**
 * 'cjk' | 'latin' | 'mixed' — which writing system dominates this text.
 *
 * Coverage scoring needs this: a Chinese query token can never appear in an
 * English passage, so counting it against that passage would make every
 * cross-language match look irrelevant, which is precisely the case where the
 * user most benefits from being reminded of what they saved.
 */
export function scriptOf(text) {
  const sample = text.slice(0, 240); // the opening of a passage settles its script
  let cjk = 0;
  let latin = 0;
  for (const ch of sample) {
    if (isCjk(ch)) cjk += 1;
    else if (/[a-z]/i.test(ch) && ch.charCodeAt(0) < 128) latin += 1;
  }
  const total = cjk + latin;
  if (total < 4) return "mixed";
  if (cjk / total > 0.75) return "cjk";
  if (latin / total > 0.75) return "latin";
  return "mixed";
}

/**
 * NFKC-fold, lowercase and squeeze whitespace.
 *
 * NFKC matters for Bilibili titles, which are full of full-width punctuation
 * and full-width latin letters that would otherwise not match their ASCII form.
 */
export function normalize(text) {
  if (!text) return "";
  return text.normalize("NFKC").replace(WS, " ").trim().toLowerCase();
}

/** Split into retrieval tokens: latin words + CJK unigrams and bigrams. */
export function tokenize(text, { dropStopwords = true } = {}) {
  text = normalize(text);
  if (!text) return [];

  const tokens = [];
  let cjkRun = [];

  const flushCjk = () => {
    if (!cjkRun.length) return;
    const run = cjkRun;
    cjkRun = [];
    tokens.push(...run);
    for (let i = 0; i < run.length - 1; i += 1) tokens.push(run[i] + run[i + 1]);
  };

  // Iterate by code point so astral CJK (the 0x20000 range) is not split.
  const chars = [...text];
  let i = 0;
  while (i < chars.length) {
    const ch = chars[i];
    if (isCjk(ch)) {
      cjkRun.push(ch);
      i += 1;
      continue;
    }
    flushCjk();
    // `y` (sticky) anchors the match at lastIndex, mirroring Python's
    // `pattern.match(text, i)`. Index in UTF-16 units, hence the offset math.
    const offset = chars.slice(0, i).join("").length;
    LATIN_TOKEN.lastIndex = offset;
    const match = LATIN_TOKEN.exec(text);
    if (match) {
      const word = match[0].replace(/^[-_.]+|[-_.]+$/g, "");
      if (word) {
        tokens.push(word);
        // "self-attention" must also match a document that only says
        // "attention", and "B-Tree" one that says "btree" or "b tree".
        const parts = word.split(SPLITTABLE).filter(Boolean);
        if (parts.length > 1) {
          for (const p of parts) if (p.length > 1) tokens.push(p);
          tokens.push(parts.join(""));
        }
      }
      i += [...match[0]].length;
    } else {
      i += 1;
    }
  }
  flushCjk();

  return dropStopwords ? tokens.filter((t) => !isFunctionToken(t)) : tokens;
}

/** Split on sentence-ish boundaries, keeping the terminator. */
export function sentences(text) {
  if (!text) return [];
  return text
    .split(/(?<=[。！？!?；;\n])\s*|(?<=[.])\s+/)
    .map((p) => (p || "").trim())
    .filter(Boolean);
}

/** A short excerpt centred on the first query token that appears. */
export function snippet(text, query, width = 160) {
  if (!text) return "";
  if (text.length <= width) return text;
  const lowered = normalize(text);
  for (const token of tokenize(query)) {
    if (token.length < 2) continue;
    const pos = lowered.indexOf(token);
    if (pos >= 0) {
      const start = Math.max(0, pos - Math.floor(width / 3));
      const end = Math.min(text.length, start + width);
      const prefix = start > 0 ? "…" : "";
      const suffix = end < text.length ? "…" : "";
      return `${prefix}${text.slice(start, end).trim()}${suffix}`;
    }
  }
  return text.slice(0, width).trim() + "…";
}
