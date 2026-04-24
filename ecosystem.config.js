module.exports = {
  apps: [
    {
      name: 'openclaw-gateway',
      script: 'openclaw',
      args: 'gateway --port 5345',
      interpreter: 'none',
      env: {
        OPENCLAW_CONFIG_PATH: '/root/.openclaw/openclaw.json',
        OPENCLAW_STATE_DIR: '/root/.openclaw',
        NODE_ENV: 'production'
      },
      restart_delay: 5000,
      max_restarts: 10,
      autorestart: true,
      watch: true,
      ignore_watch: ["logs", "node_modules", ".git", "workspace-state.json"]
    }
  ]
};
