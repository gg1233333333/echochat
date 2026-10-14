import config from '../frontend/vite.config.js';

export default {
  ...config,
  server: {
    ...config.server,
    port: 5174,
    proxy: { '/api': { target: 'http://127.0.0.1:8001' } },
  },
};
