import { createApp } from "vue";
import { createPinia } from "pinia";
import VueVirtualScroller from "vue-virtual-scroller";
import "vue-virtual-scroller/dist/vue-virtual-scroller.css";

import App from "./App.vue";
import { useThemeStore } from "@/stores/theme";

const app = createApp(App);
const pinia = createPinia();

// 注册全局插件：长列表采用虚拟滚动以提升性能
app.use(VueVirtualScroller);
app.use(pinia);

// 初始化主题，在应用挂载前同步当前模式
const themeStore = useThemeStore(pinia);
themeStore.initialize();

app.mount("#app");
