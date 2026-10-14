import { watch } from "vue";

export function useDynamicFavicon(favicon) {
  watch(favicon, (href) => {
    let link = document.querySelector('link[rel*="icon"]');
    if (!link) {
      link = document.createElement("link");
      link.rel = "icon";
      document.head.appendChild(link);
    }
    link.href = href || "/favicon.svg";
  }, { immediate: true });
}
