import test from "node:test";
import assert from "node:assert/strict";
import { languageMetadata } from "../build/highlightLanguages.js";
import {
  codeHighlighter,
  configureCodeHighlight,
  isCodeLanguageReady,
  loadCodeLanguage,
} from "../src/utils/codeHighlight.js";
import { renderMarkdown } from "../src/utils/markdown.js";

const { languages, aliases, dependencies } = languageMetadata();
const calls = [];
configureCodeHighlight({
  aliases: { ...aliases, broken: "broken" },
  dependencies: { ...dependencies, broken: [] },
  loaders: {
    ...Object.fromEntries(
      languages.map((name) => [
        name,
        () => {
          calls.push(name);
          return import(`highlight.js/lib/languages/${name}`);
        },
      ]),
    ),
    broken: () => {
      calls.push("broken");
      return Promise.reject(new Error("Synthetic download failure"));
    },
  },
});

test("plain Markdown and unknown or malicious labels never download a grammar", async () => {
  renderMarkdown("# Hello\n\nA **small** answer.");
  const html = renderMarkdown("```unknown\n<script>alert(1)</script>\n```");
  assert.match(html, /&lt;script&gt;/);
  for (const label of ["unknown", "__proto__", "constructor", 'js" onclick="alert(1)']) {
    assert.equal(await loadCodeLanguage(label), false);
  }
  assert.deepEqual(calls, []);
});

test("concurrent aliases download a grammar once and preserve the source", async () => {
  const text = '```py\nprint("<hello>")\n```';
  const first = renderMarkdown(text);
  assert.doesNotMatch(first, /hljs-built_in/);
  assert.deepEqual(await Promise.all([loadCodeLanguage("python"), loadCodeLanguage("PY")]), [
    true,
    true,
  ]);
  assert.equal(calls.filter((name) => name === "python").length, 1);
  assert.equal(isCodeLanguageReady("py"), true);
  assert.match(renderMarkdown(text), /hljs-built_in/);
  assert.match(renderMarkdown(text), /&lt;hello&gt;/);
});

test("cyclic embedded-language dependencies load without deadlock", async () => {
  assert.equal(await loadCodeLanguage("php-template"), true);
  const html = codeHighlighter.highlight('<div><?php echo "hello"; ?></div>', {
    language: "php-template",
  }).value;
  assert.match(html, /language-xml/);
  assert.match(html, /language-php/);
  assert.match(html, /hljs-keyword/);
  for (const name of ["xml", "javascript", "css", "handlebars", "php"]) {
    assert.equal(isCodeLanguageReady(name), true, name);
    assert.equal(calls.filter((loaded) => loaded === name).length, 1, name);
  }
});

test("failed downloads stay readable and do not retry on every streaming frame", async (t) => {
  const warning = t.mock.method(console, "warn", () => {});
  const text = "```broken\n<img src=x onerror=alert(1)>\n```";
  renderMarkdown(text);
  assert.equal(await loadCodeLanguage("broken"), false);
  for (let frame = 0; frame < 10; frame++) renderMarkdown(text);
  assert.equal(calls.filter((name) => name === "broken").length, 1);
  assert.equal(warning.mock.callCount(), 1);
  assert.match(renderMarkdown(text), /&lt;img/);
  assert.equal(isCodeLanguageReady("broken"), false);
});

test("the full installed catalogue and aliases remain available, including rare languages", async () => {
  assert.equal(await loadCodeLanguage("wl"), true);
  assert.match(
    codeHighlighter.highlight("Plot[Sin[x], {x, 0, Pi}]", { language: "wl" }).value,
    /hljs-built_in/,
  );
  await Promise.all(languages.map(loadCodeLanguage));
  for (const [alias, name] of Object.entries(aliases)) {
    assert.equal(isCodeLanguageReady(alias), true, alias);
    assert.equal(codeHighlighter.getLanguage(alias), codeHighlighter.getLanguage(name), alias);
  }
  assert.equal(codeHighlighter.listLanguages().length, languages.length);
  assert.equal(dependencies.http.length, languages.length - 1);
  assert.match(
    codeHighlighter.highlight(
      'HTTP/1.1 200 OK\nContent-Type: application/json\n\n{"answer": 42}\n',
      { language: "http" },
    ).value,
    /language-json/,
  );
});
