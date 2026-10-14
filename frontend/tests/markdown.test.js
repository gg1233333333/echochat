import test from "node:test";
import assert from "node:assert/strict";
import { renderMarkdown } from "../src/utils/markdown.js";

test("model raw HTML and script URLs cannot become executable markup", () => {
  const output = renderMarkdown(
    "<img src=x onerror=alert(1)>\n<script>alert(1)</script>\n[link](javascript:alert(1))",
  );
  assert.doesNotMatch(output, /<img|<script|href="javascript:/);
  assert.match(output, /&lt;img/);
});

test("malicious fence language and code remain escaped with a fixed copy control", () => {
  const output = renderMarkdown('```js" onclick="alert(1)\n<img src=x onerror=alert(1)>\n```');
  assert.doesNotMatch(output, /<img|onclick=/);
  assert.match(output, /&lt;img/);
  assert.match(output, /<button class="copy-btn" type="button">复制<\/button>/);
});

test("fenced code shows its actual language without altering code contents", () => {
  const output = renderMarkdown('```python\nprint("hello")\n```');
  assert.match(output, /<span class="code-language">python<\/span>/);
  assert.match(output, /hello/);
  assert.match(renderMarkdown("```\nplain text\n```"), /code-language">代码<\/span>/);
});
