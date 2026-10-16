import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const moduleId = "virtual:highlight-languages";
const resolvedId = `\0${moduleId}`;

// Read the installed language catalogue at build time; ship only its lazy loaders.
export function languageMetadata() {
  const hljs = require("highlight.js");
  const languages = hljs.listLanguages();
  const aliases = Object.fromEntries(languages.map((name) => [name, name]));
  for (const name of languages) {
    for (const alias of hljs.getLanguage(name).aliases || []) aliases[alias] = name;
  }
  const dependencies = {};
  for (const name of languages) {
    const seen = new WeakSet();
    const embedded = new Set();
    const visit = (mode) => {
      if (!mode || typeof mode !== "object" || seen.has(mode)) return;
      seen.add(mode);
      // An empty sublanguage list auto-detects against the entire catalogue (HTTP bodies).
      const subLanguages =
        Array.isArray(mode.subLanguage) && !mode.subLanguage.length
          ? languages
          : [mode.subLanguage].flat();
      for (const sub of subLanguages) {
        if (Object.hasOwn(aliases, sub) && aliases[sub] !== name) embedded.add(aliases[sub]);
      }
      Object.values(mode).forEach((value) => {
        if (Array.isArray(value)) value.forEach(visit);
        else visit(value);
      });
    };
    visit(hljs.getLanguage(name));
    dependencies[name] = [...embedded];
  }
  return { languages, aliases, dependencies };
}

export function highlightLanguages() {
  return {
    name: "highlight-languages",
    resolveId(id) {
      if (id === moduleId) return resolvedId;
    },
    load(id) {
      if (id !== resolvedId) return;
      const { languages, aliases, dependencies } = languageMetadata();
      const loaders = languages.map(
        (name) => `${JSON.stringify(name)}: () => import("highlight.js/lib/languages/${name}")`,
      );
      return `export default { aliases: ${JSON.stringify(aliases)},
        dependencies: ${JSON.stringify(dependencies)}, loaders: {${loaders.join(",")}} };`;
    },
  };
}
