import core from "highlight.js/lib/core";
import { shallowRef } from "vue";

export const codeHighlighter = core.newInstance();
export const highlightRevision = shallowRef(0);
let registry;
const definitions = new Map();
const requests = new Map();
const ready = new Set();

export function configureCodeHighlight(languages) {
  registry = languages;
}

const canonicalName = (label) => {
  const name = label.toLowerCase();
  return registry && Object.hasOwn(registry.aliases, name) ? registry.aliases[name] : null;
};

export const isCodeLanguageReady = (label) => ready.has(canonicalName(label));

export function loadCodeLanguage(label) {
  const name = canonicalName(label);
  if (!name) return Promise.resolve(false);
  if (ready.has(name)) return Promise.resolve(true);
  if (requests.has(name)) return requests.get(name);
  const required = new Set();
  const collect = (language) => {
    if (required.has(language)) return;
    required.add(language);
    registry.dependencies[language].forEach(collect);
  };
  collect(name);
  const pending = Promise.all(
    [...required].map((language) => {
      if (!definitions.has(language)) {
        definitions.set(
          language,
          registry.loaders[language]().then((module) => {
            codeHighlighter.registerLanguage(language, module.default);
          }),
        );
      }
      return definitions.get(language);
    }),
  )
    .then(() => {
      required.forEach((language) => ready.add(language));
      highlightRevision.value++;
      return true;
    })
    .catch((error) => {
      console.warn(`代码高亮语法加载失败（${name}），保留纯文本。`, error);
      return false;
    });
  requests.set(name, pending);
  return pending;
}
