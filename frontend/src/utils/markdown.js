import MarkdownIt from "markdown-it";
import { codeHighlighter, isCodeLanguageReady, loadCodeLanguage } from "./codeHighlight.js";

export const markdown = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
  typographer: true,
  highlight(code, language) {
    // Class names are fixed: user-provided fence labels never become HTML attributes.
    if (language && isCodeLanguageReady(language)) {
      return `<pre><code class="hljs">${codeHighlighter.highlight(code, { language }).value}</code></pre>`;
    }
    if (language) void loadCodeLanguage(language);
    return `<pre><code class="hljs">${markdown.utils.escapeHtml(code)}</code></pre>`;
  },
});

const fence = markdown.renderer.rules.fence;
markdown.renderer.rules.fence = (...args) => {
  const info = args[0][args[1]].info.trim();
  const language = /^[a-zA-Z0-9_+#.-]{1,32}$/.test(info) ? info : "代码";
  const label = `<span class="code-language">${markdown.utils.escapeHtml(language)}</span>`;
  return fence(...args)
    .replace("<pre>", `<pre>${label}`)
    .replace("</pre>", '<button class="copy-btn" type="button">复制</button></pre>');
};

export const renderMarkdown = (text) => markdown.render(text || "");

export function markdownPlainText(text) {
  const container = document.createElement("div");
  container.style.cssText = "position:fixed;left:-10000px;top:0;white-space:normal";
  container.innerHTML = renderMarkdown(text);
  container.querySelectorAll(".copy-btn,.code-language").forEach((element) => element.remove());
  document.body.appendChild(container);
  const result = container.innerText;
  container.remove();
  return result.trim();
}
